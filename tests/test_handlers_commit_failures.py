import datetime
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
import diabetes.profile_handlers as profile_handlers
import diabetes.common_handlers as common_handlers
import diabetes.reminder_handlers as reminder_handlers


class DummyMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class DummyQuery:
    def __init__(self, data):
        self.data = data
        self.edited = []

    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edited.append(text)


@pytest.mark.asyncio
async def test_profile_command_commit_failure(monkeypatch, caplog):
    import os

    os.environ["OPENAI_API_KEY"] = "test"
    os.environ["OPENAI_ASSISTANT_ID"] = "asst_test"
    import diabetes.openai_utils  # noqa: F401

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.get.return_value = None
    session.add = MagicMock()
    session.commit.side_effect = SQLAlchemyError("fail")
    session.rollback = MagicMock()

    monkeypatch.setattr(profile_handlers, "SessionLocal", lambda: session)

    message = DummyMessage()
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(args=["10", "2", "6", "4", "9"], user_data={})

    with caplog.at_level(logging.ERROR):
        await profile_handlers.profile_command(update, context)

    assert session.rollback.called
    assert "DB commit failed" in caplog.text
    assert message.texts == ["⚠️ Не удалось сохранить профиль."]


@pytest.mark.asyncio
async def test_callback_router_commit_failure(monkeypatch, caplog):
    import os

    os.environ["OPENAI_API_KEY"] = "test"
    os.environ["OPENAI_ASSISTANT_ID"] = "asst_test"
    import diabetes.openai_utils  # noqa: F401

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.add = MagicMock()
    session.commit.side_effect = SQLAlchemyError("fail")
    session.rollback = MagicMock()

    monkeypatch.setattr(common_handlers, "SessionLocal", lambda: session)

    pending_entry = {
        "telegram_id": 1,
        "event_time": datetime.datetime.now(datetime.timezone.utc),
    }
    query = DummyQuery("confirm_entry")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={"pending_entry": pending_entry})

    with caplog.at_level(logging.ERROR):
        await common_handlers.callback_router(update, context)

    assert session.rollback.called
    assert "DB commit failed" in caplog.text
    assert query.edited == ["⚠️ Не удалось сохранить запись."]


@pytest.mark.asyncio
async def test_add_reminder_commit_failure(monkeypatch, caplog):
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.add = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.count.return_value = 0
    query_mock.filter_by.return_value = filter_mock
    session.query.return_value = query_mock
    session.commit.side_effect = SQLAlchemyError("fail")
    session.rollback = MagicMock()

    monkeypatch.setattr(reminder_handlers, "SessionLocal", lambda: session)
    schedule_mock = MagicMock()
    monkeypatch.setattr(reminder_handlers, "schedule_reminder", schedule_mock)

    message = DummyMessage("23:00")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(
        user_data={"rtype": "sugar"},
        job_queue=SimpleNamespace(get_jobs_by_name=lambda name: []),
    )

    with caplog.at_level(logging.ERROR):
        result = await reminder_handlers.add_reminder_value(update, context)

    assert result == reminder_handlers.ConversationHandler.END
    assert session.rollback.called
    assert "DB commit failed" in caplog.text
    assert message.texts == ["⚠️ Не удалось сохранить напоминание."]
    assert not schedule_mock.called
