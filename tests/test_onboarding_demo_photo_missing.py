import os
from types import SimpleNamespace

import logging
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from diabetes.db import Base


class DummyMessage:
    def __init__(self):
        self.texts = []
        self.photos = []
        self.markups = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def reply_photo(self, photo, caption=None, **kwargs):
        self.photos.append((photo, caption))
        self.markups.append(kwargs.get("reply_markup"))


@pytest.mark.asyncio
async def test_onboarding_demo_photo_missing(monkeypatch, caplog):
    os.environ.setdefault("OPENAI_API_KEY", "test")
    os.environ.setdefault("OPENAI_ASSISTANT_ID", "asst_test")

    import diabetes.common_handlers  # noqa: F401
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

    await onboarding.start_command(update, context)
    update.message.text = "10"
    await onboarding.onboarding_icr(update, context)
    update.message.text = "3"
    await onboarding.onboarding_cf(update, context)
    update.message.text = "6"
    await onboarding.onboarding_target(update, context)

    import builtins

    orig_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if path == "assets/demo.jpg":
            raise OSError("missing")
        return orig_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    update.message.text = "Europe/Moscow"
    with caplog.at_level(logging.ERROR):
        state = await onboarding.onboarding_timezone(update, context)

    assert state == onboarding.ONB_DEMO
    assert not message.photos
    assert "Демо-фото недоступно" in message.texts[-1]
    assert any("Failed to open demo photo" in r.message for r in caplog.records)
