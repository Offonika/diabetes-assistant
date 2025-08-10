"""Handlers related to patient profile management."""

from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from diabetes.callbackquery_no_warn_handler import CallbackQueryNoWarnHandler

from diabetes.db import SessionLocal, Profile, Alert, Reminder, User
from diabetes.alert_handlers import evaluate_sugar
from diabetes.ui import menu_keyboard, back_keyboard, build_timezone_webapp_button
from diabetes.config import WEBAPP_URL
from .common_handlers import commit_session
import diabetes.reminder_handlers as reminder_handlers
from zoneinfo import ZoneInfo
import json


PROFILE_ICR, PROFILE_CF, PROFILE_TARGET, PROFILE_LOW, PROFILE_HIGH, PROFILE_TZ = range(6)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ``/profile`` command.

    * ``/profile`` → start step-by-step profile setup (conversation)
    * ``/profile help`` → show usage instructions
    * ``/profile <args>`` → set profile directly
    """

    args = context.args

    # Ensure no pending sugar logging conversation captures profile input
    from .dose_handlers import sugar_conv
    chat_data = getattr(context, "chat_data", {})
    if chat_data.pop("sugar_active", None):
        chat_id = getattr(update.effective_chat, "id", None) if sugar_conv.per_chat else None
        user_id = getattr(update.effective_user, "id", None) if sugar_conv.per_user else None
        msg_id = (
            getattr(update.effective_message, "message_id", None)
            if sugar_conv.per_message
            else None
        )
        sugar_conv._conversations.pop((chat_id, user_id, msg_id), None)

    help_text = (
        "❗ Формат команды:\n"
        "/profile <ИКХ г/ед.> <КЧ ммоль/л> <целевой ммоль/л> <низкий ммоль/л> <высокий ммоль/л>\n"
        "или /profile icr=<ИКХ> cf=<КЧ> target=<целевой> low=<низкий> high=<высокий>\n"
        "Пример: /profile 10 2 6 4 9 — ИКХ 10 г/ед., КЧ 2 ммоль/л, целевой 6 ммоль/л, низкий 4 ммоль/л, высокий 9 ммоль/л"
    )

    if len(args) == 1 and args[0].lower() == "help":
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return ConversationHandler.END

    if not args:
        await update.message.reply_text(
            "Введите коэффициент ИКХ (г/ед.) — сколько граммов углеводов покрывает 1 ед. быстрого инсулина:",
            reply_markup=back_keyboard,
        )
        return PROFILE_ICR

    values: dict[str, str] | None = None
    if len(args) == 5 and all("=" not in a for a in args):
        values = {
            "icr": args[0],
            "cf": args[1],
            "target": args[2],
            "low": args[3],
            "high": args[4],
        }
    else:
        parsed: dict[str, str] = {}
        for arg in args:
            if "=" not in arg:
                values = None
                break
            key, val = arg.split("=", 1)
            key = key.lower()
            match = None
            for full in ("icr", "cf", "target", "low", "high"):
                if full.startswith(key):
                    match = full
                    break
            if not match:
                values = None
                break
            parsed[match] = val
        else:
            if set(parsed) == {"icr", "cf", "target", "low", "high"}:
                values = parsed

    if values is None:
        await update.message.reply_text("❗ Неверный формат. Справка: /profile help")
        return ConversationHandler.END

    try:
        icr = float(values["icr"].replace(",", "."))
        cf = float(values["cf"].replace(",", "."))
        target = float(values["target"].replace(",", "."))
        low = float(values["low"].replace(",", "."))
        high = float(values["high"].replace(",", "."))
    except ValueError:
        await update.message.reply_text(
            "❗ Пожалуйста, введите корректные числа. Справка: /profile help"
        )
        return ConversationHandler.END

    if (
        icr <= 0
        or cf <= 0
        or target <= 0
        or low <= 0
        or high <= 0
        or low >= high
    ):
        await update.message.reply_text(
            "❗ Все значения должны быть больше 0, низкий порог < высокий. Справка: /profile help"
        )
        return ConversationHandler.END

    warning_msg = ""
    if icr > 8 or cf < 3:
        warning_msg = (
            "\n⚠️ Проверьте, пожалуйста: возможно, вы перепутали местами ИКХ и КЧ.\n"
            f"• Вы ввели ИКХ = {icr} г/ед. (высоковато)\n"
            f"• КЧ = {cf} ммоль/л (низковато)\n\n"
            "Если вы хотели ввести наоборот, отправьте:\n"
            f"/profile {cf} {icr} {target} {low} {high}\n"
            f"(ИКХ {cf}, КЧ {icr}, целевой {target}, низкий {low}, высокий {high})\n"
        )

    user_id = update.effective_user.id
    with SessionLocal() as session:
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)

        prof.icr = icr
        prof.cf = cf
        prof.target_bg = target
        prof.low_threshold = low
        prof.high_threshold = high
        if not commit_session(session):
            await update.message.reply_text("⚠️ Не удалось сохранить профиль.")
            return ConversationHandler.END  # end conversation on failure

    await update.message.reply_text(
        f"✅ Профиль обновлён:\n"
        f"• ИКХ: {icr} г/ед.\n"
        f"• КЧ: {cf} ммоль/л\n"
        f"• Целевой сахар: {target} ммоль/л\n"
        f"• Низкий порог: {low} ммоль/л\n"
        f"• Высокий порог: {high} ммоль/л" + warning_msg,
        parse_mode="Markdown",
        reply_markup=menu_keyboard,
    )
    return ConversationHandler.END


async def profile_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display current patient profile."""
    user_id = update.effective_user.id
    with SessionLocal() as session:
        profile = session.get(Profile, user_id)
        user = session.get(User, user_id)

    if not profile:
        await update.message.reply_text(
            "Ваш профиль пока не настроен.\n\n"
            "Чтобы настроить профиль, введите команду:\n"
            "/profile <ИКХ г/ед.> <КЧ ммоль/л> <целевой ммоль/л> <низкий ммоль/л> <высокий ммоль/л>\n"
            "или /profile icr=<ИКХ> cf=<КЧ> target=<целевой> low=<низкий> high=<высокий>\n"
            "Пример: /profile 10 2 6 4 9 — ИКХ 10 г/ед., КЧ 2 ммоль/л, целевой 6 ммоль/л, низкий 4 ммоль/л, высокий 9 ммоль/л",
            parse_mode="Markdown",
        )
        return

    tz = getattr(user, "timezone", "UTC") if user else "UTC"
    msg = (
        "📄 Ваш профиль:\n"
        f"• ИКХ: {profile.icr} г/ед.\n"  # Инсулин-карб коэффициент
        f"• КЧ: {profile.cf} ммоль/л\n"
        f"• Целевой сахар: {profile.target_bg} ммоль/л\n"
        f"• Низкий порог: {profile.low_threshold} ммоль/л\n"
        f"• Высокий порог: {profile.high_threshold} ммоль/л\n"
        f"• Часовой пояс: {tz}"
    )
    rows = [
        [InlineKeyboardButton("✏️ Изменить", callback_data="profile_edit")],
        [InlineKeyboardButton("🔔 Безопасность", callback_data="profile_security")],
        [InlineKeyboardButton("🌐 Часовой пояс", callback_data="profile_timezone")],
        [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")],
    ]
    if WEBAPP_URL:
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    "📝 Заполнить форму",
                    web_app=WebAppInfo(f"{WEBAPP_URL}/profile"),
                )
            ],
        )
    keyboard = InlineKeyboardMarkup(rows)
    await update.message.reply_text(msg, reply_markup=keyboard)


