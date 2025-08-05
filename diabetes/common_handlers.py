"""Common utility handlers and helpers.

This module contains utilities shared across different handler modules,
including database transaction helpers and callback query routing.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
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
        sugar = entry_data.get("sugar_before")
        if sugar is not None:
            from .alert_handlers import check_alert
            await check_alert(update, context, sugar)
        await query.edit_message_text("✅ Запись сохранена в дневник!")
        from . import reminder_handlers

        job_queue = getattr(context, "job_queue", None)
        if job_queue:
            reminder_handlers.schedule_after_meal(update.effective_user.id, job_queue)
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
                context.user_data["edit_entry"] = {
                    "id": entry.id,
                    "chat_id": query.message.chat_id,
                    "message_id": query.message.message_id,
                }
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "сахар", callback_data=f"edit_field:{entry.id}:sugar"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "xe", callback_data=f"edit_field:{entry.id}:xe"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "dose", callback_data=f"edit_field:{entry.id}:dose"
                            )
                        ],
                    ]
                )
                await query.edit_message_reply_markup(reply_markup=keyboard)
                return
    elif data.startswith("edit_field:"):
        try:
            _, entry_id_str, field = data.split(":")
            entry_id = int(entry_id_str)
        except ValueError:
            logger.warning("Invalid edit_field data: %s", data)
            await query.edit_message_text("Некорректные данные для редактирования.")
            return
        context.user_data["edit_id"] = entry_id
        context.user_data["edit_field"] = field
        context.user_data["edit_query"] = query
        prompt = {
            "sugar": "Введите уровень сахара (ммоль/л).",
            "xe": "Введите количество ХЕ.",
            "dose": "Введите дозу инсулина (ед.).",
        }.get(field, "Введите значение")
        await query.message.reply_text(prompt, reply_markup=ForceReply(selective=True))
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
        "/reminders - список напоминаний\n"
        "/addreminder - добавить напоминание\n"
        "/delreminder - удалить напоминание\n"
        "/cancel - отменить ввод\n"
        "/help - справка\n"
        "/hypoalert - FAQ по гипогликемии\n\n"
        "🆕 Новые возможности:\n"
        "• ✨ Мастер настройки при первом запуске\n"
        "• 🕹 Быстрый ввод (smart-input)\n"
        "• ✏️ Редактирование записей\n\n"
        "🔔 Безопасность:\n"
        "• Пороги низкого и высокого сахара\n"
        "• SOS-уведомления\n"
        "• ⏰ Напоминания\n"
        "• FAQ по гипогликемии: /hypoalert\n"
        "Настройки: /profile → «🔔 Безопасность»\n\n"
        "📲 Кнопки меню:\n"
        "🕹 Быстрый ввод\n"
        "📷 Фото еды\n"
        "🩸 Уровень сахара\n"
        "💉 Доза инсулина\n"
        "📊 История\n"
        "📈 Отчёт\n"
        "📄 Мой профиль\n"
        "⏰ Напоминания\n"
        "ℹ️ Помощь"
    )
    await update.message.reply_text(text, reply_markup=menu_keyboard)


async def smart_input_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain the smart-input syntax for quick diary entries."""

    text = (
        "🕹 Быстрый ввод позволяет записать сахар, ХЕ и дозу в одном сообщении.\n"
        "Используйте формат: `сахар=<ммоль/л> xe=<ХЕ> dose=<ед>` или свободный текст,\n"
        "например: `5 ммоль/л 3хе 2ед`. Можно указывать только нужные значения."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


def register_handlers(app: Application) -> None:
    """Register bot handlers on the provided ``Application`` instance.

    Parameters
    ----------
    app: :class:`telegram.ext.Application`
        The application to which handlers will be attached.
    """

    # Import inside the function to avoid heavy imports at module import time
    # (for example OpenAI client initialization).
    from . import (
        dose_handlers,
        profile_handlers,
        reporting_handlers,
        reminder_handlers,
        alert_handlers,
        sos_handlers,
        security_handlers,
    )

    app.add_handler(onboarding_conv)
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("report", reporting_handlers.report_request))
    app.add_handler(dose_handlers.dose_conv)
    app.add_handler(dose_handlers.sugar_conv)
    app.add_handler(profile_handlers.profile_conv)
    app.add_handler(sos_handlers.sos_contact_conv)
    app.add_handler(CommandHandler("cancel", dose_handlers.dose_cancel))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("gpt", dose_handlers.chat_with_gpt))
    app.add_handler(CommandHandler("reminders", reminder_handlers.reminders_list))
    app.add_handler(reminder_handlers.add_reminder_conv)
    app.add_handler(CommandHandler("delreminder", reminder_handlers.delete_reminder))
    app.add_handler(CommandHandler("alertstats", alert_handlers.alert_stats))
    app.add_handler(CommandHandler("hypoalert", security_handlers.hypo_alert_faq))
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
        MessageHandler(filters.Regex("^🕹 Быстрый ввод$"), smart_input_help)
    )
    app.add_handler(
        MessageHandler(
            filters.Regex("^⏰ Напоминания$"), reminder_handlers.reminders_list
        )
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
        CallbackQueryHandler(
            profile_handlers.profile_security, pattern="^profile_security"
        )
    )
    app.add_handler(
        CallbackQueryHandler(profile_handlers.profile_back, pattern="^profile_back$")
    )
    app.add_handler(CallbackQueryHandler(reminder_handlers.reminder_callback, pattern="^remind_"))
    app.add_handler(CallbackQueryHandler(callback_router))

    job_queue = app.job_queue
    if job_queue:
        reminder_handlers.schedule_all(job_queue)


__all__ = [
    "commit_session",
    "callback_router",
    "menu_keyboard",
    "start_command",
    "menu_command",
    "help_command",
    "smart_input_help",
    "register_handlers",
]
