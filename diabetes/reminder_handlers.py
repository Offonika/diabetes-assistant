"""Handlers for personal reminders."""

from __future__ import annotations

from datetime import time, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from diabetes.db import SessionLocal, Reminder, ReminderLog
from .common_handlers import commit_session

MAX_REMINDERS = 5


def _describe(rem: Reminder) -> str:
    if rem.type == "sugar":
        if rem.time:
            return f"Замерить сахар {rem.time}"
        return f"Замерить сахар каждые {rem.interval_hours} ч"
    if rem.type == "long_insulin":
        return f"Длинный инсулин {rem.time}"
    if rem.type == "medicine":
        return f"Таблетки/лекарство {rem.time}"
    if rem.type == "xe_after":
        return f"Проверить ХЕ через {rem.minutes_after} мин"
    return rem.type


def schedule_reminder(rem: Reminder, job_queue) -> None:
    name = f"reminder_{rem.id}"
    if rem.type in {"sugar", "long_insulin", "medicine"}:
        if rem.time:
            hh, mm = map(int, rem.time.split(":"))
            job_queue.run_daily(
                reminder_job,
                time=time(hour=hh, minute=mm),
                data={"reminder_id": rem.id, "chat_id": rem.telegram_id},
                name=name,
            )
        elif rem.interval_hours:
            job_queue.run_repeating(
                reminder_job,
                interval=timedelta(hours=rem.interval_hours),
                data={"reminder_id": rem.id, "chat_id": rem.telegram_id},
                name=name,
            )
    # xe_after reminders are scheduled when entry is logged


def schedule_all(job_queue) -> None:
    with SessionLocal() as session:
        reminders = session.query(Reminder).all()
    for rem in reminders:
        schedule_reminder(rem, job_queue)


async def reminders_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    with SessionLocal() as session:
        rems = session.query(Reminder).filter_by(telegram_id=user_id).all()
    if not rems:
        await update.message.reply_text("У вас нет напоминаний.")
        return
    lines = [f"{r.id}. {_describe(r)}" for r in rems]
    await update.message.reply_text("\n".join(lines))


# Conversation states
ADDREM_TYPE, ADDREM_VALUE = range(2)


def _is_time(val: str) -> bool:
    parts = val.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= h < 24 and 0 <= m < 60


async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with SessionLocal() as session:
        count = (
            session.query(Reminder)
            .filter_by(telegram_id=user_id)
            .count()
        )
    if count >= MAX_REMINDERS:
        await update.message.reply_text(
            "Можно создать не более 5 напоминаний.",
        )
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("sugar", callback_data="remtype:sugar")],
            [
                InlineKeyboardButton(
                    "long_insulin", callback_data="remtype:long_insulin"
                )
            ],
            [InlineKeyboardButton("medicine", callback_data="remtype:medicine")],
            [InlineKeyboardButton("xe_after", callback_data="remtype:xe_after")],
        ]
    )
    await update.message.reply_text(
        "Выберите тип напоминания:", reply_markup=keyboard
    )
    return ADDREM_TYPE


async def add_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, rtype = query.data.split(":")
    context.user_data["rtype"] = rtype
    if rtype == "sugar":
        prompt = "Введите время в формате HH:MM или интервал в часах."
    elif rtype in {"long_insulin", "medicine"}:
        prompt = "Введите время в формате HH:MM."
    else:
        prompt = "Введите интервал в минутах."
    await query.message.reply_text(f"Тип: {rtype}. {prompt}")
    return ADDREM_VALUE


