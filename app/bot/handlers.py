from __future__ import annotations
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.config import Settings
from app.database.repository import Repository
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider
from app.services.analysis import AnalysisService
from redis.asyncio import Redis

def owner_router(settings:Settings,sessions:async_sessionmaker[AsyncSession],provider:DexScreenerProvider,analysis:AnalysisService)->Router:
    router=Router()
    @router.message.outer_middleware()
    async def owner_only(handler,event,data):
        user=getattr(event,"from_user",None)
        if not user or user.id!=settings.owner_telegram_id:
            if isinstance(event,Message): await event.answer("Unauthorized.")
            return None
        return await handler(event,data)
    @router.message(Command("start","help"))
    async def start(m:Message): await m.answer("Private market scanner online.\n\n/start /status /active /history /stats /call &lt;id&gt; /scan [sol|eth|bsc] /settings",parse_mode="HTML")
    @router.message(Command("status"))
    async def status(m:Message):
        db="OFFLINE"; redis_status="OFFLINE"; active=0; scanner="OFFLINE"; tracker="OFFLINE"
        try:
            async with sessions() as s: active=len(await Repository(s).active_calls()); db="ONLINE"
        except Exception: pass
        redis=Redis.from_url(settings.redis_url,decode_responses=True)
        try:
            await redis.ping(); redis_status="ONLINE"; scanner="ONLINE" if await redis.exists("heartbeat:scanner") else "OFFLINE"; tracker="ONLINE" if await redis.exists("heartbeat:tracker") else "OFFLINE"
        except Exception: pass
        finally: await redis.aclose()
        await m.answer(f"BOT STATUS\n\nScanner: {scanner}\nTracker: {tracker}\nSolana: {'ENABLED' if 'solana' in settings.enabled_chains else 'DISABLED'}\nEthereum: {'ENABLED' if 'ethereum' in settings.enabled_chains else 'DISABLED'}\nBNB: {'ENABLED' if 'bsc' in settings.enabled_chains else 'DISABLED'}\nDatabase: {db}\nRedis: {redis_status}\nActive Calls: {active}")
    @router.message(Command("active"))
    async def active(m:Message):
        async with sessions() as s: calls=await Repository(s).active_calls()
        text="ACTIVE TRACKING\n\n"+"\n".join(f"{c.id}. ${c.token.symbol or 'UNKNOWN'} - {c.current_multiple:.2f}X" for c in calls[:25]) if calls else "No active calls."
        await m.answer(text)
    @router.message(Command("history"))
    async def history(m:Message):
        async with sessions() as s: calls=await Repository(s).call_history()
        text="CALL HISTORY\n\n"+"\n".join(f"{c.id}. ${c.token.symbol or 'UNKNOWN'} - {c.status} - ATH {c.highest_multiple:.2f}X" for c in calls) if calls else "No call history."
        await m.answer(text)
    @router.message(Command("call"))
    async def call(m:Message,command:CommandObject):
        if not command.args or not command.args.isdigit(): await m.answer("Usage: /call <id>"); return
        async with sessions() as s: c=await Repository(s).get_call(int(command.args))
        if not c: await m.answer("Call not found."); return
        marks="\n".join(("[HIT]" if x.status=="HIT" else "[ ]")+f" {x.target_multiple}X" for x in sorted(c.milestones,key=lambda x:x.target_multiple))
        await m.answer(f"CALL #{c.id}\n\n${c.token.symbol or 'UNKNOWN'} | {c.token.chain.upper()}\nReference: {c.reference_price}\nCurrent: {c.current_price}\nCurrent multiple: {c.current_multiple:.2f}X\nObserved ATH: {c.highest_multiple:.2f}X\n\nMilestones:\n{marks}\n\nStatus: {c.status}")
    @router.message(Command("stats"))
    async def stats(m:Message):
        async with sessions() as s: x=await Repository(s).stats()
        marks="\n".join(f"{k}X reached: {v}" for k,v in x["milestones"].items())
        await m.answer(f"PERFORMANCE STATISTICS\n\nTotal Calls: {x['total']}\nActive: {x['active']}\nClosed: {x['closed']}\nAverage observed ATH: {x['average_ath']:.2f}X\nMedian observed ATH: {x['median_ath']:.2f}X\nMaximum observed ATH: {x['maximum_ath']:.2f}X\nCalls below 1X: {x['below_1x']}\nCalls at/above 1X: {x['above_1x']}\n\n{marks}")
    @router.message(Command("settings"))
    async def settings_cmd(m:Message):
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Refresh",callback_data="settings:refresh")]])
        await m.answer(f"SETTINGS\n\nMinimum Score: {settings.min_score}\nMinimum Liquidity: ${settings.min_liquidity_usd}\nScan Interval: {settings.scan_interval_seconds}s\nTracking Interval: {settings.tracking_interval_seconds}s\nChains: {', '.join(settings.enabled_chains)}\nMilestones: {', '.join(map(str,settings.default_milestones))}",reply_markup=kb)
    @router.callback_query(F.data=="settings:refresh")
    async def refresh(q:CallbackQuery): await q.answer("Settings loaded from environment.")
    @router.message(Command("scan"))
    async def scan(m:Message,command:CommandObject):
        mapping={"sol":Chain.SOLANA,"solana":Chain.SOLANA,"eth":Chain.ETHEREUM,"ethereum":Chain.ETHEREUM,"bsc":Chain.BSC,"bnb":Chain.BSC}; chains=[mapping[command.args.lower()]] if command.args and command.args.lower() in mapping else [Chain(x) for x in settings.enabled_chains]
        await m.answer("Scanning current provider data...")
        candidates=[]
        for chain in chains:
            for snap in await provider.discover_tokens(chain): candidates.append(analysis.analyze(snap))
        candidates.sort(key=lambda a:a.score.score,reverse=True)
        await m.answer("TOP CURRENT CANDIDATES\n\n"+("\n".join(f"{i}. ${a.snapshot.symbol or 'UNKNOWN'} [{a.snapshot.chain.value}] - {a.score.score}/100" for i,a in enumerate(candidates[:10],1)) or "No candidates returned."))
    return router
