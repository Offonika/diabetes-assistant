# bot.py
import logging
import os

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")

from config import OPENAI_PROXY
#os.environ["HTTP_PROXY"] = OPENAI_PROXY
#os.environ["HTTPS_PROXY"] = OPENAI_PROXY

import re
import asyncio
import time
import logging


# Очищаем root‑логгер от сторонних библиотек
for logger_name in ("httpcore", "httpx", "telegram", "telegram.ext"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)  # Только WARNING и выше



logging.info("=== Bot started ===")
print("Логгер настроен, бот запускается")
from datetime import datetime, timezone   # ← добавили timezone

from gpt_command_parser import parse_command
from telegram.ext import MessageHandler, filters, CallbackQueryHandler
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from db import SessionLocal, init_db, User, Profile, Entry
from gpt_client import create_thread, send_message, client
from functions import PatientProfile, calc_bolus
from config import TELEGRAM_TOKEN

from sqlalchemy import DateTime, func
from db import SessionLocal, Entry, Profile, User, init_db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func          # уже нужен для фильтра по дате# ▸ bot.py  (положите рядом с остальными async‑хендлерами)
from pathlib import Path
import matplotlib.pyplot as plt
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
import textwrap

# Регистрация шрифтов для поддержки кириллицы и жирного начертания
pdfmetrics.registerFont(TTFont('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))

PROFILE_ICR, PROFILE_CF, PROFILE_TARGET         = range(0, 3)    # 0,1,2
DOSE_METHOD, DOSE_XE, DOSE_SUGAR, DOSE_CARBS    = range(3, 7)    # 3,4,5,6
PHOTO_SUGAR                                     = 7              # после DOSE_CARBS
SUGAR_VAL                                       = 8              # конверсация /sugar
# (подтверждение/переопределение дозы при желании  можно сделать 9 и 10)

WAITING_GPT_FLAG = "waiting_gpt_response"

# Клавиатура для выбора метода ввода
dose_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📷 Фото для оценки")],
        [KeyboardButton("✏️ Ввести углеводы (г)")],
        [KeyboardButton("🔢 Ввести ХЕ")],
        [KeyboardButton("❌ Отмена")],
    ],
    resize_keyboard=True
)

menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📷 Фото еды")], 
        [KeyboardButton("💉 Доза инсулина"), KeyboardButton("📊 История")],
        [KeyboardButton("📄 Мой профиль"), KeyboardButton("🔄 Изменить профиль")],
        [KeyboardButton("📈 Отчёт"), KeyboardButton("🔁 Сброс"), KeyboardButton("ℹ️ Помощь")]
    ],
    resize_keyboard=True
)



# ──────────────────────────────────────────────────────────────
async def freeform_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбросить старую pending_entry, если есть
    context.user_data.pop('pending_entry', None)
    raw_text = update.message.text.strip()
    user_id  = update.effective_user.id
    logger.info(f"FREEFORM raw='{raw_text}'  user={user_id}")

    # --- report_date_input ---
    if context.user_data.get('awaiting_report_date'):
        try:
            
            date_from = datetime.strptime(update.message.text.strip(), "%Y-%m-%d")
        except Exception:
            await update.message.reply_text("❗ Формат даты: YYYY-MM-DD")
            return
        await send_report(update, context, date_from, "указанный период")
        context.user_data.pop('awaiting_report_date', None)
        return

    # --- apply_edit ---
    if context.user_data.get('pending_entry') is not None and context.user_data.get('edit_id') is None:
        entry = context.user_data['pending_entry']
        only_sugar = (
            entry.get('carbs_g') is None and entry.get('xe') is None and entry.get('dose') is None and entry.get('photo_path') is None
        )
        text = update.message.text.lower().strip()
        if only_sugar:
            try:
                sugar = float(text.replace(",", "."))
                entry['sugar_before'] = sugar
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите число сахара в формате ммоль/л.")
                return
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
                    InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
                    InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
                ]
            ])
            await update.message.reply_text(
                f"Сохранить уровень сахара {sugar} ммоль/л в дневник?",
                reply_markup=keyboard
            )
            return
        parts = dict(re.findall(r"(\w+)\s*=\s*([\d.]+)", text))
        if not parts:
            await update.message.reply_text("Не вижу ни одного поля для изменения.")
            return
        if "xe" in parts:    entry['xe']           = float(parts["xe"])
        if "carbs" in parts: entry['carbs_g']      = float(parts["carbs"])
        if "dose" in parts:  entry['dose']         = float(parts["dose"])
        if "сахар" in parts or "sugar" in parts:
            entry['sugar_before'] = float(parts.get("сахар") or parts["sugar"])
        carbs = entry.get('carbs_g')
        xe = entry.get('xe')
        sugar = entry.get('sugar_before')
        dose = entry.get('dose')
        xe_info = f", ХЕ: {xe}" if xe is not None else ""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
                InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
            ]
        ])
        await update.message.reply_text(
            f"💉 Расчёт завершён:\n"
            f"• Углеводы: {carbs} г{xe_info}\n"
            f"• Сахар: {sugar} ммоль/л\n"
            f"• Ваша доза: {dose} Ед\n\n"
            f"Сохранить это в дневник?",
            reply_markup=keyboard
        )
        return
    if "edit_id" in context.user_data:
        text = update.message.text.lower()
        parts = dict(re.findall(r"(\w+)\s*=\s*([\d.]+)", text))
        if not parts:
            await update.message.reply_text("Не вижу ни одного поля для изменения.")
            return
        with SessionLocal() as s:
            entry = s.get(Entry, context.user_data["edit_id"])
            if not entry:
                await update.message.reply_text("Запись уже удалена.")
                context.user_data.pop("edit_id")
                return
            if "xe" in parts:    entry.xe           = float(parts["xe"])
            if "carbs" in parts: entry.carbs_g      = float(parts["carbs"])
            if "dose" in parts:  entry.dose         = float(parts["dose"])
            if "сахар" in parts or "sugar" in parts:
                entry.sugar_before = float(parts.get("сахар") or parts["sugar"])
            entry.updated_at = datetime.utcnow()
            s.commit()
        context.user_data.pop("edit_id")
        await update.message.reply_text("✅ Запись обновлена!")
        return

    # --- основной freeform ---
    parsed = await parse_command(raw_text)
    logger.info(f"FREEFORM parsed={parsed}")

    # если парсер не увидел понятной команды — передаём в GPT‑чат
    if not parsed or parsed.get("action") != "add_entry":
        await chat_with_gpt(update, context)
        return

    # ...дальше текущая логика добавления записи...
    fields      = parsed["fields"]
    entry_date  = parsed.get("entry_date")   # ISO‑строка или None
    time_str    = parsed.get("time")         # "HH:MM" или None

    # ── определяем event_time ─────────────────────────────────
    if entry_date:
        try:
            event_dt = datetime.fromisoformat(entry_date).replace(tzinfo=timezone.utc)
        except ValueError:
            event_dt = datetime.now(timezone.utc)
    elif time_str:
        try:
            hh, mm = map(int, time_str.split(":"))
            today  = datetime.now().date()
            event_dt = datetime.combine(today, dtime(hh, mm))
        except Exception:
            event_dt = datetime.now()
    else:
        event_dt = datetime.now(timezone.utc)

    context.user_data['pending_entry'] = {
        'telegram_id': user_id,
        'event_time': event_dt,
        'xe': fields.get('xe'),
        'carbs_g': fields.get('carbs_g'),
        'dose': fields.get('dose'),
        'sugar_before': fields.get('sugar_before'),
        'photo_path': None
    }

    xe_val     = fields.get('xe')
    carbs_val  = fields.get('carbs_g')
    dose_val   = fields.get('dose')
    sugar_val  = fields.get('sugar_before')
    date_str   = event_dt.strftime("%d.%m %H:%M")
    xe_part    = f"{xe_val} ХЕ"               if xe_val   is not None else ""
    carb_part  = f"{carbs_val:.0f} г углеводов" if carbs_val is not None else ""
    dose_part  = f"Инсулин: {dose_val} ед"    if dose_val is not None else ""
    sugar_part = f"Сахар: {sugar_val} ммоль/л" if sugar_val is not None else ""
    lines = "  \n- ".join(filter(None, [xe_part or carb_part, dose_part, sugar_part]))

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
        ]
    ])
    reply = f"💉 Расчёт завершён:\n\n{date_str}  \n- {lines}\n\nСохранить это в дневник?"
    await update.message.reply_text(reply, reply_markup=keyboard)
    return ConversationHandler.END


