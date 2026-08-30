import asyncio
import json
import logging
from datetime import timedelta

from redis.asyncio import Redis

from app.bot.formatting import chart_url_for, milestone_text
from app.bot.keyboards import alert_buttons
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider
from app.services.cache import Coordination
from app.tracking.calculations import (
    InvalidPrice,
    calculate_drawdown,
    calculate_multiple,
    is_anomalous,
    validate_price,
)


def _elapsed_text(elapsed: timedelta) -> str:
    seconds = max(0, int(elapsed.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _milestone_payload(call, milestone, multiple, extra: str = "") -> str:
    chart = chart_url_for(None, call.token.chain, call.token.contract_address)
    return json.dumps({
        "kind": "milestone",
        "text": milestone_text(call, milestone, multiple, extra),
        "milestone_id": milestone.id,
        "buttons": alert_buttons(call.id, chart),
    })


async def run_tracker(settings: Settings):
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    coord = Coordination(redis)
    provider = DexScreenerProvider(settings)
    cycles = 0
    try:
        while True:
            await coord.heartbeat("tracker", settings.tracking_interval_seconds * 3)
            async with sessions() as session:
                calls = await Repository(session).active_calls()
            async with sessions() as session:
                unsent = await Repository(session).unsent_milestones()

            for milestone in unsent:
                notify_key = f"milestone-notify:{milestone.id}"
                if not await coord.acquire(notify_key, 300):
                    continue
                call = milestone.call
                if milestone.hit_price is None or not milestone.hit_price.is_finite() or call.reference_price <= 0:
                    logging.error("INVALID_STORED_MILESTONE", extra={"milestone_id": milestone.id})
                    await coord.release(notify_key)
                    continue
                multiple = calculate_multiple(call.reference_price, milestone.hit_price)
                await coord.enqueue("telegram:outbound", _milestone_payload(call, milestone, multiple))

            for call in calls:
                lock_key = f"tracking:{call.id}"
                if not await coord.acquire(lock_key, max(settings.tracking_interval_seconds * 2, 30)):
                    continue
                try:
                    snap = await provider.get_snapshot(Chain(call.token.chain), call.token.contract_address)
                    if not snap or snap.price is None:
                        continue
                    validate_price(snap.price, snap.timestamp, settings.max_data_age_seconds)
                    if is_anomalous(call.current_price, snap.price, settings.max_price_jump_multiple):
                        logging.warning("PRICE_JUMP_REJECTED", extra={"call_id": call.id})
                        continue
                    multiple = calculate_multiple(call.reference_price, snap.price)
                    async with sessions() as session:
                        hit = await Repository(session).update_tracking(call, snap, multiple)
                    for milestone in hit:
                        elapsed = snap.timestamp - call.reference_timestamp
                        ath = max(call.highest_multiple, multiple)
                        drawdown = abs(calculate_drawdown(ath, multiple))
                        extra = (
                            f"Time since alert: {_elapsed_text(elapsed)}\n"
                            f"Observed ATH: {ath:.2f}X\n"
                            f"Drawdown from ATH: {drawdown:.2f}%"
                        )
                        if await coord.acquire(f"milestone-notify:{milestone.id}", 300):
                            await coord.enqueue("telegram:outbound", _milestone_payload(call, milestone, multiple, extra))
                except InvalidPrice:
                    logging.warning("DATA_ANOMALY", extra={"call_id": call.id})
                except Exception:
                    logging.exception("PRICE_UPDATE_ERROR", extra={"call_id": call.id})
                finally:
                    await coord.release(lock_key)

            cycles += 1
            if cycles % 120 == 0:
                async with sessions() as session:
                    await Repository(session).cleanup_snapshots(settings.snapshot_retention_days)
            await asyncio.sleep(settings.tracking_interval_seconds)
    finally:
        await provider.close()
        await redis.aclose()
        await engine.dispose()
