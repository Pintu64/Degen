from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from redis.asyncio import Redis
from app.bot.handlers import owner_router
from app.config import Settings
from app.database.session import create_engine, create_session_factory
from app.market.dexscreener import DexScreenerProvider
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine
from app.services.analysis import AnalysisService

async def run_bot(settings:Settings):
    settings.validate_runtime("bot"); engine=create_engine(settings); sessions=create_session_factory(engine); provider=DexScreenerProvider(settings); analysis=AnalysisService(FilterEngine(settings),RiskAnalyzer(),ScoringEngine(settings)); bot=Bot(settings.telegram_bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML)); dp=Dispatcher(); dp.include_router(owner_router(settings,sessions,provider,analysis))
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await provider.close(); await engine.dispose(); await bot.session.close()
