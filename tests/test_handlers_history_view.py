import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from diabetes.db import Base, Entry
import diabetes.reporting_handlers as handlers


class DummyMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_text", ["/history", "📊 История"])
async def test_history_view_lists_entries(monkeypatch, trigger_text):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(handlers, "SessionLocal", TestSession)

    now = datetime.datetime(2024, 1, 2, 12, tzinfo=datetime.timezone.utc)
    with TestSession() as session:
        session.add(
            Entry(
                telegram_id=1,
                event_time=now,
                sugar_before=5.6,
                carbs_g=30,
                xe=2.5,
                dose=1,
            )
        )
        session.add(
            Entry(
                telegram_id=1,
                event_time=now - datetime.timedelta(days=1),
                sugar_before=6.1,
                carbs_g=40,
                xe=3.3,
                dose=2,
            )
        )
        session.commit()

    message = DummyMessage(trigger_text)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(user_data={})

    await handlers.history_view(update, context)

    assert message.replies
    assert "Последние записи" in message.replies[0]
    assert "сахар" in message.replies[0]