def extract_nutrition_info(text: str):
    """
    Ищет в тексте:
      • «Углеводы: 37 г ± 3 г»  → carbs = 37
      • «ХЕ: 3,1 ± 0,2»         → xe    = 3.1
      • диапазон «20–25 г»      → carbs = среднее
      • диапазон «3–4 ХЕ»       → xe    = среднее
    Возвращает (carbs_g, xe)
    """
    carbs = xe = None
    # --- новый строгий формат со знаком ± ---
    m = re.search(r"углевод[^\d]*:\s*([\d.,]+)\s*г", text, re.IGNORECASE)
    if m:
        carbs = float(m.group(1).replace(",", "."))

    m = re.search(r"\bх[еe][^\d]*:\s*([\d.,]+)", text, re.IGNORECASE)
    if m:
        xe = float(m.group(1).replace(",", "."))

    # --- диапазоны «20–25 г» / «3–4 ХЕ» ---
    if carbs is None:
        rng = re.search(r"(\d+[.,]?\d*)\s*[–-]\s*(\d+[.,]?\d*)\s*г", text, re.IGNORECASE)
        if rng:
            carbs = (float(rng.group(1).replace(",", ".")) +
                     float(rng.group(2).replace(",", "."))) / 2

    if xe is None:
        rng = re.search(r"(\d+[.,]?\d*)\s*[–-]\s*(\d+[.,]?\d*)\s*(?:ХЕ|XE)", text, re.IGNORECASE)
        if rng:
            xe = (float(rng.group(1).replace(",", ".")) +
                  float(rng.group(2).replace(",", "."))) / 2

    return carbs, xe

