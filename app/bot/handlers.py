from __future__ import annotations

import asyncio
import logging
import re
from time import monotonic

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.formatting import (
    active_text,
    already_tracked_text,
    ca_usage,
    call_text,
    call_usage,
    candidate_text,
    chains_text,
    chart_url_for,
    checking_text,
    clip_html,
    close_prompt_suffix,
    close_usage,
    explorer_url,
    history_text,
    lookup_miss_text,
    need_price_text,
    not_found_text,
    scan_list_text,
    scan_menu_text,
    scanning_text,
    settings_text,
    start_text,
    stats_text,
    status_text,
    track_usage,
    unavailable_text,
)
from app.bot.keyboards import (
    NAV_LABELS,
    SHORT_CHAIN,
    call_inline,
    calls_inline,
    chains_inline,
    close_confirm_inline,
    home_inline,
    main_reply_keyboard,
    scan_inline,
    scan_results_inline,
    settings_inline,
    stats_inline,
    status_inline,
    token_inline,
)
from app.scanner.risk_scan import evaluate_deep_risk
from app.scanner.security import scan_coin
from app.services.cache import Coordination
from app.config import Settings
from app.database.repository import Repository
from app.domain import CandidateAnalysis, Chain
from app.market.dexscreener import DexScreenerProvider, valid_contract_address
from app.services.analysis import AnalysisService

logger = logging.getLogger(__name__)

_DEX_URL_RE = re.compile(r"https?://(?:www\.)?dexscreener\.com/([^/?#]+)/([^/?#]+)", re.IGNORECASE)
_GMGN_URL_RE = re.compile(r"https?://(?:www\.)?gmgn\.ai/([^/?#]+)/token/([^/?#]+)", re.IGNORECASE)
_BIRDEYE_URL_RE = re.compile(r"https?://(?:www\.)?birdeye\.so/token/([^/?#]+)", re.IGNORECASE)
_GECKO_URL_RE = re.compile(r"https?://(?:www\.)?geckoterminal\.com/([^/?#]+)/(?:tokens|pools)/([^/?#]+)", re.IGNORECASE)
_EXPLORER_URL_RE = re.compile(
    r"https?://(?:www\.)?(solscan\.io|basescan\.org|etherscan\.io|bscscan\.com)/(?:token|address)/([^/?#]+)",
    re.IGNORECASE,
)
_PUMP_URL_RE = re.compile(r"https?://(?:www\.)?pump\.fun/([^/?#]+)", re.IGNORECASE)
_CHAIN_ALIASES = {
    "sol": Chain.SOLANA,
    "solana": Chain.SOLANA,
    "eth": Chain.ETHEREUM,
    "ethereum": Chain.ETHEREUM,
    "ether": Chain.ETHEREUM,
    "bsc": Chain.BSC,
    "bnb": Chain.BSC,
    "base": Chain.BASE,
}
_EXPLORER_CHAIN = {
    "solscan.io": Chain.SOLANA,
    "basescan.org": Chain.BASE,
    "etherscan.io": Chain.ETHEREUM,
    "bscscan.com": Chain.BSC,
}


def _chain_list(settings: Settings, argument: str | None) -> list[Chain]:
    if argument:
        chain = _CHAIN_ALIASES.get(argument.strip().lower())
        if chain:
            return [chain]
    return [Chain(name) for name in settings.enabled_chains]


def _parse_lookup(text: str) -> tuple[Chain | None, str | None]:
    value = text.strip().split()[0] if text.strip() else ""
    match = _DEX_URL_RE.search(value)
    if match:
        chain = _CHAIN_ALIASES.get(match.group(1).lower())
        address = match.group(2)
        return (chain, address) if chain and valid_contract_address(chain, address) else (None, None)
    match = _GMGN_URL_RE.search(value)
    if match:
        chain = _CHAIN_ALIASES.get(match.group(1).lower())
        address = match.group(2)
        return (chain, address) if chain and valid_contract_address(chain, address) else (None, None)
    match = _GECKO_URL_RE.search(value)
    if match:
        chain = _CHAIN_ALIASES.get(match.group(1).lower())
        address = match.group(2)
        return (chain, address) if chain and valid_contract_address(chain, address) else (None, None)
    match = _EXPLORER_URL_RE.search(value)
    if match:
        chain = _EXPLORER_CHAIN.get(match.group(1).lower())
        address = match.group(2)
        return (chain, address) if chain and valid_contract_address(chain, address) else (None, None)
    match = _BIRDEYE_URL_RE.search(value)
    if match:
        address = match.group(1)
        if valid_contract_address(Chain.SOLANA, address):
            return Chain.SOLANA, address
        if valid_contract_address(Chain.BASE, address):
            return None, address
        return None, None
    match = _PUMP_URL_RE.search(value)
    if match and valid_contract_address(Chain.SOLANA, match.group(1)):
        return Chain.SOLANA, match.group(1)
    if valid_contract_address(Chain.SOLANA, value):
        return Chain.SOLANA, value
    if valid_contract_address(Chain.ETHEREUM, value) or valid_contract_address(Chain.BASE, value):
        return None, value
    return None, None


