from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config


scheduler = AsyncIOScheduler()


def schedule_reminder(bot, chat_id: int, run_time: datetime, text: str) -> None:
    """Schedule a reminder message.

    Parameters
    ----------
    bot:
        Bot instance with ``send_message`` coroutine.
    chat_id:
        Chat identifier to deliver the reminder to.
    run_time:
        Target time when the reminder should be triggered.  If the provided
        ``datetime`` is *naive* (i.e. ``tzinfo`` is ``None``), it is assumed to
        be in the timezone specified by :data:`config.TIMEZONE` if present or
        UTC otherwise.
    text:
        Message text to send.
    """

    if run_time.tzinfo is None:
        tz = getattr(config, "TIMEZONE", timezone.utc)
        run_time = run_time.replace(tzinfo=tz)

    if not scheduler.running:
        scheduler.start()
    scheduler.add_job(
        bot.send_message,
        "date",
        run_date=run_time,
        kwargs={"chat_id": chat_id, "text": text},
    )
