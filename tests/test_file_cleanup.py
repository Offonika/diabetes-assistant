import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import diabetes.common_handlers as common_handlers


class DummyQuery:
    def __init__(self, data):
        self.data = data
        self.edited = []

    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edited.append(text)


@pytest.mark.asyncio
async def test_callback_router_removes_photo(tmp_path, monkeypatch):
    photo = tmp_path / "img.jpg"
    photo.write_bytes(b"img")

    pending_entry = {
        "telegram_id": 1,
        "event_time": datetime.datetime.now(datetime.timezone.utc),
        "photo_path": str(photo),
    }

    query = DummyQuery("confirm_entry")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={"pending_entry": pending_entry})

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.add = MagicMock()
    session.commit = MagicMock()

    monkeypatch.setattr(common_handlers, "SessionLocal", lambda: session)

    await common_handlers.callback_router(update, context)

    assert not photo.exists()
    assert query.edited == ["✅ Запись сохранена в дневник!"]
