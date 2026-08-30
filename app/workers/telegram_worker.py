import asyncio
import json
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from redis.asyncio import Redis

from app.bot.keyboards import from_payload
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.services.cache import Coordination

OUTBOUND_QUEUE = "telegram:outbound"
PROCESSING_QUEUE = "telegram:processing"
DEAD_LETTER_QUEUE = "telegram:dead"
MAX_ATTEMPTS = 5


async def _replace(redis: Redis, queue: str, raw: str, new_raw: str) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lrem(queue, 1, raw)
        pipe.lpush(queue, new_raw)
        await pipe.execute()


async def _retry(redis: Redis, raw: str, payload: dict, delay: float = 5) -> None:
    attempts = int(payload.get("attempts", 0)) + 1
    payload["attempts"] = attempts
    target = DEAD_LETTER_QUEUE if attempts >= MAX_ATTEMPTS else OUTBOUND_QUEUE
    new_raw = json.dumps(payload)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lrem(PROCESSING_QUEUE, 1, raw)
        pipe.lpush(target, new_raw)
        await pipe.execute()
    if target == DEAD_LETTER_QUEUE:
        logging.error("TELEGRAM_MESSAGE_DEAD_LETTERED", extra={"kind": payload.get("kind")})
    else:
        await asyncio.sleep(max(0, min(delay, 60)))


def _payload(raw: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"]:
        raise ValueError("Outbound Telegram payload requires non-empty text")
    if len(value["text"]) > 4096:
        raise ValueError("Outbound Telegram message exceeds 4096 characters")
    attempts = value.get("attempts", 0)
    if type(attempts) is not int or attempts < 0:
        raise ValueError("Outbound Telegram attempts must be a non-negative integer")
    identifiers = [name for name in ("call_id", "milestone_id") if value.get(name) is not None]
    if len(identifiers) > 1:
        raise ValueError("Outbound Telegram payload cannot contain multiple database identifiers")
    for name in identifiers:
        if type(value[name]) is not int or value[name] <= 0:
            raise ValueError(f"Outbound Telegram {name} must be a positive integer")
    message_id = value.get("sent_message_id")
    if message_id is not None and (type(message_id) is not int or message_id <= 0):
        raise ValueError("Outbound Telegram sent_message_id must be a positive integer")
    return value


async def run_telegram_worker(settings: Settings):
    settings.validate_runtime("telegram")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    coordination = Coordination(redis)
    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await coordination.recover_processing(PROCESSING_QUEUE, OUTBOUND_QUEUE)
        while True:
            await coordination.heartbeat("telegram", 30)
            raw = await coordination.dequeue_reliably(OUTBOUND_QUEUE, PROCESSING_QUEUE, timeout=10)
            if not raw:
                continue
            try:
                payload = _payload(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                logging.exception("INVALID_TELEGRAM_PAYLOAD")
                await coordination.acknowledge(PROCESSING_QUEUE, raw)
                continue

            try:
                message_id = payload.get("sent_message_id")
                if type(message_id) is not int:
                    message = await bot.send_message(
                        settings.owner_telegram_id,
                        payload["text"],
                        disable_web_page_preview=True,
                        reply_markup=from_payload(payload.get("buttons")),
                    )
                    message_id = message.message_id
                    payload["sent_message_id"] = message_id
                    persisted_raw = json.dumps(payload)
                    await _replace(redis, PROCESSING_QUEUE, raw, persisted_raw)
                    raw = persisted_raw

                async with sessions() as session:
                    repo = Repository(session)
                    if payload.get("milestone_id"):
                        await repo.mark_milestone_sent(int(payload["milestone_id"]), message_id)
                    elif payload.get("call_id"):
                        await repo.mark_call_alert_sent(int(payload["call_id"]), message_id)
                await coordination.acknowledge(PROCESSING_QUEUE, raw)
            except TelegramRetryAfter as exc:
                await _retry(redis, raw, payload, float(exc.retry_after))
            except TelegramNetworkError:
                logging.exception("TELEGRAM_NETWORK_ERROR")
                await _retry(redis, raw, payload)
            except TelegramAPIError:
                logging.exception("TELEGRAM_API_ERROR")
                payload["attempts"] = MAX_ATTEMPTS - 1
                await _retry(redis, raw, payload, 0)
            except Exception:
                logging.exception("TELEGRAM_DELIVERY_ERROR")
                await _retry(redis, raw, payload)
    finally:
        await bot.session.close()
        await redis.aclose()
        await engine.dispose()
