import asyncio
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db
import db_access


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    TestingSession = sessionmaker(bind=engine)
    db.Base.metadata.create_all(engine)

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", TestingSession)
    monkeypatch.setattr(db_access, "SessionLocal", TestingSession)
    # create user for FK
    with TestingSession() as s:
        from db import User
        s.add(User(telegram_id=1, thread_id="t"))
        s.commit()
    yield


class DummyBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_reminder_triggers():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from bot.handlers import reminder_job

    bot = DummyBot()
    remind_time = datetime.now() + timedelta(seconds=0.3)
    reminder_id = db_access.add_reminder(1, remind_time, "test")
    sched = AsyncIOScheduler()
    sched.start()
    sched.add_job(
        reminder_job,
        "date",
        run_date=remind_time,
        args=(bot, 1, "test", reminder_id),
    )
    await asyncio.sleep(0.5)
    assert bot.messages == [(1, "test")]
    assert db_access.get_user_reminders(1) == []
    sched.remove_all_jobs()


def test_add_and_delete_reminder():
    now = datetime.now() + timedelta(minutes=5)
    rid = db_access.add_reminder(1, now, "hi")
    reminders = db_access.get_user_reminders(1)
    assert len(reminders) == 1 and reminders[0].id == rid
    db_access.delete_reminder(rid)
    assert db_access.get_user_reminders(1) == []
