import asyncio
import json
import logging
from datetime import timedelta

from app.bot.formatting import chart_url_for, elapsed_text, milestone_text
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
    return elapsed_text(elapsed)


def _milestone_payload(call, milestone, multiple, extra: str = "") -> str:
    chart = chart_url_for(None, call.token.chain, call.token.contract_address)
    return json.dumps({
        "kind": "milestone",
        "text": milestone_text(call, milestone, multiple, extra),
        "milestone_id": milestone.id,
        "buttons": alert_buttons(call.id, chart, call.token.chain, call.token.contract_address),
    })


async def run_tracker(settings: Settings):
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    coord = Coordination(sessions)
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

            grouped: dict[str, list] = {}
            locked = []
            ttl = max(settings.tracking_interval_seconds * 2, 20)
            for call in calls:
                lock_key = f"tracking:{call.id}"
                if not await coord.acquire(lock_key, ttl):
                    continue
                locked.append(call)
                grouped.setdefault(call.token.chain, []).append(call)
            try:
                snap_map: dict[tuple[str, str], object] = {}
                loads = []
                for chain_name, group in grouped.items():
                    chain = Chain(chain_name)
                    addresses = [item.token.contract_address for item in group]
                    loads.append((chain_name, chain, addresses))
                fetched = await asyncio.gather(
                    *(provider.get_snapshots(chain, addresses) for _, chain, addresses in loads),
                    return_exceptions=True,
                )
                for (chain_name, chain, _), snaps in zip(loads, fetched):
                    if isinstance(snaps, Exception):
                        logging.exception("PRICE_BATCH_ERROR", extra={"chain": chain_name})
                        continue
                    for snap in snaps:
                        key = snap.contract_address.lower() if chain.is_evm else snap.contract_address
                        snap_map[(chain_name, key)] = snap
                for call in locked:
                    chain = Chain(call.token.chain)
                    key = call.token.contract_address.lower() if chain.is_evm else call.token.contract_address
                    snap = snap_map.get((call.token.chain, key))
                    if not snap or snap.price is None:
                        continue
                    try:
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
                                f"⏱ Time since alert: {_elapsed_text(elapsed)}\n"
                                f"🏆 Observed ATH: {ath:.2f}X\n"
                                f"📉 Drawdown from ATH: {drawdown:.2f}%"
                            )
                            if await coord.acquire(f"milestone-notify:{milestone.id}", 300):
                                await coord.enqueue("telegram:outbound", _milestone_payload(call, milestone, multiple, extra))
                    except InvalidPrice:
                        logging.warning("DATA_ANOMALY", extra={"call_id": call.id})
                    except Exception:
                        logging.exception("PRICE_UPDATE_ERROR", extra={"call_id": call.id})
            finally:
                for call in locked:
                    await coord.release(f"tracking:{call.id}")

            cycles += 1
            if cycles % 120 == 0:
                async with sessions() as session:
                    await Repository(session).cleanup_snapshots(settings.snapshot_retention_days)
            await asyncio.sleep(settings.tracking_interval_seconds)
    finally:
        await provider.close()
        await engine.dispose()