async def add_reminder_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rtype = context.user_data.get("rtype")
    if not rtype:
        await update.message.reply_text("Тип напоминания не выбран.")
        return ConversationHandler.END
    val = update.message.text.strip()
    reminder = Reminder(telegram_id=update.effective_user.id, type=rtype)
    if rtype == "sugar":
        if ":" in val:
            if not _is_time(val):
                await update.message.reply_text("Неверный формат времени.")
                return ADDREM_VALUE
            reminder.time = val
        else:
            try:
                reminder.interval_hours = int(val)
            except ValueError:
                await update.message.reply_text("Интервал должен быть числом.")
                return ADDREM_VALUE
    elif rtype in {"long_insulin", "medicine"}:
        if not _is_time(val):
            await update.message.reply_text("Введите время в формате HH:MM.")
            return ADDREM_VALUE
        reminder.time = val
    elif rtype == "xe_after":
        try:
            reminder.minutes_after = int(val)
        except ValueError:
            await update.message.reply_text("Значение должно быть числом.")
            return ADDREM_VALUE
    with SessionLocal() as session:
        session.add(reminder)
        if not commit_session(session):
            await update.message.reply_text("⚠️ Не удалось сохранить напоминание.")
            return ConversationHandler.END
        session.refresh(reminder)
    schedule_reminder(reminder, context.job_queue)
    await update.message.reply_text(
        f"✅ Напоминание сохранено: {_describe(reminder)}"
    )
    return ConversationHandler.END


async def add_reminder_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Напоминание отменено.")
    return ConversationHandler.END


add_reminder_conv = ConversationHandler(
    entry_points=[CommandHandler("addreminder", add_reminder)],
    states={
        ADDREM_TYPE: [CallbackQueryHandler(add_reminder_type, pattern="^remtype:")],
        ADDREM_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_value)
        ],
    },
    fallbacks=[CommandHandler("cancel", add_reminder_cancel)],
    per_message=False,
)


async def delete_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    args = getattr(context, "args", [])
    if not args:
        if message:
            await message.reply_text("Укажите ID: /delreminder <id>")
        return
    try:
        rid = int(args[0])
    except ValueError:
        if message:
            await message.reply_text("ID должен быть числом: /delreminder <id>")
        return
    with SessionLocal() as session:
        rem = session.get(Reminder, rid)
        if not rem:
            if message:
                await message.reply_text("Не найдено")
            return
        session.delete(rem)
        commit_session(session)
    for job in context.job_queue.get_jobs_by_name(f"reminder_{rid}"):
        job.schedule_removal()
    if message:
        await message.reply_text("Удалено")


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    rid = data["reminder_id"]
    chat_id = data["chat_id"]
    with SessionLocal() as session:
        rem = session.get(Reminder, rid)
        if not rem:
            return
        session.add(
            ReminderLog(reminder_id=rid, telegram_id=chat_id, action="trigger")
        )
        commit_session(session)
        text = _describe(rem)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Отложить 10 мин", callback_data=f"remind_snooze:{rid}"
                ),
                InlineKeyboardButton("Отмена", callback_data=f"remind_cancel:{rid}"),
            ]
        ]
    )
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, rid_str = query.data.split(":")
    rid = int(rid_str)
    chat_id = update.effective_user.id
    with SessionLocal() as session:
        session.add(
            ReminderLog(reminder_id=rid, telegram_id=chat_id, action=action)
        )
        commit_session(session)
    if action == "remind_snooze":
        context.job_queue.run_once(
            reminder_job,
            when=timedelta(minutes=10),
            data={"reminder_id": rid, "chat_id": chat_id},
            name=f"reminder_{rid}",
        )
        await query.edit_message_text("⏰ Отложено на 10 минут")
    else:
        await query.edit_message_text("❌ Напоминание отменено")


def schedule_after_meal(user_id: int, job_queue) -> None:
    with SessionLocal() as session:
        rems = (
            session.query(Reminder)
            .filter_by(telegram_id=user_id, type="xe_after")
            .all()
        )
    for rem in rems:
        job_queue.run_once(
            reminder_job,
            when=timedelta(minutes=rem.minutes_after),
            data={"reminder_id": rem.id, "chat_id": user_id},
            name=f"reminder_{rem.id}",
        )