async def profile_webapp_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Save profile data sent from the web app."""
    raw = update.effective_message.web_app_data.data
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if {
        "icr",
        "cf",
        "target",
        "low",
        "high",
    } - data.keys():
        return
    try:
        icr = float(str(data["icr"]).replace(",", "."))
        cf = float(str(data["cf"]).replace(",", "."))
        target = float(str(data["target"]).replace(",", "."))
        low = float(str(data["low"]).replace(",", "."))
        high = float(str(data["high"]).replace(",", "."))
    except ValueError:
        return
    if icr <= 0 or cf <= 0 or target <= 0 or low <= 0 or high <= 0 or low >= high:
        await update.effective_message.reply_text(
            "❗ Все значения должны быть больше 0, низкий порог < высокий.",
            reply_markup=menu_keyboard,
        )
        return
    user_id = update.effective_user.id
    with SessionLocal() as session:
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)
        prof.icr = icr
        prof.cf = cf
        prof.target_bg = target
        prof.low_threshold = low
        prof.high_threshold = high
        if not commit_session(session):
            await update.effective_message.reply_text(
                "⚠️ Не удалось сохранить профиль.",
                reply_markup=menu_keyboard,
            )
            return
    await update.effective_message.reply_text(
        "✅ Профиль обновлён:\n"
        f"• ИКХ: {icr} г/ед.\n"
        f"• КЧ: {cf} ммоль/л\n"
        f"• Целевой сахар: {target} ммоль/л\n"
        f"• Низкий порог: {low} ммоль/л\n"
        f"• Высокий порог: {high} ммоль/л",
        reply_markup=menu_keyboard,
    )


async def profile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel profile creation conversation."""
    await update.message.reply_text("Отменено.", reply_markup=menu_keyboard)
    return ConversationHandler.END


