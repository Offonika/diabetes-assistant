import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from telegram.ext import ConversationHandler

from diabetes.db import Base, User


class DummyMessage:
    def __init__(self):
        self.texts = []
        self.photos = []
        self.polls = []
        self.markups = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def reply_photo(self, photo, caption=None, **kwargs):
        self.photos.append((photo, caption))
        self.markups.append(kwargs.get("reply_markup"))

    async def reply_poll(self, question, options, **kwargs):
        self.polls.append((question, options))
        self.markups.append(kwargs.get("reply_markup"))
        return SimpleNamespace(poll=SimpleNamespace(id="p1"))

    async def delete(self):
        pass


class DummyQuery:
    def __init__(self, message, data):
        self.message = message
        self.data = data

    async def answer(self):
        pass


@pytest.mark.asyncio
async def test_onboarding_flow(monkeypatch):
    os.environ.setdefault("OPENAI_API_KEY", "test")
    os.environ.setdefault("OPENAI_ASSISTANT_ID", "asst_test")

    import diabetes.onboarding_handlers as onboarding
    import diabetes.gpt_client as gpt_client

    monkeypatch.setattr(gpt_client, "create_thread", lambda: "tid")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(onboarding, "SessionLocal", TestSession)
    monkeypatch.setattr(onboarding, "menu_keyboard", "MK")

    message = DummyMessage()
    update = SimpleNamespace(
        message=message, effective_user=SimpleNamespace(id=1, first_name="Ann")
    )
    context = SimpleNamespace(user_data={}, bot_data={})

    state = await onboarding.start_command(update, context)
    assert state == onboarding.ONB_PROFILE_ICR
    assert "1/3" in message.texts[-1]

    update.message.text = "10"
    state = await onboarding.onboarding_icr(update, context)
    assert state == onboarding.ONB_PROFILE_CF

    update.message.text = "3"
    state = await onboarding.onboarding_cf(update, context)
    assert state == onboarding.ONB_PROFILE_TARGET

    update.message.text = "6"
    state = await onboarding.onboarding_target(update, context)
    assert state == onboarding.ONB_DEMO
    assert message.photos

    query = DummyQuery(message, "onb_next")
    update_cb = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
    state = await onboarding.onboarding_demo_next(update_cb, context)
    assert state == onboarding.ONB_REMINDERS
    assert "3/3" in message.texts[-1]

    query2 = DummyQuery(message, "onb_rem_no")
    update_cb2 = SimpleNamespace(callback_query=query2, effective_user=SimpleNamespace(id=1))
    state = await onboarding.onboarding_reminders(update_cb2, context)
    assert state == ConversationHandler.END
    assert message.polls

    with TestSession() as session:
        user = session.get(User, 1)
        assert user.onboarding_complete is True

    message2 = DummyMessage()
    update2 = SimpleNamespace(
        message=message2, effective_user=SimpleNamespace(id=1, first_name="Ann")
    )
    context2 = SimpleNamespace(user_data={}, bot_data={})
    state2 = await onboarding.start_command(update2, context2)
    assert state2 == ConversationHandler.END
    assert any("Выберите" in t for t in message2.texts)
