from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.formatting import (
    active_text,
    call_text,
    call_usage,
    candidate_text,
    chart_url_for,
    close_usage,
    explorer_url,
    history_text,
    scan_list_text,
    settings_text,
    start_text,
    stats_text,
    status_text,
)
from app.bot.keyboards import (
    NAV_LABELS,
    SHORT_CHAIN,
    call_inline,
    calls_inline,
    close_confirm_inline,
    home_inline,
    main_reply_keyboard,
    scan_inline,
    scan_results_inline,
    settings_inline,
    token_inline,
)
from app.config import Settings
from app.database.repository import Repository
from app.domain import CandidateAnalysis, Chain
from app.market.dexscreener import DexScreenerProvider, valid_contract_address
from app.services.analysis import AnalysisService

logger = logging.getLogger(__name__)

_DEX_URL_RE = re.compile(r"https?://(?:www\.)?dexscreener\.com/([^/?#]+)/([^/?#]+)", re.IGNORECASE)
_CHAIN_ALIASES = {
    "sol": Chain.SOLANA,
    "solana": Chain.SOLANA,
    "eth": Chain.ETHEREUM,
    "ethereum": Chain.ETHEREUM,
    "bsc": Chain.BSC,
    "bnb": Chain.BSC,
}


def _chain_list(settings: Settings, argument: str | None) -> list[Chain]:
    if argument:
        chain = _CHAIN_ALIASES.get(argument.strip().lower())
        if chain:
            return [chain]
    return [Chain(name) for name in settings.enabled_chains]


def _parse_lookup(text: str) -> tuple[Chain | None, str | None]:
    value = text.strip()
    match = _DEX_URL_RE.fullmatch(value)
    if match:
        chain = _CHAIN_ALIASES.get(match.group(1).lower())
        address = match.group(2)
        return (chain, address) if chain and valid_contract_address(chain, address) else (None, None)
    if valid_contract_address(Chain.SOLANA, value):
        return Chain.SOLANA, value
    if valid_contract_address(Chain.ETHEREUM, value):
        return None, value
    return None, None


def _is_private_owner(event, owner_id: int) -> bool:
    user = getattr(event, "from_user", None)
    message = getattr(event, "message", None) or event
    chat = getattr(message, "chat", None)
    return bool(user and chat and user.id == owner_id and chat.id == owner_id)


async def _answer(message: Message, text: str, **kwargs) -> Message:
    return await message.answer(text, parse_mode="HTML", **kwargs)