# ▸ bot.py  (положите рядом с остальными async‑хендлерами)
async def apply_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если редактируем pending_entry (ещё не сохранено в БД)
    if context.user_data.get('pending_entry') is not None and context.user_data.get('edit_id') is None:
        entry = context.user_data['pending_entry']
        # Проверяем: если это только сахар
        only_sugar = (
            entry.get('carbs_g') is None and entry.get('xe') is None and entry.get('dose') is None and entry.get('photo_path') is None
        )
        text = update.message.text.lower().strip()
        if only_sugar:
            # Ожидаем только новое значение сахара
            try:
                sugar = float(text.replace(",", "."))
                entry['sugar_before'] = sugar
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите число сахара в формате ммоль/л.")
                return
            # Показываем подтверждение
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
                    InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
                    InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
                ]
            ])
            await update.message.reply_text(
                f"Сохранить уровень сахара {sugar} ммоль/л в дневник?",
                reply_markup=keyboard
            )
            return
        # Обычный режим: ожидаем поля в формате key=value
        parts = dict(re.findall(r"(\w+)\s*=\s*([\d.]+)", text))
        if not parts:
            await update.message.reply_text("Не вижу ни одного поля для изменения.")
            return
        if "xe" in parts:    entry['xe']           = float(parts["xe"])
        if "carbs" in parts: entry['carbs_g']      = float(parts["carbs"])
        if "dose" in parts:  entry['dose']         = float(parts["dose"])
        if "сахар" in parts or "sugar" in parts:
            entry['sugar_before'] = float(parts.get("сахар") or parts["sugar"])
        # После редактирования снова показать подтверждение
        carbs = entry.get('carbs_g')
        xe = entry.get('xe')
        sugar = entry.get('sugar_before')
        dose = entry.get('dose')
        xe_info = f", ХЕ: {xe}" if xe is not None else ""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
                InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
            ]
        ])
        await update.message.reply_text(
            f"💉 Расчёт завершён:\n"
            f"• Углеводы: {carbs} г{xe_info}\n"
            f"• Сахар: {sugar} ммоль/л\n"
            f"• Ваша доза: {dose} Ед\n\n"
            f"Сохранить это в дневник?",
            reply_markup=keyboard
        )
        return
    # --- Старый режим: редактирование уже существующей записи ---
    if "edit_id" not in context.user_data:    # нет режима редактирования
        return

    text = update.message.text.lower()
    parts = dict(re.findall(r"(\w+)\s*=\s*([\d.]+)", text))
    if not parts:
        await update.message.reply_text("Не вижу ни одного поля для изменения.")
        return

    with SessionLocal() as s:
        entry = s.get(Entry, context.user_data["edit_id"])
        if not entry:
            await update.message.reply_text("Запись уже удалена.")
            context.user_data.pop("edit_id")
            return

        # обновляем поля, если присутствуют
        if "xe" in parts:    entry.xe           = float(parts["xe"])
        if "carbs" in parts: entry.carbs_g      = float(parts["carbs"])
        if "dose" in parts:  entry.dose         = float(parts["dose"])
        if "сахар" in parts or "sugar" in parts:
            entry.sugar_before = float(parts.get("сахар") or parts["sugar"])
        entry.updated_at = datetime.utcnow()
        s.commit()

    context.user_data.pop("edit_id")
    await update.message.reply_text("✅ Запись обновлена!")

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает inline‑кнопки из /history и подтверждения записи."""
    query = update.callback_query
    await query.answer()  # обязательный ACK
    data = query.data

    # --- Подтверждение новой записи после фото ---
    if data == "confirm_entry":
        entry_data = context.user_data.pop('pending_entry', None)
        if not entry_data:
            await query.edit_message_text("❗ Нет данных для сохранения.")
            return
        session = SessionLocal()
        entry = Entry(**entry_data)
        session.add(entry)
        session.commit()
        session.close()
        await query.edit_message_text("✅ Запись сохранена в дневник!")
        return
    if data == "edit_entry":
        entry_data = context.user_data.get('pending_entry')
        if not entry_data:
            await query.edit_message_text("❗ Нет данных для редактирования.")
            return
        # Переводим в режим ручного редактирования (apply_edit)
        context.user_data['edit_id'] = None  # Можно реализовать редактирование pending_entry через текст
        await query.edit_message_text(
            "Отправьте новое сообщение в формате:\n"
            "`сахар=<ммоль/л>  xe=<ХЕ>  carbs=<г>  dose=<ед>`\n"
            "Можно указывать не все поля (что прописано — то и поменяется).",
            parse_mode="Markdown"
        )
        # Далее пользователь отправляет текст, и apply_edit должен обработать pending_entry
        return
    if data == "cancel_entry":
        context.user_data.pop('pending_entry', None)
        await query.edit_message_text("❌ Запись отменена.", reply_markup=menu_keyboard)
        return

    # --- Старый код: обработка истории ---
    if ":" in data:
        action, entry_id = data.split(":", 1)
        with SessionLocal() as s:
            entry = s.get(Entry, int(entry_id))
            if not entry:
                await query.edit_message_text("Запись не найдена (уже удалена).")
                return
            if action == "del":
                s.delete(entry)
                s.commit()
                await query.edit_message_text("❌ Запись удалена.")
                return
            if action == "edit":
                context.user_data["edit_id"] = entry.id
                txt = (
                    "Отправьте новое сообщение в формате:\n"
                    "`сахар=<ммоль/л>  xe=<ХЕ>  carbs=<г>  dose=<ед>`\n"
                    "Можно указывать не все поля (что прописано — то и поменяется).",
                )
                await query.edit_message_text("\n".join(txt), parse_mode="Markdown")
                return

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or not document.mime_type.startswith("image/"):
        return ConversationHandler.END

    user_id = update.effective_user.id
    ext      = Path(document.file_name).suffix or ".jpg"
    file_path = f"photos/{user_id}_{document.file_unique_id}{ext}"
    os.makedirs("photos", exist_ok=True)
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_path)

    # записываем путь и вызовем photo_handler
    context.user_data["__file_path"] = file_path
    return await photo_handler(update, context, demo=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    session = SessionLocal()
    user_id = update.effective_user.id
    user = session.get(User, user_id)

    if not user:
        thread_id = create_thread()
        user = User(telegram_id=user_id, thread_id=thread_id)
        session.add(user)
        session.commit()

    session.close()

    await update.message.reply_text(
        "👋 <b>Привет, рад снова тебя видеть!</b>\n"
        "📘 Я помогу вести твой диабетический дневник:\n"
        "• добавлять записи,\n"
        "• считать дозу 💉,\n"
        "• анализировать питание 🍽️\n\n"
        "✍️ Просто напиши: <code>Я съел 4 ХЕ, уколол 6 ед</code>\n"
        "📷 Или пришли фото еды — я всё распознаю и подскажу дозу!\n"
        "🤖 Остальное я возьму на себя.\n\n"
        "🔎 Хочешь узнать больше? Нажми «📄 Что умею» в меню Telegram.",
        parse_mode="HTML",
        reply_markup=menu_keyboard
    )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📋 <b>Меню действий:</b>\n\n"
        "📷 <b>Фото еды</b> — пришли снимок, я распознаю ХЕ и посчитаю дозу\n"
        "💉 <b>Доза инсулина</b> — ручной ввод ХЕ/углеводов + сахар\n"
        "📊 <b>История</b> — покажу последние записи\n"
        "📄 <b>Мой профиль</b> — коэффициенты ИКХ/КЧ и целевой сахар\n"
        "🔄 <b>Изменить профиль</b> — если поменялись параметры\n"
        "🔁 <b>Сброс</b> — удалить профиль и все записи\n\n"
        "✍️ Или просто пиши команды в свободной форме: «я съел 3 ХЕ», «добавь сахар 7.5» и т.д.",
        parse_mode="HTML",
        reply_markup=menu_keyboard
    )

async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    session = SessionLocal()
    user_id = update.effective_user.id
    session.query(Entry).filter_by(telegram_id=user_id).delete()
    session.query(Profile).filter_by(telegram_id=user_id).delete()
    session.query(User).filter_by(telegram_id=user_id).delete()  # Теперь удаляем и пользователя
    session.commit()
    session.close()
    await update.message.reply_text("Профиль и история удалены. Вы можете начать заново.", reply_markup=menu_keyboard)

# === Профиль ===
async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    user_id = update.effective_user.id
    profile = session.get(Profile, user_id)
    session.close()
    
    current_value = f"(текущее: {profile.icr} г/ед.)" if profile and profile.icr else ""
    await update.message.reply_text(
        f"Введите ИКХ (сколько г углеводов на 1 ед. инсулина) {current_value}:"
    )
    return PROFILE_ICR

async def profile_icr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['icr'] = float(update.message.text)
        
        session = SessionLocal()
        profile = session.get(Profile, update.effective_user.id)
        session.close()

        current_value = f"(текущее: {profile.cf} ммоль/л)" if profile and profile.cf else ""
        await update.message.reply_text(
            f"Введите коэффициент коррекции (КЧ) {current_value}:"
        )
        return PROFILE_CF
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return PROFILE_ICR

async def profile_cf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['cf'] = float(update.message.text)

        session = SessionLocal()
        profile = session.get(Profile, update.effective_user.id)
        session.close()

        current_value = f"(текущее: {profile.target_bg} ммоль/л)" if profile and profile.target_bg else ""
        await update.message.reply_text(
            f"Введите целевой уровень сахара {current_value}:"
        )
        return PROFILE_TARGET
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return PROFILE_CF

async def profile_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['target'] = float(update.message.text)
        session = SessionLocal()
        user_id = update.effective_user.id
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)
        prof.icr = context.user_data['icr']
        prof.cf = context.user_data['cf']
        prof.target_bg = context.user_data['target']
        session.commit()
        session.close()
        await update.message.reply_text("✅ Профиль сохранён.", reply_markup=menu_keyboard)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return PROFILE_TARGET
    
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "❗ Формат команды:\n"
            "/profile <ИКХ> <КЧ> <целевой>\n"
            "Пример: /profile 2 10 6",
            parse_mode="Markdown"
        )
        return

    try:
        icr = float(args[0])
        cf = float(args[1])
        target = float(args[2])

        # Флаги подозрения
        suspicious = False
        warning_msg = ""

        if icr > 8 or cf < 3:
            suspicious = True
            warning_msg = (
                "\n⚠️ Проверьте, пожалуйста: возможно, вы перепутали местами ИКХ и КЧ.\n"
                f"• Вы ввели ИКХ = {icr} ммоль/л (высоковато)\n"
                f"• КЧ = {cf} г/ед. (низковато)\n\n"
                "Если вы хотели ввести наоборот, отправьте:\n"
                f"/profile {cf} {icr} {target}\n"
            )

        session = SessionLocal()
        user_id = update.effective_user.id
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)

        prof.icr = cf  # г/ед
        prof.cf = icr  # ммоль/л
        prof.target_bg = target
        session.commit()
        session.close()

        await update.message.reply_text(
            f"✅ Профиль обновлён:\n"
            f"• ИКХ: {icr} ммоль/л\n"
            f"• КЧ: {cf} г/ед.\n"
            f"• Целевой сахар: {target} ммоль/л"
            + warning_msg,
            parse_mode="Markdown"
        )

    except ValueError:
        await update.message.reply_text(
            "❗ Пожалуйста, введите корректные числа. Пример:\n/profile 2 10 6",
            parse_mode="Markdown"
        )

async def profile_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    session = SessionLocal()
    user_id = update.effective_user.id
    profile = session.get(Profile, user_id)
    session.close()

    if not profile:
        await update.message.reply_text(
            "Ваш профиль пока не настроен.\n\n"
            "Чтобы настроить профиль, введите команду:\n"
            "/profile <ИКХ> <КЧ> <целевой>\n"
            "Пример: /profile 2 10 6",
            parse_mode="Markdown"
        )
        return

    msg = (
        f"📄 Ваш профиль:\n"
        f"• ИКХ: {profile.cf} ммоль/л\n"
        f"• КЧ: {profile.icr} г/ед.\n"
        f"• Целевой сахар: {profile.target_bg} ммоль/л"
    )
    await update.message.reply_text(msg)


async def profile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=menu_keyboard)
    return ConversationHandler.END

async def photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки '📷 Фото еды'"""
    await update.message.reply_text(
        "📸 Пожалуйста, отправьте фото блюда, и я оценю углеводы и ХЕ.",
        reply_markup=menu_keyboard
    )

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.", reply_markup=menu_keyboard)
    return ConversationHandler.END