async def profile_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to main menu from profile view."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await query.message.reply_text("📋 Выберите действие:", reply_markup=menu_keyboard)


async def profile_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to enter timezone."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Введите ваш часовой пояс (например Europe/Moscow):",
        reply_markup=back_keyboard,
    )
    button = build_timezone_webapp_button()
    if button:
        keyboard = InlineKeyboardMarkup([[button]])
        await query.message.reply_text(
            "Можно определить автоматически:", reply_markup=keyboard
        )
    return PROFILE_TZ


async def profile_timezone_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save user timezone from input."""
    raw = (
        update.message.web_app_data.data
        if getattr(update.message, "web_app_data", None)
        else update.message.text.strip()
    )
    if "назад" in raw.lower():
        return await profile_cancel(update, context)
    try:
        ZoneInfo(raw)
    except Exception:
        await update.message.reply_text(
            "Некорректный часовой пояс. Пример: Europe/Moscow",
            reply_markup=back_keyboard,
        )
        button = build_timezone_webapp_button()
        if button:
            keyboard = InlineKeyboardMarkup([[button]])
            await update.message.reply_text(
                "Можно определить автоматически:", reply_markup=keyboard
            )
        return PROFILE_TZ
    user_id = update.effective_user.id
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if not user:
            await update.message.reply_text(
                "Профиль не найден.", reply_markup=menu_keyboard
            )
            return ConversationHandler.END
        user.timezone = raw
        commit_session(session)
    await update.message.reply_text(
        "✅ Часовой пояс обновлён.", reply_markup=menu_keyboard
    )
    return ConversationHandler.END


async def profile_security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display and modify security settings."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    action = query.data.split(":", 1)[1] if ":" in query.data else None

    if action == "sos_contact":
        from diabetes import sos_handlers

        await sos_handlers.sos_contact_start(update.callback_query, context)
        return

    with SessionLocal() as session:
        profile = session.get(Profile, user_id)
        user = session.get(User, user_id)
        if not profile:
            await query.edit_message_text("Профиль не найден.")
            return

        changed = False
        if action == "low_inc":
            new = (profile.low_threshold or 0) + 0.5
            if profile.high_threshold is None or new < profile.high_threshold:
                profile.low_threshold = new
                changed = True
        elif action == "low_dec":
            new = (profile.low_threshold or 0) - 0.5
            if new > 0:
                profile.low_threshold = new
                changed = True
        elif action == "high_inc":
            new = (profile.high_threshold or 0) + 0.5
            profile.high_threshold = new
            changed = True
        elif action == "high_dec":
            new = (profile.high_threshold or 0) - 0.5
            if profile.low_threshold is None or new > profile.low_threshold:
                profile.high_threshold = new
                changed = True
        elif action == "toggle_sos":
            profile.sos_alerts_enabled = not profile.sos_alerts_enabled
            changed = True
        elif action == "add":
            if WEBAPP_URL:
                button = InlineKeyboardButton(
                    "📝 Новое", web_app=WebAppInfo(f"{WEBAPP_URL}/reminders")
                )
                keyboard = InlineKeyboardMarkup([[button]])
                await query.message.reply_text(
                    "Создать напоминание:", reply_markup=keyboard
                )
        elif action == "del":
            await reminder_handlers.delete_reminder(update, context)

        if changed:
            commit_session(session)
            alert = (
                session.query(Alert)
                .filter_by(user_id=user_id)
                .order_by(Alert.ts.desc())
                .first()
            )
            if alert:
                evaluate_sugar(user_id, alert.sugar, context.application.job_queue)

        low = profile.low_threshold or 0
        high = profile.high_threshold or 0
        sos = "вкл" if profile.sos_alerts_enabled else "выкл"
        rems = session.query(Reminder).filter_by(telegram_id=user_id).all()
        rem_text = (
            "\n".join(
                f"{r.id}. {reminder_handlers._describe(r, user)}" for r in rems
            )
            if rems
            else "нет"
        )
        text = (
            "🔐 Настройки безопасности:\n"
            f"Низкий порог: {low:.1f} ммоль/л\n"
            f"Высокий порог: {high:.1f} ммоль/л\n"
            f"SOS-уведомления: {sos}\n\n"
            f"⏰ Напоминания:\n{rem_text}"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Низкий -0.5", callback_data="profile_security:low_dec"),
                    InlineKeyboardButton("Низкий +0.5", callback_data="profile_security:low_inc"),
                ],
                [
                    InlineKeyboardButton("Высокий -0.5", callback_data="profile_security:high_dec"),
                    InlineKeyboardButton("Высокий +0.5", callback_data="profile_security:high_inc"),
                ],
                [
                    InlineKeyboardButton(
                        f"SOS-уведомления: {'off' if profile.sos_alerts_enabled else 'on'}",
                        callback_data="profile_security:toggle_sos",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "SOS контакт", callback_data="profile_security:sos_contact"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "➕ Добавить", callback_data="profile_security:add"
                    ),
                    InlineKeyboardButton(
                        "🗑 Удалить", callback_data="profile_security:del"
                    ),
                ],
                [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")],
            ]
        )
    await query.edit_message_text(text, reply_markup=keyboard)


async def profile_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start step-by-step profile setup."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await query.message.reply_text(
        "Введите коэффициент ИКХ (г/ед.) — сколько граммов углеводов покрывает 1 ед. быстрого инсулина:",
        reply_markup=back_keyboard,
    )
    return PROFILE_ICR


async def profile_icr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ICR input."""
    raw_text = update.message.text.strip()
    if "назад" in raw_text.lower():
        return await profile_cancel(update, context)
    text = raw_text.replace(",", ".")
    try:
        icr = float(text)
    except ValueError:
        await update.message.reply_text("Введите ИКХ числом.", reply_markup=back_keyboard)
        return PROFILE_ICR
    if icr <= 0:
        await update.message.reply_text("ИКХ должен быть больше 0.", reply_markup=back_keyboard)
        return PROFILE_ICR
    context.user_data["profile_icr"] = icr
    await update.message.reply_text(
        "Введите коэффициент чувствительности (КЧ) ммоль/л — на сколько ммоль/л 1 ед. инсулина снижает сахар:",
        reply_markup=back_keyboard,
    )
    return PROFILE_CF