async def _edit(query: CallbackQuery, text: str, **kwargs) -> None:
    try:
        await query.message.edit_text(text, parse_mode="HTML", **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
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
        await _answer(message, await status_view(), reply_markup=home_inline())

    async def active_view():
        async with sessions() as session:
            calls = await Repository(session).active_calls()
        return active_text(calls), calls

    async def show_active(message: Message) -> None:
        text, calls = await active_view()
        await _answer(message, text, reply_markup=calls_inline(calls))

    async def history_view():
        async with sessions() as session:
            calls = await Repository(session).call_history()
        return history_text(calls), calls

    async def show_history(message: Message) -> None:
        text, calls = await history_view()
        await _answer(message, text, reply_markup=calls_inline(calls))

    async def stats_view() -> str:
        async with sessions() as session:
            return stats_text(await Repository(session).stats())

    async def show_stats(message: Message) -> None:
        await _answer(message, await stats_view(), reply_markup=home_inline())

    async def show_settings(message: Message) -> None:
        await _answer(message, settings_text(settings), reply_markup=settings_inline())

    async def collect_candidates(chains: list[Chain]) -> list[CandidateAnalysis]:
        candidates: list[CandidateAnalysis] = []
        for chain in chains:
            try:
                candidates.extend(analysis.analyze(snapshot) for snapshot in await provider.discover_tokens(chain))
            except Exception:
                logger.exception("BOT_SCAN_PROVIDER_FAILED", extra={"chain": chain.value})
        candidates.sort(key=lambda item: item.score.score, reverse=True)
        return candidates

    async def show_scan(message: Message, argument: str | None = None) -> None:
        progress = await _answer(message, "Scanning current provider data…")
        candidates = await collect_candidates(_chain_list(settings, argument))
        label = argument.strip().upper() if argument else "ALL CHAINS"
        await progress.edit_text(scan_list_text(candidates, label), parse_mode="HTML", reply_markup=scan_results_inline(candidates))

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

    @router.message(Command("call"))
    async def call(message: Message, command: CommandObject) -> None:
        if not command.args or not command.args.strip().isdigit():
            await _answer(message, call_usage())
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(command.args.strip()))
        if not item:
            await _answer(message, "Call not found.", reply_markup=home_inline())
            return
        chart = chart_url_for(None, item.token.chain, item.token.contract_address)
        await _answer(message, call_text(item), reply_markup=call_inline(item.id, chart, item.status == "ACTIVE"))

    @router.message(Command("close"))
    async def close(message: Message, command: CommandObject) -> None:
        if not command.args or not command.args.strip().isdigit():
            await _answer(message, close_usage())
            return
        async with sessions() as session:
            item = await Repository(session).get_call(int(command.args.strip()))
        if not item:
            await _answer(message, "Call not found.", reply_markup=home_inline())
        elif item.status != "ACTIVE":
            await _answer(message, "That call is already closed.", reply_markup=call_inline(item.id, active=False))
        else:
            await _answer(message, call_text(item) + "\n\n<b>Close this call?</b>", reply_markup=close_confirm_inline(item.id))

    @router.message(F.text.in_(NAV_LABELS))
    async def reply_navigation(message: Message) -> None:
        action = NAV_LABELS[message.text or ""]
        if action == "scan":
            await show_scan(message)
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
        for selected_chain in ([chain] if chain else _chain_list(settings, None)):
            try:
                item = await _analysis_for(provider, analysis, selected_chain, address)
            except Exception:
                logger.exception("BOT_TOKEN_LOOKUP_FAILED", extra={"chain": selected_chain.value})
                continue
            if item:
                await _answer(message, candidate_text(item), reply_markup=token_inline(selected_chain, item.snapshot.contract_address, chart_url_for(item.snapshot), explorer_url(selected_chain, item.snapshot.contract_address)))
                return
        await _answer(message, "No market pair found for that contract or DexScreener URL.", reply_markup=home_inline())

    @router.callback_query(F.data == "nav:home")
    async def nav_home(query: CallbackQuery) -> None:
        await query.answer()
        await _edit(query, start_text(), reply_markup=home_inline())

    @router.callback_query(F.data.startswith("nav:"))
    async def nav(query: CallbackQuery) -> None:
        action = (query.data or "").split(":", 1)[1]
        await query.answer()
        if action == "status":
            await _edit(query, await status_view(), reply_markup=home_inline())
        elif action == "active":
            text, calls = await active_view()
            await _edit(query, text, reply_markup=calls_inline(calls))
        elif action == "history":
            text, calls = await history_view()
            await _edit(query, text, reply_markup=calls_inline(calls))
        elif action == "stats":
            await _edit(query, await stats_view(), reply_markup=home_inline())
        elif action == "settings":
            await _edit(query, settings_text(settings), reply_markup=settings_inline())

    @router.callback_query(F.data.startswith("scan:"))
    async def scan_callback(query: CallbackQuery) -> None:
        key = (query.data or "").split(":", 1)[1]
        await query.answer("Scanning…")
        candidates = await collect_candidates(_chain_list(settings, None if key == "all" else key))
        await _edit(query, scan_list_text(candidates, key.upper()), reply_markup=scan_results_inline(candidates))

    @router.callback_query(F.data.startswith("v:"))
    async def token_callback(query: CallbackQuery) -> None:
        _, short, address = (query.data or "").split(":", 2)
        chain = SHORT_CHAIN.get(short)
        if not chain:
            await query.answer("Unknown chain", show_alert=True)
            return
        await query.answer("Refreshing token…")
        try:
            item = await _analysis_for(provider, analysis, chain, address)
        except Exception:
            logger.exception("BOT_TOKEN_REFRESH_FAILED", extra={"chain": chain.value})
            await _edit(query, "Token data is unavailable right now.", reply_markup=scan_inline())
            return
        if not item:
            await _edit(query, "Token data is unavailable right now.", reply_markup=scan_inline())
            return
        await _edit(query, candidate_text(item), reply_markup=token_inline(chain, address, chart_url_for(item.snapshot), explorer_url(chain, address)))

    @router.callback_query(F.data.startswith("t:"))
    async def track_callback(query: CallbackQuery) -> None:
        _, short, address = (query.data or "").split(":", 2)
        chain = SHORT_CHAIN.get(short)
        if not chain:
            await query.answer("Unknown chain", show_alert=True)
            return
        await query.answer("Starting paper tracking…")
        try:
            item = await _analysis_for(provider, analysis, chain, address)
        except Exception:
            logger.exception("BOT_TRACK_LOOKUP_FAILED", extra={"chain": chain.value})
            await _edit(query, "Token data is unavailable right now.", reply_markup=scan_inline())
            return
        if not item or item.snapshot.price is None or item.snapshot.price <= 0:
            await _edit(query, "A valid current price is required before tracking.", reply_markup=scan_inline())
            return
        try:
            async with sessions() as session:
                repo = Repository(session)
                call_item = await repo.create_call(item, settings.default_milestones, query.message.message_id)
        except IntegrityError:
            await _edit(query, "This token already has an active call.", reply_markup=home_inline())
            return
        await _edit(query, "Tracking started.\n\n" + call_text(call_item), reply_markup=call_inline(call_item.id, chart_url_for(item.snapshot)))

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
        await query.answer()
        chart = chart_url_for(None, item.token.chain, item.token.contract_address)
        await _edit(query, call_text(item), reply_markup=call_inline(item.id, chart, item.status == "ACTIVE"))

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
            await _edit(query, call_text(item), reply_markup=call_inline(item.id, active=False))
            return
        await query.answer()
        await _edit(query, call_text(item) + "\n\n<b>Close this call?</b>", reply_markup=close_confirm_inline(item.id))

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
        await query.answer("Call closed")
        await _edit(query, call_text(item), reply_markup=call_inline(item.id, active=False))

    @router.callback_query(F.data == "settings:refresh")
    async def settings_refresh_legacy(query: CallbackQuery) -> None:
        await query.answer("Settings loaded from environment.")

    return router