# === Доза ===
async def dose_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Как вы хотите получить количество углеводов?\n"
        "• 📷 Фото для оценки\n"
        "• ✏️ Ввести углеводы (г)\n"
        "• 🔢 Ввести ХЕ",
        reply_markup=dose_keyboard
    )
    return DOSE_METHOD

async def sugar_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если аргумент передан сразу, сохраняем сразу
    if context.args:
        try:
            sugar = float(context.args[0].replace(",", "."))
            # Записываем в БД
            session = SessionLocal()
            entry = Entry(telegram_id=update.effective_user.id, sugar_before=sugar)
            session.add(entry); session.commit(); session.close()
            await update.message.reply_text(f"✅ Уровень сахара сохранён: {sugar} ммоль/л", reply_markup=menu_keyboard)
            return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("❗ Неправильный формат. Введите число или /sugar <число>")
            return ConversationHandler.END

    # Иначе — просим ввести
    await update.message.reply_text("Введите текущий уровень сахара (ммоль/л):", reply_markup=menu_keyboard)
    return SUGAR_VAL

async def sugar_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбросить старую pending_entry, если есть
    context.user_data.pop('pending_entry', None)
    try:
        sugar = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❗ Пожалуйста, введите число.")
        return SUGAR_VAL

    user_id = update.effective_user.id
    event_time = datetime.now(timezone.utc)
    # Сохраняем все данные во временный блок
    context.user_data['pending_entry'] = {
        'telegram_id': user_id,
        'event_time': event_time,
        'photo_path': None,
        'carbs_g': None,
        'xe': None,
        'sugar_before': sugar,
        'dose': None
    }
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
        ]
    ])
    await update.message.reply_text(
        f"Сохранить уровень сахара {sugar} ммоль/л в дневник?",
        reply_markup=keyboard
    )
    return ConversationHandler.END

