import asyncio, json
import logging
from sqlalchemy.exc import IntegrityError
from app.bot.formatting import alert_text, chart_url_for, recovery_alert_text
from app.bot.keyboards import alert_buttons
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider
from app.scanner.degen import DegenRanker
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine
from app.scanner.ai_analyzer import AIAnalyzer
from app.scanner.risk_scan import evaluate_deep_risk
from app.scanner.security import scan_coin
from app.services.alert import AlertEngine
from app.services.analysis import AnalysisService
from app.services.cache import Coordination

async def run_scanner(settings: Settings):
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    coord = Coordination(sessions)
    provider = DexScreenerProvider(settings)
    ranker = DegenRanker(settings)
    analyzer = AnalysisService(FilterEngine(settings), RiskAnalyzer(), ScoringEngine(settings), ranker, settings)
    ai = AIAnalyzer(settings)
    decision = AlertEngine(settings, ranker)
    try:
        while True:
            await coord.heartbeat("scanner", settings.scan_interval_seconds * 3)
            async with sessions() as session:
                unsent_calls = await Repository(session).unsent_call_alerts()
            for unsent in unsent_calls:
                if await coord.acquire(f"call-notify:{unsent.id}", 300):
                    chart = chart_url_for(None, unsent.token.chain, unsent.token.contract_address)
                    await coord.enqueue("telegram:outbound", json.dumps({
                        "kind": "alert",
                        "text": recovery_alert_text(unsent),
                        "call_id": unsent.id,
                        "buttons": alert_buttons(unsent.id, chart, unsent.token.chain, unsent.token.contract_address),
                    }))
            qualified = []
            enabled = await coord.enabled_chains(settings.enabled_chains)
            chains = [Chain(name) for name in enabled]
            try:
                discovered = await provider.discover_many(chains)
            except Exception:
                logging.exception("PROVIDER_ERROR")
                discovered = {}
            for chain in chains:
                try:
                    snapshots = discovered.get(chain, [])
                except Exception:
                    logging.exception("PROVIDER_ERROR", extra={"chain": chain.value, "provider": provider.name})
                    continue
                for snap in snapshots:
                    analysis = analyzer.analyze(snap)
                    if ranker.prefilter_ok(analysis):
                        qualified.append(analysis)
            picks = analyzer.select_best(qualified, 3)
            if not picks:
                await asyncio.sleep(settings.scan_interval_seconds)
                continue
            called = False
            for analysis in picks:
                if called:
                    break
                snap = analysis.snapshot
                key = f"alert:{snap.chain.value}:{snap.contract_address}"
                if await coord.exists(key):
                    continue
                async with sessions() as session:
                    if await Repository(session).has_active_call(snap.chain, snap.contract_address):
                        continue
                scan = await scan_coin(snap)
                analysis.coin_scan = scan
                analysis.deep_risk = evaluate_deep_risk(analysis)
                analysis = analyzer.degen.apply(analysis)
                ok, why = decision.should_alert(analysis)
                if not ok:
                    logging.info("OFFICIAL_SKIP", extra={"address": snap.contract_address, "why": why, "verdict": analysis.deep_risk.verdict.value if analysis.deep_risk else None})
                    continue
                if not await coord.acquire("official-call-gap", settings.official_call_gap_seconds):
                    logging.info("OFFICIAL_SILENCE", extra={"reason": "gap"})
                    break
                if ai.available:
                    analysis.ai_summary = await ai.analyze(analysis)
                if not await coord.acquire(key, settings.token_cooldown_seconds):
                    continue
                try:
                    async with sessions() as session:
                        repo = Repository(session)
                        if await repo.has_active_call(snap.chain, snap.contract_address):
                            continue
                        call = await repo.create_call(analysis, settings.default_milestones, source="OFFICIAL")
                except IntegrityError:
                    continue
                except Exception:
                    await coord.release(key)
                    logging.exception("CALL_CREATE_ERROR", extra={"chain": snap.chain.value, "address": snap.contract_address})
                    continue
                if await coord.acquire(f"call-notify:{call.id}", 300):
                    await coord.enqueue("telegram:outbound", json.dumps({
                        "kind": "alert",
                        "text": alert_text(analysis, call.id, decision.level(analysis.degen_score)),
                        "call_id": call.id,
                        "buttons": alert_buttons(call.id, chart_url_for(snap), snap.chain, snap.contract_address, snap.pair_address),
                    }))
                called = True
            await asyncio.sleep(settings.scan_interval_seconds)
    finally:
        await ai.close()
        await provider.close()
        await engine.dispose()