async def profile_cf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle CF input."""
    raw_text = update.message.text.strip()
    if "назад" in raw_text.lower():
        await update.message.reply_text(
            "Введите коэффициент ИКХ (г/ед.) — сколько граммов углеводов покрывает 1 ед. быстрого инсулина:",
            reply_markup=back_keyboard,
        )
        return PROFILE_ICR
    text = raw_text.replace(",", ".")
    try:
        cf = float(text)
    except ValueError:
        await update.message.reply_text("Введите КЧ числом.", reply_markup=back_keyboard)
        return PROFILE_CF
    if cf <= 0:
        await update.message.reply_text("КЧ должен быть больше 0.", reply_markup=back_keyboard)
        return PROFILE_CF
    context.user_data["profile_cf"] = cf
    await update.message.reply_text(
        "Введите целевой уровень сахара (ммоль/л) — к какому значению вы стремитесь:",
        reply_markup=back_keyboard,
    )
    return PROFILE_TARGET


async def profile_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle target BG input."""
    raw_text = update.message.text.strip()
    if "назад" in raw_text.lower():
        await update.message.reply_text(
            "Введите коэффициент чувствительности (КЧ) ммоль/л — на сколько ммоль/л 1 ед. инсулина снижает сахар:",
            reply_markup=back_keyboard,
        )
        return PROFILE_CF
    text = raw_text.replace(",", ".")
    try:
        target = float(text)
    except ValueError:
        await update.message.reply_text(
            "Введите целевой сахар числом.", reply_markup=back_keyboard
        )
        return PROFILE_TARGET
    if target <= 0:
        await update.message.reply_text(
            "Целевой сахар должен быть больше 0.", reply_markup=back_keyboard
        )
        return PROFILE_TARGET
    context.user_data["profile_target"] = target
    await update.message.reply_text(
        "Введите нижний порог сахара (ммоль/л) — ниже него бот предупредит о гипогликемии:",
        reply_markup=back_keyboard,
    )
    return PROFILE_LOW