# ──────────────────────────────────────────────────────────────
async def dose_sugar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбросить старую pending_entry, если есть
    context.user_data.pop('pending_entry', None)
    try:
        sugar = float(update.message.text.replace(",", "."))
        context.user_data["sugar"] = sugar
    except ValueError:
        await update.message.reply_text("Введите число.")
        return DOSE_SUGAR

    user_id = update.effective_user.id
    session = SessionLocal()
    profile = session.get(Profile, user_id)
    if not profile:
        session.close()
        await update.message.reply_text("Профиль не найден. Используйте /profile.")
        return ConversationHandler.END

    icr, cf, target_bg = profile.icr, profile.cf, profile.target_bg

    last_carbs = context.user_data.get("last_carbs")
    last_photo_time = context.user_data.get("last_photo_time")
    now = time.time()

    if last_carbs is not None and last_photo_time and now - last_photo_time < 600:
        carbs, xe_val = last_carbs, None
    elif context.user_data.get("xe") is not None:
        xe_val = context.user_data["xe"]
        carbs = xe_val * 12          # 1 ХЕ = 12 г
    else:
        session.close()
        await update.message.reply_text(
            "Нет данных о количестве углеводов. Сначала отправьте фото блюда или введите углеводы вручную.",
            reply_markup=menu_keyboard
        )
        return ConversationHandler.END

    dose = calc_bolus(carbs, sugar, PatientProfile(icr, cf, target_bg))
    event_time = datetime.now(timezone.utc)
    session.close()

    # Сохраняем все данные во временный блок
    context.user_data['pending_entry'] = {
        'telegram_id': user_id,
        'event_time': event_time,
        'photo_path': context.user_data.get('photo_path'),
        'carbs_g': carbs,
        'xe': xe_val,
        'sugar_before': sugar,
        'dose': dose
    }

    xe_info = f", ХЕ: {xe_val}" if xe_val is not None else ""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
        ]
    ])
    await update.message.reply_text(
        f"💉 Расчёт завершён:\n"
        f"• Углеводы: {carbs} г{xe_info}\n"
        f"• Сахар: {sugar} ммоль/л\n"
        f"• Ваша доза: {dose} Ед\n\n"
        f"Сохранить это в дневник?",
        reply_markup=keyboard
    )
    # очищаем временные данные, кроме pending_entry
    for k in ("last_carbs", "last_photo_time", "xe", "sugar", "photo_path"):
        if k in context.user_data and k != 'pending_entry':
            context.user_data.pop(k, None)
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────
# Обработчик ✏️ «Ввести углеводы (г)»
async def dose_carbs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Пользователь вводит углеводы вручную.
      1. Сохраняем количество во временный контекст.
      2. Просим ввести сахар (переход в DOSE_SUGAR).
      3. Дозу рассчитает dose_sugar после ввода сахара.
    """
    try:
        carbs_input = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число граммов углеводов.")
        return DOSE_CARBS

    # сохраняем углеводы как «последние» и помечаем время (≤10 мин)
    context.user_data["last_carbs"] = carbs_input
    context.user_data["last_photo_time"] = time.time()

    await update.message.reply_text(
        "Введите текущий уровень сахара (ммоль/л):",
        reply_markup=menu_keyboard
    )
    return DOSE_SUGAR
# ──────────────────────────────────────────────────────────────


async def dose_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📷 Фото для оценки":
        # Завершаем текущий диалог /dose,
        # а дальше сработает отдельный photo_conv
        await update.message.reply_text(
            "Отправьте, пожалуйста, фото блюда:",
            reply_markup=menu_keyboard
        )
        return ConversationHandler.END

    if text == "✏️ Ввести углеводы (г)":
        await update.message.reply_text(
            "Введите, пожалуйста, количество углеводов в граммах:",
            reply_markup=menu_keyboard
        )
        return DOSE_CARBS

    if text == "🔢 Ввести ХЕ":
        await update.message.reply_text(
            "Введите, пожалуйста, количество хлебных единиц (ХЕ):",
            reply_markup=menu_keyboard
        )
        return DOSE_XE

    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.", reply_markup=menu_keyboard)
        return ConversationHandler.END

    # Если ввели что-то не из меню
    await update.message.reply_text(
        "Пожалуйста, выберите один из пунктов на клавиатуре.",
        reply_markup=dose_keyboard
    )
    return DOSE_METHOD


async def dose_xe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        xe = float(update.message.text.replace(",", "."))
        context.user_data['xe'] = xe
        # теперь запросим сахар, дальше пойдёт обычный сценарий sugar→carbs→dose
        await update.message.reply_text("Введите текущий уровень сахара (ммоль/л):", reply_markup=menu_keyboard)
        return DOSE_SUGAR
    except ValueError:
        await update.message.reply_text("Введите число ХЕ.")
        return DOSE_XE



async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, demo: bool = False):
    from gpt_client import client, send_message, create_thread
    import time

    message = update.message or update.callback_query.message
    user_id = update.effective_user.id

    if context.user_data.get(WAITING_GPT_FLAG):
        await message.reply_text("⏳ Уже обрабатываю фото, подождите…")
        return ConversationHandler.END
    context.user_data[WAITING_GPT_FLAG] = True

    # 1. Получение file_path
    file_path = context.user_data.pop("__file_path", None)
    if not file_path:
        try:
            photo = update.message.photo[-1]
        except (AttributeError, IndexError):
            await message.reply_text("❗ Файл не распознан как изображение.")
            context.user_data.pop(WAITING_GPT_FLAG, None)
            return ConversationHandler.END

        os.makedirs("photos", exist_ok=True)
        file_path = f"photos/{user_id}_{photo.file_unique_id}.jpg"
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(file_path)

    logging.info("[PHOTO] Saved to %s", file_path)

    try:
        # 2. Запуск Vision run
        thread_id = context.user_data.get("thread_id") or create_thread()
        run = send_message(
            thread_id=thread_id,
            content="Определи количество углеводов и ХЕ на фото блюда. Используй формат из системных инструкций ассистента.",
            image_path=file_path
        )
        await message.reply_text("🔍 Анализирую фото (это займёт 5‑10 с)…")

        # 3. Ждать окончания run
        while run.status not in ("completed", "failed", "cancelled", "expired"):
            time.sleep(2)
            run = client.beta.threads.runs.retrieve(thread_id=run.thread_id, run_id=run.id)

        if run.status != "completed":
            logging.error(f"[VISION][RUN_FAILED] run.status={run.status}")
            await message.reply_text("⚠️ Vision не смог обработать фото.")
            return ConversationHandler.END

        # 4. Читать все сообщения в thread (и логировать)
        messages = client.beta.threads.messages.list(thread_id=run.thread_id)
        for m in messages.data:
            logging.warning(f"[VISION][MSG] m.role={m.role}; content={m.content}")

        # 5. Ищем ответ ассистента
        vision_text = next((m.content[0].text.value for m in messages.data if m.role == "assistant" and m.content), "")
        logging.warning(f"[VISION][RESPONSE] Ответ Vision для {file_path}:\n{vision_text}")

        carbs_g, xe = extract_nutrition_info(vision_text)
        if carbs_g is None and xe is None:
            # ЛОГИРУЕМ ОТВЕТ Vision и файл
            logging.warning(
                "[VISION][NO_PARSE] Ответ ассистента: %r для файла: %s", vision_text, file_path
            )
            await message.reply_text(
                "⚠️ Не смог разобрать углеводы на фото.\n\n"
                f"Вот полный ответ Vision:\n<pre>{vision_text}</pre>\n"
                "Введите /dose и укажите их вручную.",
                parse_mode="HTML",
                reply_markup=menu_keyboard
            )
            return ConversationHandler.END


        # 6. Сохраняем и показываем
        context.user_data.update({"carbs": carbs_g, "xe": xe, "photo_path": file_path})
        await message.reply_text(
            f"🍽️ На фото:\n{vision_text}\n\n"
            "Введите текущий сахар (ммоль/л) — и я рассчитаю дозу инсулина.",
            reply_markup=menu_keyboard
        )
        return PHOTO_SUGAR

    except Exception as e:
        logging.exception("[PHOTO] Vision failed: %s", e)
        await message.reply_text("⚠️ Не удалось распознать фото. Попробуйте ещё раз.")
        return ConversationHandler.END

    finally:
        context.user_data.pop(WAITING_GPT_FLAG, None)


async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Пользователь отправил изображение как «файл» (document‑image).
    Скачиваем оригинал и передаём в общий photo‑flow.
    """
    document = update.message.document
    # игнорируем, если вдруг пришёл pdf/zip
    if not document or not document.mime_type.startswith("image/"):
        return ConversationHandler.END

    user_id = update.effective_user.id
    # путь сохранения
    ext  = Path(document.file_name).suffix or ".jpg"
    path = f"photos/{user_id}_{document.file_unique_id}{ext}"
    os.makedirs("photos", exist_ok=True)

    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(path)

    # кладём путь и «псевдо‑фото» в update, чтобы дальше всё работало
    context.user_data["__file_path"] = path
    # чтобы код, который где‑то проверяет .photo, не упал
             # пустой список‑заглушка

    # переходим в обычный обработчик фото
    return await photo_handler(update, context)

