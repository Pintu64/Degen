import asyncio, json
import logging
from redis.asyncio import Redis
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider
from app.services.cache import Coordination
from app.tracking.calculations import calculate_drawdown, calculate_multiple, is_anomalous, validate_price, InvalidPrice

async def run_tracker(settings:Settings):
    engine=create_engine(settings); sessions=create_session_factory(engine); redis=Redis.from_url(settings.redis_url,decode_responses=True); coord=Coordination(redis); provider=DexScreenerProvider(settings); cycles=0
    try:
        while True:
            await coord.heartbeat("tracker",settings.tracking_interval_seconds*3)
            async with sessions() as session: calls=await Repository(session).active_calls()
            async with sessions() as session: unsent=await Repository(session).unsent_milestones()
            for milestone in unsent:
                if await coord.acquire(f"milestone-notify:{milestone.id}",300):
                    call=milestone.call; multiple=milestone.hit_price/call.reference_price
                    text=f"<b>MILESTONE HIT</b>\n\n${call.token.symbol or 'UNKNOWN'} - {milestone.target_multiple}X\n\nReference: ${call.reference_price}\nHit price: ${milestone.hit_price}\nMultiple: {multiple:.2f}X\n\nPrice reached {milestone.target_multiple}X relative to the recorded reference price."
                    await coord.enqueue("telegram:outbound",json.dumps({"kind":"milestone","text":text,"milestone_id":milestone.id}))
            for call in calls:
                lock_key=f"tracking:{call.id}"
                if not await coord.acquire(lock_key,max(settings.tracking_interval_seconds*2,30)): continue
                try:
                    snap=await provider.get_snapshot(Chain(call.token.chain),call.token.contract_address)
                    if not snap or snap.price is None: continue
                    validate_price(snap.price,snap.timestamp,settings.max_data_age_seconds)
                    if is_anomalous(call.current_price,snap.price,settings.max_price_jump_multiple): continue
                    multiple=calculate_multiple(call.reference_price,snap.price)
                    async with sessions() as session: hit=await Repository(session).update_tracking(call,snap,multiple)
                    for milestone in hit:
                        elapsed=snap.timestamp-call.reference_timestamp; drawdown=calculate_drawdown(max(call.highest_multiple,multiple),multiple)
                        text=f"<b>MILESTONE HIT</b>\n\n${call.token.symbol or 'UNKNOWN'} - {milestone.target_multiple}X\n\nReference: ${call.reference_price}\nCurrent: ${snap.price}\nMultiple: {multiple:.2f}X\nTime Since Alert: {elapsed}\nObserved ATH: {max(call.highest_multiple,multiple):.2f}X\nDrawdown from ATH: {drawdown:.2f}%\n\nPrice reached {milestone.target_multiple}X relative to the recorded reference price."
                        if await coord.acquire(f"milestone-notify:{milestone.id}",300):
                            await coord.enqueue("telegram:outbound",json.dumps({"kind":"milestone","text":text,"milestone_id":milestone.id}))
                except InvalidPrice:
                    logging.warning("DATA_ANOMALY",extra={"call_id":call.id}); continue
                except Exception:
                    logging.exception("PRICE_UPDATE_ERROR",extra={"call_id":call.id}); continue
                finally:
                    await coord.release(lock_key)
            cycles+=1
            if cycles%120==0:
                async with sessions() as session: await Repository(session).cleanup_snapshots(settings.snapshot_retention_days)
            await asyncio.sleep(settings.tracking_interval_seconds)
    finally: await provider.close(); await redis.aclose(); await engine.dispose()
