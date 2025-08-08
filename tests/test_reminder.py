import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db_access
from db import Base
from reminder_scheduler import schedule_reminder


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_access, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


@pytest.mark.asyncio
async def test_reminder_creation_and_trigger(session):
    run_time = datetime.now() + timedelta(seconds=1)
    db_access.add_reminder(1, run_time, "check sugar")
    reminders = db_access.get_reminders(1)
    assert len(reminders) == 1

    bot = DummyBot()
    schedule_reminder(bot, 1, run_time, "check sugar")
    await asyncio.sleep(1.5)
    assert bot.sent == [(1, "check sugar")]

    db_access.delete_reminder(reminders[0].id)
    assert db_access.get_reminders(1) == []