async def photo_sugar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sugar = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❗ Пожалуйста, введите число.")
        return PHOTO_SUGAR

    user_id = update.effective_user.id
    carbs = context.user_data.get("carbs")
    xe = context.user_data.get("xe")
    photo_path = context.user_data.get("photo_path")
    session = SessionLocal()
    profile = session.get(Profile, user_id)
    if not profile or carbs is None:
        session.close()
        await update.message.reply_text("Нет данных для расчёта. Начните заново.", reply_markup=menu_keyboard)
        return ConversationHandler.END

    dose = calc_bolus(carbs, sugar, PatientProfile(profile.icr, profile.cf, profile.target_bg))
    event_time = datetime.now(timezone.utc)
    session.close()

    context.user_data['pending_entry'] = {
        'telegram_id': user_id,
        'event_time': event_time,
        'photo_path': photo_path,
        'carbs_g': carbs,
        'xe': xe,
        'sugar_before': sugar,
        'dose': dose
    }

    xe_info = f", ХЕ: {xe}" if xe is not None else ""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data="confirm_entry"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_entry"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_entry")
        ]
    ])
    await update.message.reply_text(
        f"💉 Расчёт завершён:\n"
        f"• Углеводы: {carbs} г{xe_info}\n"
        f"• Сахар: {sugar} ммоль/л\n"
        f"• Ваша доза: {dose} Ед\n\n"
        f"Сохранить это в дневник?",
        reply_markup=keyboard
    )
    # очищаем временные данные, кроме pending_entry
    for k in ("carbs", "xe", "photo_path"):
        if k in context.user_data and k != 'pending_entry':
            context.user_data.pop(k, None)
    return ConversationHandler.END

async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /history                   – последние 5 записей
    /history YYYY‑MM‑DD        – записи за конкретный день
    """
    context.user_data.clear()
    user_id = update.effective_user.id

    # ── аргумент‑дата (опционально) ──────────────────────────────
    day = None
    if context.args:
        try:
            day = datetime.fromisoformat(context.args[0]).date()
        except ValueError:
            await update.message.reply_text(
                "❗ Формат даты: YYYY-MM-DD  (пример: /history 2025-05-05)"
            )
            return

    with SessionLocal() as s:
        query = s.query(Entry).filter_by(telegram_id=user_id)
        if day:
            query = query.filter(func.date(Entry.event_time) == day)

        entries = (
            query
            .order_by(Entry.event_time.desc())
            .limit(None if day else 5)
            .all()
        )

    if not entries:
        await update.message.reply_text("История пуста.")
        return

    header = "Записи за " + str(day) if day else "Последние записи"
    await update.message.reply_text(f"📖 {header}:")

    # ── выводим каждую запись отдельным сообщением ───────────────
    for e in entries:
        when   = e.event_time.astimezone().strftime("%d.%m %H:%M")
        carbs  = f"{e.carbs_g:.0f} г" if e.carbs_g else f"{e.xe:.1f} ХЕ" if e.xe else "-"
        dose   = f"{e.dose:.1f} ед"   if e.dose else "-"
        sugar  = f"{e.sugar_before:.1f}" if e.sugar_before else "-"

        text = (
            f"🕒 {when}\n"
            f"• Сахар: {sugar} ммоль/л\n"
            f"• Углеводы: {carbs}\n"
            f"• Доза: {dose}"
        )

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Исправить", callback_data=f"edit:{e.id}"),
                InlineKeyboardButton("🗑️ Удалить",   callback_data=f"del:{e.id}")
            ]
        ])
        await update.message.reply_text(text, reply_markup=kb)

async def chat_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return  # игнорируем не‑текст

    session   = SessionLocal()
    user_id   = update.effective_user.id
    user      = session.get(User, user_id)
    session.close()
    if not user:
        await update.message.reply_text("Сначала используйте /start.")
        return

    # 1) отправляем сообщение (или изображение) в GPT
    run = send_message(user.thread_id, content=update.message.text)
    await update.message.reply_text("⏳ Жду ответ от GPT...")

    # 2) ждём, пока Assistant закончит
    while run.status not in ("completed", "failed", "cancelled", "expired"):
        await asyncio.sleep(2)
        run = client.beta.threads.runs.retrieve(
            thread_id=user.thread_id,
            run_id=run.id
        )

    # 3) если не completed – сообщаем об ошибке и выходим
    if run.status != "completed":
        await update.message.reply_text(
            f"⚠️ GPT не смог ответить (status={run.status}). Попробуйте позже."
        )
        logging.error(f"GPT run failed: {run}")
        return

    # 4) получаем последний ответ Assistant'а
    messages = client.beta.threads.messages.list(thread_id=user.thread_id)
    reply_msg = next(
        (m for m in messages.data if m.role == "assistant"), None
    )

    if not reply_msg:
        await update.message.reply_text("⚠️ Ответ пустой.")
        return

    reply_text = reply_msg.content[0].text.value
    await update.message.reply_text(reply_text)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 <b>Помощь</b>\n\n"
        "Ты можешь:\n"
        "• Отправить 📷 фото еды — я распознаю ХЕ и рассчитаю дозу\n"
        "• Написать: «съел 3 ХЕ, сахар 7.5, уколол 4 ед» — и я добавлю запись\n"
        "• Ввести /dose или нажать кнопку, чтобы рассчитать дозу вручную\n"
        "• Команда /history покажет последние записи\n\n"
        "Если что-то непонятно — просто напиши 🙂",
        parse_mode="HTML"
    )

async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня", callback_data="report_today"),
         InlineKeyboardButton("Неделя", callback_data="report_week")],
        [InlineKeyboardButton("Месяц", callback_data="report_month"),
         InlineKeyboardButton("Указать дату", callback_data="report_custom")]
    ])
    await update.message.reply_text(
        "📊 За какой период сделать отчёт?",
        reply_markup=keyboard
    )

async def report_period_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    user_id = update.effective_user.id
    now = datetime.now()
    if data == "report_today":
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_label = "сегодня"
    elif data == "report_week":
        date_from = now - timedelta(days=7)
        period_label = "неделю"
    elif data == "report_month":
        date_from = now - timedelta(days=30)
        period_label = "месяц"
    elif data == "report_custom":
        await query.edit_message_text("Введите дату начала отчёта в формате YYYY-MM-DD:")
        context.user_data['awaiting_report_date'] = True
        return
    else:
        await query.edit_message_text("Неизвестный период.")
        return
    # Новое: сообщение-ожидание
    await query.edit_message_text(f"⏳ Формирую отчёт за {period_label}, пожалуйста, подождите...")
    await send_report(update, context, date_from, period_label, query=query)

async def report_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_report_date'):
        try:
            
            date_from = datetime.strptime(update.message.text.strip(), "%Y-%m-%d")
        except Exception:
            await update.message.reply_text("❗ Формат даты: YYYY-MM-DD")
            return
        await send_report(update, context, date_from, "указанный период")
        context.user_data.pop('awaiting_report_date', None)

def clean_markdown(text):
    """
    Удаляет простую Markdown-разметку: **жирный**, # заголовки, * списки, 1. списки и т.д.
    """
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **жирный**
    text = re.sub(r'#+\s*', '', text)                  # ### Заголовки
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)  # 1. списки
    text = re.sub(r'^\s*\*\s*', '', text, flags=re.MULTILINE)      # * списки
    text = re.sub(r'`([^`]+)`', r'\1', text)           # `код`
    return text

def split_text_by_width(text, font_name, font_size, max_width_mm):
    """Разбивает строку так, чтобы она не выходила за max_width_mm."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        width = stringWidth(test_line, font_name, font_size) / mm
        if width > max_width_mm and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    return lines

def generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf_graph):
    from io import BytesIO
    pdf_buf = BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    y = height - 20*mm
    c.setFont("DejaVuSans-Bold", 16)
    c.drawString(20*mm, y, "Отчёт по диабетическому дневнику")
    y -= 12*mm
    c.setFont("DejaVuSans", 11)
    for line in summary_lines:
        c.drawString(20*mm, y, line)
        y -= 7*mm
    if errors:
        y -= 5*mm
        c.setFont("DejaVuSans-Bold", 11)
        c.drawString(20*mm, y, "Ошибки и критические значения:")
        y -= 7*mm
        c.setFont("DejaVuSans", 11)
        for line in errors:
            c.drawString(22*mm, y, line)
            y -= 6*mm
    y -= 5*mm
    c.setFont("DejaVuSans-Bold", 11)
    c.drawString(20*mm, y, "Динамика по дням:")
    y -= 7*mm
    c.setFont("DejaVuSans", 11)
    # Новый способ: используем TextObject для переноса строк по ширине и перехода на новую страницу
    text_obj = c.beginText(22*mm, y)
    text_obj.setFont("DejaVuSans", 11)
    for line in clean_markdown(gpt_text).splitlines():
        for subline in split_text_by_width(line, "DejaVuSans", 11, max_width_mm=170):
            if text_obj.getY() < 30*mm:
                c.drawText(text_obj)
                c.showPage()
                y = height - 20*mm
                text_obj = c.beginText(22*mm, y)
                text_obj.setFont("DejaVuSans", 11)
            text_obj.textLine(subline)
    c.drawText(text_obj)
    y = text_obj.getY()  # обновляем y после вывода текста
    if y < 30*mm:
        c.showPage()
        y = height - 20*mm
    # Вставить график
    if buf_graph:
        y -= 10*mm
        try:
            c.drawImage(ImageReader(buf_graph), 20*mm, y-60*mm, width=170*mm, height=50*mm, preserveAspectRatio=True)
            y -= 60*mm
        except Exception:
            pass
    c.save()
    pdf_buf.seek(0)
    return pdf_buf

async def send_report(update, context, date_from, period_label, query=None):
    user_id = update.effective_user.id

    now = datetime.now()
    with SessionLocal() as s:
        entries = (
            s.query(Entry)
            .filter(Entry.telegram_id == user_id)
            .filter(Entry.event_time >= date_from)
            .order_by(Entry.event_time)
            .all()
        )
    if not entries:
        text = f"Нет записей за {period_label}."
        if query:
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return
    # --- Сводка ---
    sugars = [e.sugar_before for e in entries if e.sugar_before is not None]
    doses = [e.dose for e in entries if e.dose is not None]
    carbs = [e.carbs_g for e in entries if e.carbs_g is not None]
    avg_sugar = round(sum(sugars) / len(sugars), 1) if sugars else "-"
    avg_dose = round(sum(doses) / len(doses), 1) if doses else "-"
    avg_carbs = round(sum(carbs) / len(carbs), 1) if carbs else "-"
    summary_lines = [
        f"• Всего записей: {len(entries)}",
        f"• Средний сахар: {avg_sugar} ммоль/л",
        f"• Средняя доза: {avg_dose} Ед",
        f"• Средние углеводы: {avg_carbs} г"
    ]
    # --- Ошибки и критические значения ---
    errors = []
    for e in entries:
        if (e.sugar_before is not None and e.sugar_before < 0) or (e.carbs_g is not None and e.carbs_g < 0) or (e.dose is not None and e.dose < 0):
            errors.append(f"{e.event_time.strftime('%d.%m %H:%M')}: отрицательные значения в записи")
        if e.sugar_before is not None and e.sugar_before >= 14:
            errors.append(f"⚠️ {e.event_time.strftime('%d.%m %H:%M')}: сахар {e.sugar_before} ммоль/л — критически высокий!")
    # --- Динамика по дням ---
    from collections import defaultdict
    day_stats = defaultdict(list)
    for e in entries:
        day = e.event_time.strftime('%d.%m')
        day_stats[day].append(e)
    day_lines = []
    for day, day_entries in sorted(day_stats.items()):
        sugars_day = [e.sugar_before for e in day_entries if e.sugar_before is not None]
        doses_day = [e.dose for e in day_entries if e.dose is not None]
        carbs_day = [e.carbs_g for e in day_entries if e.carbs_g is not None]
        min_sugar = min(sugars_day) if sugars_day else "-"
        max_sugar = max(sugars_day) if sugars_day else "-"
        sum_dose = sum(doses_day) if doses_day else "-"
        sum_carbs = sum(carbs_day) if carbs_day else "-"
        day_lines.append(f"{day}: сахар {min_sugar}–{max_sugar}, доза {sum_dose}, углеводы {sum_carbs}")
    # --- График ---
    plt.figure(figsize=(7, 3))
    times = [e.event_time for e in entries if e.sugar_before is not None]
    sugars_plot = [e.sugar_before for e in entries if e.sugar_before is not None]
    plt.plot(times, sugars_plot, marker='o', label='Сахар (ммоль/л)')
    plt.title(f'Динамика сахара за {period_label}')
    plt.xlabel('Дата')
    plt.ylabel('Сахар, ммоль/л')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    # --- Формируем summary для GPT ---
    summary = []
    for e in entries:
        when = e.event_time.strftime('%Y-%m-%d %H:%M')
        summary.append(
            f"{when}: сахар={e.sugar_before or '-'} ммоль/л, углеводы={e.carbs_g or '-'} г, ХЕ={e.xe or '-'}, доза={e.dose or '-'}"
        )
    summary_text = "\n".join(summary)
    gpt_prompt = (
        f"Вот сводка по дневнику диабетика за {period_label}:\n"
        + "\n".join(summary_lines) + "\n"
        + ("\nОшибки и критические значения:\n" + "\n".join(errors) if errors else "")
        + "\nДинамика по дням:\n" + "\n".join(day_lines) + "\n"
        + "\nПодробные записи:\n" + summary_text + "\n\n"
        "Сделай анализ, дай советы по контролю сахара и питанию, укажи возможные проблемы."
    )
    from gpt_client import client
    gpt_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "Ты — медицинский ассистент для диабетиков."},
                  {"role": "user", "content": gpt_prompt}],
        temperature=0.2,
        max_tokens=600
    )
    gpt_text = gpt_response.choices[0].message.content.strip()
    report_msg = (
        f"<b>📈 Отчёт за {period_label}</b>\n\n"
        + "\n".join(summary_lines) + "\n\n"
        + ("<b>Ошибки и критические значения:</b>\n" + "\n".join(errors) + "\n\n" if errors else "")
        + "<b>Динамика по дням:</b>\n" + "\n".join(day_lines) + "\n\n"
        + f"<b>Анализ и рекомендации:</b>\n{gpt_text}\n\n"
        "ℹ️ Для подробного разбора покажите этот отчёт врачу."
    )
    if query:
        await query.edit_message_text(report_msg, parse_mode="HTML")
        await query.message.reply_photo(buf, caption="График сахара за период")
        pdf_buf = generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf)
        await query.message.reply_document(pdf_buf, filename='diabetes_report.pdf', caption='PDF-отчёт для врача')
    else:
        await update.message.reply_text(report_msg, parse_mode="HTML")
        await update.message.reply_photo(buf, caption="График сахара за период")
        pdf_buf = generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf)
        await update.message.reply_document(pdf_buf, filename='diabetes_report.pdf', caption='PDF-отчёт для врача')

