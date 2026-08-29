import json
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import Redis
from app.config import Settings
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.services.cache import Coordination

async def run_telegram_worker(settings:Settings):
    settings.validate_runtime("telegram"); engine=create_engine(settings); sessions=create_session_factory(engine); redis=Redis.from_url(settings.redis_url,decode_responses=True); coordination=Coordination(redis); bot=Bot(settings.telegram_bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML)); processing="telegram:processing"
    try:
        await coordination.recover_processing(processing,"telegram:outbound")
        while True:
            raw=await coordination.dequeue_reliably("telegram:outbound",processing,timeout=10)
            if not raw: continue
            try:
                payload=json.loads(raw); message=await bot.send_message(settings.owner_telegram_id,payload["text"],disable_web_page_preview=True)
                async with sessions() as session:
                    repo=Repository(session)
                    if payload.get("milestone_id"): await repo.mark_milestone_sent(payload["milestone_id"],message.message_id)
                    elif payload.get("call_id"): await repo.mark_call_alert_sent(payload["call_id"],message.message_id)
                await coordination.acknowledge(processing,raw)
            except Exception:
                await redis.lrem(processing,1,raw); await redis.lpush("telegram:outbound",raw)
                await __import__("asyncio").sleep(5)
    finally: await bot.session.close(); await redis.aclose(); await engine.dispose()