async def profile_low(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle low threshold input."""
    raw_text = update.message.text.strip()
    if "назад" in raw_text.lower():
        await update.message.reply_text(
            "Введите целевой уровень сахара (ммоль/л) — к какому значению вы стремитесь:",
            reply_markup=back_keyboard,
        )
        return PROFILE_TARGET
    text = raw_text.replace(",", ".")
    try:
        low = float(text)
    except ValueError:
        await update.message.reply_text(
            "Введите нижний порог числом.", reply_markup=back_keyboard
        )
        return PROFILE_LOW
    if low <= 0:
        await update.message.reply_text(
            "Нижний порог должен быть больше 0.", reply_markup=back_keyboard
        )
        return PROFILE_LOW
    context.user_data["profile_low"] = low
    await update.message.reply_text(
        "Введите верхний порог сахара (ммоль/л) — выше него бот предупредит о гипергликемии:",
        reply_markup=back_keyboard,
    )
    return PROFILE_HIGH


async def profile_high(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle high threshold input and save profile."""
    raw_text = update.message.text.strip()
    if "назад" in raw_text.lower():
        await update.message.reply_text(
            "Введите нижний порог сахара (ммоль/л) — ниже него бот предупредит о гипогликемии:",
            reply_markup=back_keyboard,
        )
        return PROFILE_LOW
    text = raw_text.replace(",", ".")
    try:
        high = float(text)
    except ValueError:
        await update.message.reply_text(
            "Введите верхний порог числом.", reply_markup=back_keyboard
        )
        return PROFILE_HIGH
    low = context.user_data.get("profile_low")
    if high <= 0 or low is None or high <= low:
        await update.message.reply_text(
            "Верхний порог должен быть больше нижнего и больше 0.",
            reply_markup=back_keyboard,
        )
        return PROFILE_HIGH
    icr = context.user_data.pop("profile_icr")
    cf = context.user_data.pop("profile_cf")
    target = context.user_data.pop("profile_target")
    context.user_data.pop("profile_low")
    user_id = update.effective_user.id
    with SessionLocal() as session:
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)
        prof.icr = icr
        prof.cf = cf
        prof.target_bg = target
        prof.low_threshold = low
        prof.high_threshold = high
        if not commit_session(session):
            await update.message.reply_text("⚠️ Не удалось сохранить профиль.")
            return ConversationHandler.END
    warning_msg = ""
    if icr > 8 or cf < 3:
        warning_msg = (
            "\n⚠️ Проверьте, пожалуйста: возможно, вы перепутали местами ИКХ и КЧ.\n"
            f"• Вы ввели ИКХ = {icr} г/ед. (высоковато)\n"
            f"• КЧ = {cf} ммоль/л (низковато)\n\n"
            "Если вы хотели ввести наоборот, отправьте:\n"
            f"/profile {cf} {icr} {target} {low} {high}\n"
            f"(ИКХ {cf}, КЧ {icr}, целевой {target}, низкий {low}, высокий {high})\n"
        )
    await update.message.reply_text(
        "✅ Профиль обновлён:\n"
        f"• ИКХ: {icr} г/ед.\n"
        f"• КЧ: {cf} ммоль/л\n"
        f"• Целевой сахар: {target} ммоль/л\n"
        f"• Низкий порог: {low} ммоль/л\n"
        f"• Высокий порог: {high} ммоль/л" + warning_msg,
        reply_markup=menu_keyboard,
    )
    return ConversationHandler.END


async def _photo_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .dose_handlers import _cancel_then, photo_prompt

    handler = _cancel_then(photo_prompt)
    return await handler(update, context)


profile_conv = ConversationHandler(
    entry_points=[
        CommandHandler("profile", profile_command),
        CallbackQueryNoWarnHandler(profile_edit, pattern="^profile_edit$"),
        CallbackQueryNoWarnHandler(profile_timezone, pattern="^profile_timezone$"),
    ],
    states={
        PROFILE_ICR: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_icr)],
        PROFILE_CF: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_cf)],
        PROFILE_TARGET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, profile_target)
        ],
        PROFILE_LOW: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, profile_low)
        ],
        PROFILE_HIGH: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, profile_high)
        ],
        PROFILE_TZ: [
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND) | filters.StatusUpdate.WEB_APP_DATA,
                profile_timezone_save,
            )
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^↩️ Назад$"), profile_cancel),
        CommandHandler("cancel", profile_cancel),
        MessageHandler(filters.Regex("^📷 Фото еды$"), _photo_fallback),
    ],
    # Subsequent steps depend on ``MessageHandler`` for text inputs. Enabling
    # ``per_message=True`` would store state per message and reset the
    # conversation after each reply, so we keep per-chat tracking.
    per_message=False,
)


profile_webapp_handler = MessageHandler(
    filters.StatusUpdate.WEB_APP_DATA, profile_webapp_save
)


__all__ = [
    "profile_command",
    "profile_view",
    "profile_cancel",
    "profile_back",
    "profile_security",
    "profile_timezone",
    "profile_edit",
    "profile_conv",
    "profile_webapp_save",
    "profile_webapp_handler",
]
