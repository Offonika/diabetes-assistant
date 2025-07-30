import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

# Set dummy env vars before importing handlers
os.environ.setdefault('TELEGRAM_TOKEN', 'x')
os.environ.setdefault('OPENAI_API_KEY', 'x')
os.environ.setdefault('OPENAI_ASSISTANT_ID', 'x')

from telegram.ext import ConversationHandler
from bot.handlers import cancel_handler, menu_keyboard

@pytest.mark.asyncio
async def test_cancel_handler_returns_menu():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace()

    result = await cancel_handler(update, context)

    message.reply_text.assert_awaited_with(
        "❌ Действие отменено.", reply_markup=menu_keyboard
    )
    assert result == ConversationHandler.END
