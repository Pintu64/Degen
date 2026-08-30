import importlib
import json
import pkgutil
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app
from app.bot.formatting import milestone_text, money
from app.bot.handlers import _is_private_owner, _parse_lookup, owner_router
from app.bot.keyboards import from_payload, main_reply_keyboard
from app.config import Settings
from app.database.repository import Repository
from app.domain import Chain, RiskLevel
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.services.cache import Coordination
from app.workers.telegram_worker import _payload
from app.workers.tracker_worker import _elapsed_text
from tests.test_analysis import snapshot


def test_all_application_modules_import():
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        importlib.import_module(module.name)


def test_handler_factory_registers_owner_routes():
    settings = Settings(_env_file=None, owner_telegram_id=1)
    router = owner_router(settings, MagicMock(), MagicMock(), MagicMock())
    assert router.message.handlers
    assert router.callback_query.handlers


def test_owner_authorization_requires_the_private_owner_chat():
    private = SimpleNamespace(from_user=SimpleNamespace(id=7), chat=SimpleNamespace(id=7))
    group = SimpleNamespace(from_user=SimpleNamespace(id=7), chat=SimpleNamespace(id=-100))
    stranger = SimpleNamespace(from_user=SimpleNamespace(id=8), chat=SimpleNamespace(id=8))
    assert _is_private_owner(private, 7)
    assert not _is_private_owner(group, 7)
    assert not _is_private_owner(stranger, 7)


def test_plain_text_is_not_misread_as_contract_lookup():
    assert _parse_lookup("hello scanner") == (None, None)
    assert _parse_lookup("https://dexscreener.com/ethereum/0x" + "a" * 40) == (
        Chain.ETHEREUM,
        "0x" + "a" * 40,
    )


def test_tiny_money_values_are_not_rendered_as_zero():
    assert money(Decimal("0.000000000001")) == "$0.000000000001"
    assert money(Decimal("NaN")) == "Data unavailable"


def test_milestone_details_have_valid_line_breaks():
    call = SimpleNamespace(token=SimpleNamespace(symbol="TOK"), reference_price=Decimal("1"))
    milestone = SimpleNamespace(target_multiple=Decimal("2"), hit_price=Decimal("2"))
    text = milestone_text(call, milestone, Decimal("2"), "Observed ATH: 2.00X")
    assert "Multiple: 2.00X\nObserved ATH" in text


def test_reply_keyboard_includes_help_action():
    labels = [button.text for row in main_reply_keyboard().keyboard for button in row]
    assert "Help" in labels


def test_payload_keyboard_ignores_malformed_or_oversized_callbacks():
    markup = from_payload([
        "bad row",
        [{"text": "Open", "callback": "c:1"}, {"text": "Bad", "callback": "x" * 65}],
    ])
    assert markup is not None
    assert len(markup.inline_keyboard[0]) == 1


def test_outbound_payload_validation():
    assert _payload(json.dumps({"text": "ok"}))["text"] == "ok"
    with pytest.raises(ValueError):
        _payload(json.dumps({"text": ""}))
    with pytest.raises(ValueError):
        _payload(json.dumps({"text": "x" * 4097}))
    with pytest.raises(ValueError):
        _payload(json.dumps({"text": "ok", "call_id": True}))
    with pytest.raises(ValueError):
        _payload(json.dumps({"text": "ok", "call_id": 1, "milestone_id": 2}))


@pytest.mark.asyncio
async def test_coordination_enqueues_fifo_compatible_side():
    redis = AsyncMock()
    await Coordination(redis).enqueue("queue", "payload")
    redis.lpush.assert_awaited_once_with("queue", "payload")


@pytest.mark.asyncio
async def test_coordination_recovery_preserves_inflight_fifo_order():
    class Pipeline:
        def __init__(self):
            self.calls = []
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        def delete(self, queue):
            self.calls.append(("delete", queue))
        def rpush(self, queue, *payloads):
            self.calls.append(("rpush", queue, payloads))
        async def execute(self):
            return []

    redis = AsyncMock()
    redis.lrange.return_value = ["newer", "older"]
    pipeline = Pipeline()
    redis.pipeline = MagicMock(return_value=pipeline)
    await Coordination(redis).recover_processing("processing", "queue")
    assert pipeline.calls == [("delete", "processing"), ("rpush", "queue", ("newer", "older"))]


@pytest.mark.asyncio
async def test_close_call_is_atomic_and_reloads_relationships():
    result = MagicMock()
    result.scalar_one_or_none.return_value = 7
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    repo = Repository(session)
    closed = object()
    repo.get_call = AsyncMock(return_value=closed)

    assert await repo.close_call(7) is closed
    session.commit.assert_awaited_once()
    repo.get_call.assert_awaited_once_with(7)
    assert "calls.status" in str(session.execute.await_args.args[0])


def test_filter_allows_exact_holder_limit_and_rejects_above_it():
    settings = Settings(_env_file=None)
    assert FilterEngine(settings).evaluate(snapshot(top_holder_percentage=Decimal("35"))).passed
    result = FilterEngine(settings).evaluate(snapshot(top_holder_percentage=Decimal("35.01")))
    assert not result.passed
    assert "Top-holder concentration too high" in result.reasons


def test_known_risk_plus_missing_security_data_is_high_risk():
    result = RiskAnalyzer().assess(snapshot(mint_authority=True))
    assert result.level == RiskLevel.HIGH


@pytest.mark.parametrize("kwargs", [
    {"database_url": "sqlite:///local.db"},
    {"redis_url": "http://localhost:6379"},
    {"enabled_chains": ""},
    {"max_price_jump_multiple": "1"},
])
def test_invalid_runtime_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **kwargs)


def test_elapsed_text_is_compact_and_stable():
    from datetime import timedelta

    assert _elapsed_text(timedelta(days=1, hours=2, minutes=3, seconds=4)) == "1d 2h 3m 4s"
