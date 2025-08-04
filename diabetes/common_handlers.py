"""Common utility handlers and helpers.

This module contains utilities shared across different handler modules,
including database transaction helpers and callback query routing.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PollAnswerHandler,
    filters,
)
from sqlalchemy.exc import SQLAlchemyError

from diabetes.db import Entry, SessionLocal
from diabetes.ui import menu_keyboard

logger = logging.getLogger(__name__)


def commit_session(session) -> bool:
    """Commit an SQLAlchemy session.

    Parameters
    ----------
    session: Session
        Active SQLAlchemy session.

    Returns
    -------
    bool
        ``True`` if the commit succeeded. If an error occurs the session is
        rolled back, the error is logged and ``False`` is returned.
    """
    try:
        session.commit()
        return True
    except SQLAlchemyError as exc:  # pragma: no cover - logging only
        session.rollback()
        logger.error("DB commit failed: %s", exc)
        return False


from .onboarding_handlers import (  # noqa: E402
    start_command,
    onboarding_conv,
    onboarding_poll_answer,
)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks for pending entries and history actions."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm_entry":
        entry_data = context.user_data.pop("pending_entry", None)
        if not entry_data:
            await query.edit_message_text("❗ Нет данных для сохранения.")
            return
        with SessionLocal() as session:
            entry = Entry(**entry_data)
            session.add(entry)
            if not commit_session(session):
                await query.edit_message_text("⚠️ Не удалось сохранить запись.")
                return
        await query.edit_message_text("✅ Запись сохранена в дневник!")
        return
    elif data == "edit_entry":
        entry_data = context.user_data.get("pending_entry")
        if not entry_data:
            await query.edit_message_text("❗ Нет данных для редактирования.")
            return
        context.user_data["edit_id"] = None
        await query.edit_message_text(
            "Отправьте новое сообщение в формате:\n"
            "`сахар=<ммоль/л>  xe=<ХЕ>  carbs=<г>  dose=<ед>`\n"
            "Можно указывать не все поля (что прописано — то и поменяется).",
            parse_mode="Markdown",
        )
        return
    elif data == "cancel_entry":
        context.user_data.pop("pending_entry", None)
        await query.edit_message_text("❌ Запись отменена.")
        await query.message.reply_text("📋 Выберите действие:", reply_markup=menu_keyboard)
        return
    elif data.startswith("edit:") or data.startswith("del:"):
        action, entry_id = data.split(":", 1)
        try:
            entry_id = int(entry_id)
        except ValueError:
            logger.warning("Invalid entry_id in callback data: %s", entry_id)
            await query.edit_message_text("Некорректный идентификатор записи.")
            return
        with SessionLocal() as session:
            entry = session.get(Entry, entry_id)
            if not entry:
                await query.edit_message_text("Запись не найдена (уже удалена).")
                return
            if entry.telegram_id != update.effective_user.id:
                await query.edit_message_text(
                    "⚠️ Эта запись принадлежит другому пользователю."
                )
                return
            if action == "del":
                session.delete(entry)
                if not commit_session(session):
                    await query.edit_message_text("⚠️ Не удалось удалить запись.")
                    return
                await query.edit_message_text("❌ Запись удалена.")
                return
            if action == "edit":
                context.user_data["edit_id"] = entry.id
                text = (
                    "Отправьте новое сообщение в формате:\n"
                    "`сахар=<ммоль/л>  xe=<ХЕ>  carbs=<г>  dose=<ед>`\n"
                    "Можно указывать не все поля (что прописано — то и поменяется).",
                )
                await query.edit_message_text("\n".join(text), parse_mode="Markdown")
                return
    else:
        logger.warning("Unrecognized callback data: %s", data)
        await query.edit_message_text("Команда не распознана")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display the main menu keyboard using ``menu_keyboard``."""
    await update.message.reply_text(
        "📋 Выберите действие:", reply_markup=menu_keyboard
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands, including :command:`/menu`, and menu buttons."""

    text = (
        "📚 Доступные команды:\n"
        "/start - запустить бота\n"
        "/menu - главное меню (вернуться к кнопкам)\n"
        "/profile - мой профиль\n"
        "/report - отчёт\n"
        "/sugar - расчёт сахара\n"
        "/gpt - чат с GPT\n"
        "/cancel - отменить ввод\n"
        "/help - справка\n\n"
        "📲 Кнопки меню:\n"
        "📷 Фото еды\n"
        "🩸 Уровень сахара\n"
        "💉 Доза инсулина\n"
        "📊 История\n"
        "📈 Отчёт\n"
        "📄 Мой профиль\n"
        "ℹ️ Помощь"
    )
    await update.message.reply_text(text, reply_markup=menu_keyboard)


def register_handlers(app: Application) -> None:
    """Register bot handlers on the provided ``Application`` instance.

    Parameters
    ----------
    app: :class:`telegram.ext.Application`
        The application to which handlers will be attached.
    """

    # Import inside the function to avoid heavy imports at module import time
    # (for example OpenAI client initialization).
    from . import dose_handlers, profile_handlers, reporting_handlers

    app.add_handler(onboarding_conv)
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("report", reporting_handlers.report_request))
    app.add_handler(dose_handlers.dose_conv)
    app.add_handler(dose_handlers.sugar_conv)
    app.add_handler(profile_handlers.profile_conv)
    app.add_handler(CommandHandler("sugar", dose_handlers.sugar_start))
    app.add_handler(CommandHandler("cancel", dose_handlers.dose_cancel))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("gpt", dose_handlers.chat_with_gpt))
    app.add_handler(PollAnswerHandler(onboarding_poll_answer))
    app.add_handler(
        MessageHandler(filters.Regex("^📄 Мой профиль$"), profile_handlers.profile_view)
    )
    app.add_handler(
        MessageHandler(filters.Regex("^📈 Отчёт$"), reporting_handlers.report_request)
    )
    app.add_handler(
        MessageHandler(filters.Regex("^📊 История$"), reporting_handlers.history_view)
    )
    app.add_handler(
        MessageHandler(filters.Regex("^📷 Фото еды$"), dose_handlers.photo_prompt)
    )
    app.add_handler(
        MessageHandler(filters.Regex("^ℹ️ Помощь$"), help_command)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dose_handlers.freeform_handler)
    )
    app.add_handler(MessageHandler(filters.PHOTO, dose_handlers.photo_handler))
    app.add_handler(
        MessageHandler(filters.Document.IMAGE, dose_handlers.doc_handler)
    )
    app.add_handler(
        CallbackQueryHandler(
            reporting_handlers.report_period_callback, pattern="^report_back$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            reporting_handlers.report_period_callback, pattern="^report_period:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(profile_handlers.profile_back, pattern="^profile_back$")
    )
    app.add_handler(CallbackQueryHandler(callback_router))


__all__ = [
    "commit_session",
    "callback_router",
    "menu_keyboard",
    "start_command",
    "menu_command",
    "help_command",
    "register_handlers",
]