def _evm_order(enabled: list[Chain]) -> list[Chain]:
    preferred = [Chain.BASE, Chain.ETHEREUM, Chain.BSC]
    return [chain for chain in preferred if chain in enabled] + [chain for chain in enabled if chain.is_evm and chain not in preferred]


def _is_private_owner(event, owner_id: int) -> bool:
    user = getattr(event, "from_user", None)
    message = getattr(event, "message", None) or event
    chat = getattr(message, "chat", None)
    return bool(user and chat and user.id == owner_id and chat.id == owner_id)


async def _answer(message: Message, text: str, **kwargs) -> Message:
    return await message.answer(clip_html(text), parse_mode="HTML", **kwargs)


async def _edit(query: CallbackQuery, text: str, **kwargs) -> None:
    text = clip_html(text)
    message = query.message
    if message is None:
        return
    if message.photo:
        await message.answer(text, parse_mode="HTML", **kwargs)
        return
    try:
        await message.edit_text(text, parse_mode="HTML", **kwargs)
    except TelegramBadRequest as exc:
        detail = str(exc).lower()
        if "message is not modified" in detail:
            return
        if "no text in the message" in detail or "can't be edited" in detail or "message to edit not found" in detail:
            await message.answer(text, parse_mode="HTML", **kwargs)
            return
        raise


async def _analysis_for(provider: DexScreenerProvider, analysis: AnalysisService, chain: Chain, address: str) -> CandidateAnalysis | None:
    snapshot = await provider.get_snapshot(chain, address)
    return analysis.analyze(snapshot) if snapshot else None


