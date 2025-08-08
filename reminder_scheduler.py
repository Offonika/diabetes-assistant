from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def schedule_reminder(bot, chat_id: int, run_time: datetime, text: str) -> None:
    if not scheduler.running:
        scheduler.start()
    scheduler.add_job(
        bot.send_message,
        "date",
        run_date=run_time,
        kwargs={"chat_id": chat_id, "text": text},
    )
