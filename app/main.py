import asyncio, os
from app.bot.app import run_bot
from app.config import get_settings
from app.workers.scanner_worker import run_scanner
from app.workers.telegram_worker import run_telegram_worker
from app.workers.tracker_worker import run_tracker

async def main():
    settings=get_settings(); role=os.getenv("SERVICE_ROLE",settings.service_role).lower()
    runners={"bot":run_bot,"scanner":run_scanner,"tracker":run_tracker,"telegram":run_telegram_worker}
    if role not in runners: raise ValueError(f"Unknown SERVICE_ROLE: {role}")
    await runners[role](settings)

if __name__=="__main__": asyncio.run(main())