# 1. Константы для онбординга
ONB_HELLO, ONB_PROFILE_ICR, ONB_PROFILE_CF, ONB_PROFILE_TARGET, ONB_DEMO = range(20, 25)

# 2. Обработчики онбординга
async def onb_hello(update, context):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Начать", callback_data="onb:start")]])
    await update.message.reply_text(
        "👋 Привет! Я *Diabet Buddy* — твой ассистент по углеводам и инсулину.\n"
        "Давай настроим профиль — это займёт <1 мин.",
        reply_markup=kb, parse_mode="Markdown")
    return ONB_HELLO

async def onb_begin(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.edit_text(
        "📋 *Шаг 1 из 2*  \n"
        "Введи *ИКХ* — сколько граммов углеводов «покрывает» 1 ед. инсулина.\n"
        "_Например: 12_", parse_mode="Markdown")
    return ONB_PROFILE_ICR

async def onb_icr(update, context):
    try:
        context.user_data['icr'] = float(update.message.text)
        await update.message.reply_text(
            "📋 *Шаг 1 из 2*\nТеперь введи *КЧ* — на сколько ммоль/л 1 ед. инсулина снижает сахар.\n_Например: 2_",
            parse_mode="Markdown")
        return ONB_PROFILE_CF
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return ONB_PROFILE_ICR

async def onb_cf(update, context):
    try:
        context.user_data['cf'] = float(update.message.text)
        await update.message.reply_text(
            "📋 *Шаг 1 из 2*\nТеперь введи *целевой сахар* (ммоль/л).\n_Например: 6_",
            parse_mode="Markdown")
        return ONB_PROFILE_TARGET
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return ONB_PROFILE_CF

async def onb_target(update, context):
    try:
        context.user_data['target'] = float(update.message.text)
        session = SessionLocal()
        user_id = update.effective_user.id
        prof = session.get(Profile, user_id)
        if not prof:
            prof = Profile(telegram_id=user_id)
            session.add(prof)
        prof.icr = context.user_data['icr']
        prof.cf = context.user_data['cf']
        prof.target_bg = context.user_data['target']
        session.commit()
        session.close()
        img_path = "assets/demo.jpg"
        with open(img_path, "rb") as f:
            await update.message.reply_photo(
                f, caption="📸 *Шаг 2 из 2*\nНажми «Оценить», и я покажу, как это работает!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔍 Оценить", callback_data="onb:demo")]]
                )
            )
        return ONB_DEMO
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число.")
        return ONB_PROFILE_TARGET

async def onb_demo_run(update, context):
    await update.callback_query.answer()
    context.user_data["__file_path"] = "assets/demo.jpg"
    context.user_data["demo"] = True
    await photo_handler(update, context, demo=True)
    await update.callback_query.message.reply_text(
        '✨ *Что я умею*\n'
        '• 📷  Распознавать еду с фото\n'
        '• ✍️  Понимать свободный текст ( "5 ХЕ, сахар 9" )\n'
        '• 💉  Считать дозу по твоему профилю\n'
        '• 📊  Показывать историю и графики\n'
        '• ⏰  Напоминать о замере сахара',
        parse_mode="Markdown",
        reply_markup=menu_keyboard
    )
    return ConversationHandler.END

# 4. ConversationHandler для онбординга
onboarding_conv = ConversationHandler(
    entry_points=[CommandHandler("start", onb_hello)],
    states={
        ONB_HELLO: [CallbackQueryHandler(onb_begin, pattern="^onb:start$")],
        ONB_PROFILE_ICR: [MessageHandler(filters.TEXT & ~filters.COMMAND, onb_icr)],
        ONB_PROFILE_CF: [MessageHandler(filters.TEXT & ~filters.COMMAND, onb_cf)],
        ONB_PROFILE_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, onb_target)],
        ONB_DEMO: [CallbackQueryHandler(onb_demo_run, pattern="^onb:demo$")],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler)
    ],
)

sugar_conv = ConversationHandler(
    entry_points=[
        CommandHandler("sugar", sugar_start),
    ],
    states={
        SUGAR_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sugar_val)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler)
    ],
)

photo_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.PHOTO,          photo_handler),
        MessageHandler(filters.Document.IMAGE, doc_handler),
    ],
    states={
        PHOTO_SUGAR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, photo_sugar_handler)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler)
    ],
)

dose_conv = ConversationHandler(
    entry_points=[
        CommandHandler("dose", dose_start),
        MessageHandler(filters.Regex("^💉 Доза инсулина$"), dose_start),
    ],
    states={
        DOSE_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, dose_method_choice)],
        DOSE_XE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, dose_xe_handler)],
        DOSE_SUGAR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, dose_sugar)],
        DOSE_CARBS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, dose_carbs)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler)
    ],
)

profile_conv = ConversationHandler(
    entry_points=[
        CommandHandler("profile", profile_start),
        MessageHandler(filters.Regex(r"^🔄 Изменить профиль$"), profile_start)
    ],
    states={
        PROFILE_ICR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_icr)],
        PROFILE_CF:     [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_cf)],
        PROFILE_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_target)],
    },
    fallbacks=[
        CommandHandler("cancel", profile_cancel),
        MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler)
    ],
)



def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(onboarding_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CommandHandler("reset", reset_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(MessageHandler(filters.Regex("^📄 Мой профиль$"), profile_view))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 История$"), history_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^❓ Мой сахар$"), sugar_start))
    app.add_handler(sugar_conv)
    app.add_handler(photo_conv)
    app.add_handler(profile_conv)
    app.add_handler(dose_conv)
    app.add_handler(MessageHandler(filters.Regex(r"^📷 Фото еды$"), photo_request))
    app.add_handler(CommandHandler("report", report_handler))
    app.add_handler(MessageHandler(filters.Regex("^📈 Отчёт$"), report_handler))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freeform_handler))
    app.add_handler(CommandHandler("help", help_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