def owner_router(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    provider: DexScreenerProvider,
    analysis: AnalysisService,
) -> Router:
    router = Router()

    @router.message.outer_middleware()
    async def owner_only(handler, event, data):
        if not _is_private_owner(event, settings.owner_telegram_id):
            return None
        return await handler(event, data)

    @router.callback_query.outer_middleware()
    async def owner_callback_only(handler, event, data):
        if not _is_private_owner(event, settings.owner_telegram_id):
            await event.answer("Unauthorized.", show_alert=True)
            return None
        return await handler(event, data)

    async def show_home(message: Message) -> None:
        await _answer(message, start_text(), reply_markup=home_inline())

    async def status_view() -> str:
        db = redis_status = scanner = tracker = telegram = "OFFLINE"
        active = 0
        try:
            async with sessions() as session:
                active = len(await Repository(session).active_calls())
                db = "ONLINE"
        except Exception:
            logger.exception("BOT_DATABASE_STATUS_FAILED")
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.ping()
            redis_status = "ONLINE"
            scanner = "ONLINE" if await redis.exists("heartbeat:scanner") else "OFFLINE"
            tracker = "ONLINE" if await redis.exists("heartbeat:tracker") else "OFFLINE"
            telegram = "ONLINE" if await redis.exists("heartbeat:telegram") else "OFFLINE"
        except Exception:
            logger.exception("BOT_REDIS_STATUS_FAILED")
        finally:
            await redis.aclose()
        return status_text(scanner, tracker, telegram, db, redis_status, active, settings.enabled_chains)

    async def show_status(message: Message) -> None:
        await _answer(message, await status_view(), reply_markup=status_inline())

    async def active_view():
        async with sessions() as session:
            calls = await Repository(session).active_calls()
        return active_text(calls), calls

    async def show_active(message: Message) -> None:
        text, calls = await active_view()
        await _answer(message, text, reply_markup=calls_inline(calls, back="nav:home"))

    async def history_view():
        async with sessions() as session:
            calls = await Repository(session).call_history()
        return history_text(calls), calls

    async def show_history(message: Message) -> None:
        text, calls = await history_view()
        await _answer(message, text, reply_markup=calls_inline(calls, back="nav:home"))

    async def stats_view() -> str:
        async with sessions() as session:
            return stats_text(await Repository(session).stats())

    async def show_stats(message: Message) -> None:
        await _answer(message, await stats_view(), reply_markup=stats_inline())

    async def show_settings(message: Message) -> None:
        await _answer(message, settings_text(settings), reply_markup=settings_inline())

    chains_memo: list[object] = [0.0, None]

    async def live_chains() -> list[Chain]:
        now = monotonic()
        cached = chains_memo[1]
        if cached is not None and now - float(chains_memo[0]) < 5:
            return list(cached)  # type: ignore[arg-type]
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            names = await Coordination(redis).enabled_chains(settings.enabled_chains)
        finally:
            await redis.aclose()
        result = [Chain(name) for name in names]
        chains_memo[0] = now
        chains_memo[1] = result
        return result

    async def show_chains(message: Message) -> None:
        chains = tuple(chain.value for chain in await live_chains())
        await _answer(message, chains_text(chains), reply_markup=chains_inline(chains))

    async def full_scan(item: CandidateAnalysis) -> CandidateAnalysis:
        item.coin_scan = await scan_coin(item.snapshot)
        item.deep_risk = evaluate_deep_risk(item)
        return analysis.degen.apply(item)

    async def attach_default_checks(candidates: list[CandidateAnalysis]) -> list[CandidateAnalysis]:
        async def one(item: CandidateAnalysis) -> None:
            try:
                item.coin_scan = await scan_coin(item.snapshot)
                item.deep_risk = evaluate_deep_risk(item)
                analysis.degen.apply(item)
            except Exception:
                logger.exception("DEFAULT_CHECK_FAILED", extra={"address": item.snapshot.contract_address})

        if candidates:
            await asyncio.gather(*(one(item) for item in candidates))
        safe = [item for item in candidates if not (item.coin_scan and item.coin_scan.fatal)]
        return safe or candidates

    async def collect_candidates(chains: list[Chain], limit: int | None = None) -> list[CandidateAnalysis]:
        candidates: list[CandidateAnalysis] = []
        cap = limit or settings.max_degen_picks
        try:
            discovered = await provider.discover_many(chains)
        except Exception:
            logger.exception("BOT_SCAN_PROVIDER_FAILED")
            discovered = {}
        for chain in chains:
            for snapshot in discovered.get(chain, []):
                candidates.append(analysis.analyze(snapshot))
        ranked = analysis.select_best(candidates, max(cap, 4))
        checked = await attach_default_checks(ranked)
        return checked[:cap]

    async def prior_calls(address: str):
        async with sessions() as session:
            repo = Repository(session)
            calls = await repo.calls_for_contract(address)
            history = await repo.price_history(calls[0].id) if calls else []
        return calls, history

    def token_card(item: CandidateAnalysis, back: str = "nav:scan"):
        snapshot = item.snapshot
        return token_inline(
            snapshot.chain,
            snapshot.contract_address,
            chart_url_for(snapshot),
            explorer_url(snapshot.chain, snapshot.contract_address),
            back=back,
            pair_address=snapshot.pair_address,
        )

    async def resolve_token(raw: str) -> CandidateAnalysis | None:
        chain, address = _parse_lookup(raw)
        if not address:
            return None
        enabled = await live_chains()
        if chain:
            order = [chain]
        elif address.startswith("0x"):
            order = _evm_order(enabled) or enabled
        else:
            order = enabled
        async def lookup(selected: Chain) -> CandidateAnalysis | None:
            try:
                return await _analysis_for(provider, analysis, selected, address)
            except Exception:
                logger.exception("BOT_TOKEN_LOOKUP_FAILED", extra={"chain": selected.value})
                return None

        if len(order) == 1:
            return await lookup(order[0])
        tasks = [asyncio.create_task(lookup(selected)) for selected in order]
        try:
            for task in asyncio.as_completed(tasks):
                item = await task
                if item:
                    for pending in tasks:
                        if not pending.done():
                            pending.cancel()
                    return item
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)
        return None

    async def show_lookup(message: Message, raw: str) -> None:
        progress = await _answer(message, checking_text())
        item = await resolve_token(raw)
        if not item:
            await progress.edit_text(clip_html(lookup_miss_text()), parse_mode="HTML", reply_markup=home_inline())
            return
        item = await full_scan(item)
        calls, history = await prior_calls(item.snapshot.contract_address)
        await progress.edit_text(
            clip_html(candidate_text(item, prior_calls=calls, price_history=history)),
            parse_mode="HTML",
            reply_markup=token_card(item, back="nav:home"),
        )

    async def start_personal_track(message: Message, item: CandidateAnalysis) -> None:
        if item.snapshot.price is None or item.snapshot.price <= 0:
            await _answer(message, need_price_text(), reply_markup=home_inline())
            return
        if item.coin_scan is None:
            item = await full_scan(item)
        try:
            async with sessions() as session:
                call_item = await Repository(session).create_call(item, settings.default_milestones, source="PERSONAL")
        except IntegrityError:
            await _answer(message, already_tracked_text(), reply_markup=home_inline())
            return
        await _answer(message, call_text(call_item), reply_markup=call_card(call_item, item.snapshot))

    def call_card(item, snapshot=None, active: bool | None = None):
        chain = Chain(item.token.chain)
        chart = chart_url_for(snapshot, item.token.chain, item.token.contract_address)
        pair = snapshot.pair_address if snapshot is not None else None
        is_active = item.status == "ACTIVE" if active is None else active
        return call_inline(item.id, chart, is_active, chain, item.token.contract_address, pair)

    async def show_scan_menu(message: Message) -> None:
        await _answer(message, scan_menu_text(), reply_markup=scan_inline())

    async def show_scan(message: Message, argument: str | None = None) -> None:
        if not argument:
            await show_scan_menu(message)
            return
        progress = await _answer(message, scanning_text())
        key = argument.strip().lower()
        limit = 1 if key in {"best", "top"} else settings.max_degen_picks
        chains = await live_chains() if key in {"all", "best", "top"} else _chain_list(settings, argument)
        candidates = await collect_candidates(chains, limit)
        label = "BEST DEGEN" if key in {"best", "top"} else argument.strip().upper()
        if key in {"best", "top"} and candidates:
            item = candidates[0]
            calls, history = await prior_calls(item.snapshot.contract_address)
            await progress.edit_text(
                clip_html(candidate_text(item, prior_calls=calls, price_history=history)),
                parse_mode="HTML",
                reply_markup=token_card(item, back="nav:scan"),
            )
            return
        await progress.edit_text(
            clip_html(scan_list_text(candidates, label)),
            parse_mode="HTML",
            reply_markup=scan_results_inline(candidates, key),
        )

    @router.message(Command("start", "help"))
    async def start(message: Message) -> None:
        await _answer(message, start_text(), reply_markup=main_reply_keyboard())

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        await show_status(message)

    @router.message(Command("active"))
    async def active(message: Message) -> None:
        await show_active(message)

    @router.message(Command("history"))
    async def history(message: Message) -> None:
        await show_history(message)

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        await show_stats(message)

    @router.message(Command("settings"))
    async def settings_command(message: Message) -> None:
        await show_settings(message)

    @router.message(Command("scan"))
    async def scan(message: Message, command: CommandObject) -> None:
        await show_scan(message, command.args)

    @router.message(Command("best"))
    async def best(message: Message) -> None:
        await show_scan(message, "best")

    @router.message(Command("check"))
    async def check_command(message: Message, command: CommandObject) -> None:
        if command.args:
            await show_lookup(message, command.args)
            return
        await _answer(message, ca_usage(), reply_markup=home_inline())

    @router.message(Command("ca"))
    async def ca_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await _answer(message, ca_usage(), reply_markup=home_inline())
            return
        await show_lookup(message, command.args)

    @router.message(Command("track"))
    async def track_command(message: Message, command: CommandObject) -> None:
        if not command.args:
            await _answer(message, track_usage(), reply_markup=home_inline())
            return
        item = await resolve_token(command.args)
        if not item:
            await _answer(message, lookup_miss_text(), reply_markup=home_inline())
            return
        await start_personal_track(message, item)

    @router.message(Command("mytracks"))
    async def mytracks(message: Message) -> None:
        await show_active(message)

    @router.message(Command("chains"))
    async def chains_command(message: Message) -> None:
        await show_chains(message)

    @router.message(Command("call"))
    async def call(message: Message, command: CommandObject) -> None:
        if not command.args or not command.args.strip().isdigit():
            await _answer(message, call_usage())
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(command.args.strip()))
        if not item:
            await _answer(message, not_found_text("Call"), reply_markup=home_inline())
            return
        await _answer(message, call_text(item), reply_markup=call_card(item))

    @router.message(Command("close"))
    async def close(message: Message, command: CommandObject) -> None:
        if not command.args or not command.args.strip().isdigit():
            await _answer(message, close_usage())
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(command.args.strip()))
        if not item:
            await _answer(message, not_found_text("Call"), reply_markup=home_inline())
        elif item.status != "ACTIVE":
            await _answer(message, call_text(item), reply_markup=call_card(item, active=False))
        else:
            await _answer(message, call_text(item) + close_prompt_suffix(), reply_markup=close_confirm_inline(item.id))

    @router.message(F.text.in_(NAV_LABELS))
    async def reply_navigation(message: Message) -> None:
        action = NAV_LABELS[message.text or ""]
        if action == "scan":
            await show_scan_menu(message)
        elif action == "best":
            await show_scan(message, "best")
        elif action == "check":
            await _answer(message, ca_usage(), reply_markup=home_inline())
        elif action == "status":
            await show_status(message)
        elif action == "active":
            await show_active(message)
        elif action == "history":
            await show_history(message)
        elif action == "stats":
            await show_stats(message)
        elif action == "settings":
            await show_settings(message)
        else:
            await show_home(message)

    @router.message(F.text)
    async def token_lookup(message: Message) -> None:
        chain, address = _parse_lookup(message.text or "")
        if not address:
            return
        await show_lookup(message, message.text or "")

    @router.callback_query(F.data == "nav:home")
    async def nav_home(query: CallbackQuery) -> None:
        await query.answer()
        await _edit(query, start_text(), reply_markup=home_inline())

    @router.callback_query(F.data.startswith("nav:"))
    async def nav(query: CallbackQuery) -> None:
        action = (query.data or "").split(":", 1)[1]
        await query.answer()
        if action == "scan":
            await _edit(query, scan_menu_text(), reply_markup=scan_inline())
        elif action == "check":
            await _edit(query, ca_usage(), reply_markup=home_inline())
        elif action == "status":
            await _edit(query, await status_view(), reply_markup=status_inline())
        elif action == "active":
            text, calls = await active_view()
            await _edit(query, text, reply_markup=calls_inline(calls, back="nav:home"))
        elif action == "history":
            text, calls = await history_view()
            await _edit(query, text, reply_markup=calls_inline(calls, back="nav:home"))
        elif action == "stats":
            await _edit(query, await stats_view(), reply_markup=stats_inline())
        elif action == "settings":
            await _edit(query, settings_text(settings), reply_markup=settings_inline())
        elif action == "chains":
            chains = tuple(chain.value for chain in await live_chains())
            await _edit(query, chains_text(chains), reply_markup=chains_inline(chains))

    @router.callback_query(F.data.startswith("scan:"))
    async def scan_callback(query: CallbackQuery) -> None:
        key = (query.data or "").split(":", 1)[1]
        await query.answer("✨ Hunting the best degen…")
        limit = 1 if key in {"best", "top"} else settings.max_degen_picks
        chains = await live_chains() if key in {"all", "best", "top"} else _chain_list(settings, key)
        candidates = await collect_candidates(chains, limit)
        label = "BEST DEGEN" if key in {"best", "top"} else key.upper()
        if key in {"best", "top"} and candidates:
            item = candidates[0]
            calls, history = await prior_calls(item.snapshot.contract_address)
            await _edit(
                query,
                candidate_text(item, prior_calls=calls, price_history=history),
                reply_markup=token_card(item, back="nav:scan"),
            )
            return
        await _edit(query, scan_list_text(candidates, label), reply_markup=scan_results_inline(candidates, key))

    @router.callback_query(F.data.startswith("v:"))
    async def token_callback(query: CallbackQuery) -> None:
        _, short, address = (query.data or "").split(":", 2)
        chain = SHORT_CHAIN.get(short)
        if not chain:
            await query.answer("Unknown chain", show_alert=True)
            return
        await query.answer("🔄 Refreshing token…")
        try:
            item = await _analysis_for(provider, analysis, chain, address)
        except Exception:
            logger.exception("BOT_TOKEN_REFRESH_FAILED", extra={"chain": chain.value})
            await _edit(query, unavailable_text(), reply_markup=scan_inline())
            return
        if not item:
            await _edit(query, unavailable_text(), reply_markup=scan_inline())
            return
        item = await full_scan(item)
        calls, history = await prior_calls(item.snapshot.contract_address)
        await _edit(
            query,
            candidate_text(item, prior_calls=calls, price_history=history),
            reply_markup=token_card(item),
        )

    @router.callback_query(F.data.startswith("t:"))
    async def track_callback(query: CallbackQuery) -> None:
        _, short, address = (query.data or "").split(":", 2)
        chain = SHORT_CHAIN.get(short)
        if not chain:
            await query.answer("Unknown chain", show_alert=True)
            return
        await query.answer("📌 Starting paper tracking…")
        try:
            item = await _analysis_for(provider, analysis, chain, address)
        except Exception:
            logger.exception("BOT_TRACK_LOOKUP_FAILED", extra={"chain": chain.value})
            await _edit(query, unavailable_text(), reply_markup=scan_inline())
            return
        if not item or item.snapshot.price is None or item.snapshot.price <= 0:
            await _edit(query, need_price_text(), reply_markup=scan_inline())
            return
        item = await full_scan(item)
        try:
            async with sessions() as session:
                repo = Repository(session)
                call_item = await repo.create_call(item, settings.default_milestones, query.message.message_id, source="PERSONAL")
        except IntegrityError:
            await _edit(query, already_tracked_text(), reply_markup=home_inline())
            return
        await _edit(query, call_text(call_item), reply_markup=call_card(call_item, item.snapshot))

    @router.callback_query(F.data.startswith("c:"))
    async def call_callback(query: CallbackQuery) -> None:
        call_id = (query.data or "").split(":", 1)[1]
        if not call_id.isdigit():
            await query.answer("Invalid call ID", show_alert=True)
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(call_id))
        if not item:
            await query.answer("Call not found", show_alert=True)
            return
        await query.answer("🔄 Refreshing call…")
        live = None
        chain = Chain(item.token.chain)
        try:
            live = await _analysis_for(provider, analysis, chain, item.token.contract_address)
            if live:
                live = await full_scan(live)
        except Exception:
            logger.exception("CALL_CHECK_FAILED")
        await _edit(query, call_text(item, live), reply_markup=call_card(item, live.snapshot if live else None))

    @router.callback_query(F.data.startswith("x:"))
    async def close_prompt(query: CallbackQuery) -> None:
        call_id = (query.data or "").split(":", 1)[1]
        if not call_id.isdigit():
            await query.answer("Invalid call ID", show_alert=True)
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(call_id))
        if not item:
            await query.answer("Call not found", show_alert=True)
            return
        if item.status != "ACTIVE":
            await query.answer("That call is already closed", show_alert=True)
            await _edit(query, call_text(item), reply_markup=call_card(item, active=False))
            return
        await query.answer()
        await _edit(query, call_text(item) + close_prompt_suffix(), reply_markup=close_confirm_inline(item.id))

    @router.callback_query(F.data.startswith("z:"))
    async def close_confirm(query: CallbackQuery) -> None:
        call_id = (query.data or "").split(":", 1)[1]
        if not call_id.isdigit():
            await query.answer("Invalid call ID", show_alert=True)
            return
        async with sessions() as session:
            item = await Repository(session).close_call(int(call_id))
        if not item:
            await query.answer("Call not found or already closed", show_alert=True)
            return
        await query.answer("🛑 Call closed")
        await _edit(query, call_text(item), reply_markup=call_card(item, active=False))

    @router.callback_query(F.data.startswith("chain:"))
    async def toggle_chain(query: CallbackQuery) -> None:
        name = (query.data or "").split(":", 1)[1]
        if name not in {"solana", "ethereum", "bsc", "base"}:
            await query.answer("Unknown chain", show_alert=True)
            return
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            coord = Coordination(redis)
            current = list(await coord.enabled_chains(settings.enabled_chains))
            if name in current:
                if len(current) == 1:
                    await query.answer("Keep at least one chain on.", show_alert=True)
                    return
                current.remove(name)
            else:
                current.append(name)
            updated = await coord.set_enabled_chains(current)
        finally:
            await redis.aclose()
        await query.answer(f"{name} {'on' if name in updated else 'off'}")
        await _edit(query, chains_text(updated), reply_markup=chains_inline(updated))

    @router.callback_query(F.data == "settings:refresh")
    async def settings_refresh_legacy(query: CallbackQuery) -> None:
        await query.answer("Settings loaded from environment.")

    return router
