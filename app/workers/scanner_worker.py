import asyncio, json
import logging
from sqlalchemy.exc import IntegrityError
from redis.asyncio import Redis
from app.bot.formatting import alert_text
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine
from app.scanner.ai_analyzer import AIAnalyzer
from app.services.alert import AlertEngine
from app.services.analysis import AnalysisService
from app.services.cache import Coordination

async def run_scanner(settings:Settings):
    engine=create_engine(settings); sessions=create_session_factory(engine); redis=Redis.from_url(settings.redis_url,decode_responses=True); coord=Coordination(redis); provider=DexScreenerProvider(settings); analyzer=AnalysisService(FilterEngine(settings),RiskAnalyzer(),ScoringEngine(settings)); ai=AIAnalyzer(settings); decision=AlertEngine(settings)
    try:
        while True:
            await coord.heartbeat("scanner",settings.scan_interval_seconds*3)
            async with sessions() as session: unsent_calls=await Repository(session).unsent_call_alerts()
            for unsent in unsent_calls:
                if await coord.acquire(f"call-notify:{unsent.id}",300):
                    text=f"<b>MARKET ALERT</b>\n\n<b>${unsent.token.symbol or 'UNKNOWN'}</b> | {unsent.token.chain.upper()}\nCall #{unsent.id}\n\nReference price: ${unsent.reference_price}\nInitial score: {unsent.initial_score}/100\nRisk: {unsent.initial_risk}\n\nTracking is active. Research and paper-tracking alert; this does not guarantee future performance."
                    await coord.enqueue("telegram:outbound",json.dumps({"kind":"alert","text":text,"call_id":unsent.id}))
            for chain_name in settings.enabled_chains:
                chain=Chain(chain_name)
                try: snapshots=await provider.discover_tokens(chain)
                except Exception:
                    logging.exception("PROVIDER_ERROR",extra={"chain":chain.value,"provider":provider.name}); continue
                for snap in snapshots:
                    analysis=analyzer.analyze(snap); qualified,_=decision.should_alert(analysis)
                    if not qualified: continue
                    if ai.available:
                        analysis.ai_summary=await ai.analyze(analysis)
                    key=f"alert:{chain.value}:{snap.contract_address}"
                    if not await coord.acquire(key,settings.token_cooldown_seconds): continue
                    try:
                        async with sessions() as session:
                            repo=Repository(session)
                            if await repo.has_active_call(chain,snap.contract_address): continue
                            call=await repo.create_call(analysis,settings.default_milestones)
                    except IntegrityError:
                        continue
                    if await coord.acquire(f"call-notify:{call.id}",300):
                        await coord.enqueue("telegram:outbound",json.dumps({"kind":"alert","text":alert_text(analysis,call.id),"call_id":call.id}))
            await asyncio.sleep(settings.scan_interval_seconds)
    finally: await provider.close(); await redis.aclose(); await engine.dispose()
