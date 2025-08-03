"""Handlers for insulin dose calculations and related utilities."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
from pathlib import Path

from openai import OpenAIError
from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes

from diabetes.db import SessionLocal, User, Entry
from diabetes.functions import extract_nutrition_info
from diabetes.gpt_client import create_thread, send_message, _get_client
from diabetes.gpt_command_parser import parse_command
from diabetes.ui import menu_keyboard, confirm_keyboard
from .common_handlers import commit_session
from .reporting_handlers import send_report


logger = logging.getLogger(__name__)


def _cleanup_file(path: str | None) -> None:
    """Remove a temporary image file if it exists."""
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - log only
        logger.warning("Failed to delete file %s: %s", path, exc)


def _sanitize(text: str, max_len: int = 200) -> str:
    """Strip control chars and truncate for safe logging."""
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(text))
    return cleaned[:max_len]


PHOTO_SUGAR = 7
WAITING_GPT_FLAG = "waiting_gpt_response"


async def freeform_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle freeform text commands for adding diary entries."""
    raw_text = update.message.text.strip()
    user_id = update.effective_user.id
    logging.info("FREEFORM raw='%s'  user=%s", raw_text, user_id)

    if context.user_data.get("awaiting_report_date"):
        try:
            date_from = datetime.datetime.strptime(
                update.message.text.strip(), "%Y-%m-%d"
            ).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            await update.message.reply_text("❗ Некорректная дата. Используйте формат YYYY-MM-DD.")
            return
        await send_report(update, context, date_from, "указанный период")
        context.user_data.pop("awaiting_report_date", None)
        return

    if context.user_data.get("pending_entry") is not None and context.user_data.get("edit_id") is None:
        entry = context.user_data["pending_entry"]
        text = update.message.text.lower().strip()
        if re.fullmatch(r"-?\d+(?:[.,]\d+)?", text) and entry.get("sugar_before") is None:
            try:
                sugar = float(text.replace(",", "."))
            except ValueError:
                await update.message.reply_text(
                    "Некорректное числовое значение."
                )
                return
            entry["sugar_before"] = sugar
            await update.message.reply_text(
                f"Сохранить уровень сахара {sugar} ммоль/л в дневник?",
                reply_markup=confirm_keyboard(),
            )
            return
        parts = dict(
            re.findall(r"(\w+)\s*=\s*(-?\d+(?:[.,]\d+)?)(?=\s|$)", text)
        )
        if not parts:
            await update.message.reply_text("Не вижу ни одного поля для изменения.")
            return
        if "xe" in parts:
            try:
                entry["xe"] = float(parts["xe"].replace(",", "."))
            except ValueError:
                await update.message.reply_text("Некорректное числовое значение.")
                return
        if "carbs" in parts:
            try:
                entry["carbs_g"] = float(parts["carbs"].replace(",", "."))
            except ValueError:
                await update.message.reply_text("Некорректное числовое значение.")
                return
        if "dose" in parts:
            try:
                entry["dose"] = float(parts["dose"].replace(",", "."))
            except ValueError:
                await update.message.reply_text("Некорректное числовое значение.")
                return
        if "сахар" in parts or "sugar" in parts:
            sugar_value = parts.get("сахар") or parts["sugar"]
            try:
                entry["sugar_before"] = float(sugar_value.replace(",", "."))
            except ValueError:
                await update.message.reply_text("Некорректное числовое значение.")
                return
        carbs = entry.get("carbs_g")
        xe = entry.get("xe")
        sugar = entry.get("sugar_before")
        dose = entry.get("dose")
        xe_info = f", ХЕ: {xe}" if xe is not None else ""

        await update.message.reply_text(
            f"💉 Расчёт завершён:\n"
            f"• Углеводы: {carbs} г{xe_info}\n"
            f"• Сахар: {sugar} ммоль/л\n"
            f"• Ваша доза: {dose} Ед\n\n"
            f"Сохранить это в дневник?",
            reply_markup=confirm_keyboard(),
        )
        return
    if "edit_id" in context.user_data:
        text = update.message.text.lower()
        parts = dict(
            re.findall(r"(\w+)\s*=\s*(-?\d+(?:[.,]\d+)?)(?=\s|$)", text)
        )
        if not parts:
            await update.message.reply_text("Не вижу ни одного поля для изменения.")
            return
        with SessionLocal() as session:
            entry = session.get(Entry, context.user_data["edit_id"])
            if not entry:
                await update.message.reply_text("Запись уже удалена.")
                context.user_data.pop("edit_id")
                return
            if "xe" in parts:
                try:
                    entry.xe = float(parts["xe"].replace(",", "."))
                except ValueError:
                    await update.message.reply_text(
                        "Некорректное числовое значение."
                    )
                    return
            if "carbs" in parts:
                try:
                    entry.carbs_g = float(parts["carbs"].replace(",", "."))
                except ValueError:
                    await update.message.reply_text(
                        "Некорректное числовое значение."
                    )
                    return
            if "dose" in parts:
                try:
                    entry.dose = float(parts["dose"].replace(",", "."))
                except ValueError:
                    await update.message.reply_text(
                        "Некорректное числовое значение."
                    )
                    return
            if "сахар" in parts or "sugar" in parts:
                sugar_value = parts.get("сахар") or parts["sugar"]
                try:
                    entry.sugar_before = float(sugar_value.replace(",", "."))
                except ValueError:
                    await update.message.reply_text(
                        "Некорректное числовое значение."
                    )
                    return
            entry.updated_at = datetime.datetime.now(datetime.timezone.utc)
            if not commit_session(session):
                await update.message.reply_text("⚠️ Не удалось обновить запись.")
                return
        context.user_data.pop("edit_id")
        await update.message.reply_text("✅ Запись обновлена!")
        return

    parsed = await parse_command(raw_text)
    logging.info("FREEFORM parsed=%s", parsed)
    if not parsed or parsed.get("action") != "add_entry":
        await chat_with_gpt(update, context)
        return

    fields = parsed["fields"]
    entry_date = parsed.get("entry_date")
    time_str = parsed.get("time")

    if entry_date:
        try:
            event_dt = datetime.datetime.fromisoformat(entry_date)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=datetime.timezone.utc)
            else:
                event_dt = event_dt.astimezone(datetime.timezone.utc)
        except ValueError:
            event_dt = datetime.datetime.now(datetime.timezone.utc)
    elif time_str:
        try:
            hh, mm = map(int, time_str.split(":"))
            today = datetime.datetime.now(datetime.timezone.utc).date()
            event_dt = datetime.datetime.combine(
                today, datetime.time(hh, mm), tzinfo=datetime.timezone.utc
            )
        except (ValueError, TypeError):
            await update.message.reply_text(
                "⏰ Неверный формат времени. Использую текущее время."
            )
            event_dt = datetime.datetime.now(datetime.timezone.utc)
    else:
        event_dt = datetime.datetime.now(datetime.timezone.utc)
    context.user_data.pop("pending_entry", None)
    context.user_data["pending_entry"] = {
        "telegram_id": user_id,
        "event_time": event_dt,
        "xe": fields.get("xe"),
        "carbs_g": fields.get("carbs_g"),
        "dose": fields.get("dose"),
        "sugar_before": fields.get("sugar_before"),
        "photo_path": None,
    }

    xe_val = fields.get("xe")
    carbs_val = fields.get("carbs_g")
    dose_val = fields.get("dose")
    sugar_val = fields.get("sugar_before")
    date_str = event_dt.strftime("%d.%m %H:%M")
    xe_part = f"{xe_val} ХЕ" if xe_val is not None else ""
    carb_part = f"{carbs_val:.0f} г углеводов" if carbs_val is not None else ""
    dose_part = f"Инсулин: {dose_val} ед" if dose_val is not None else ""
    sugar_part = f"Сахар: {sugar_val} ммоль/л" if sugar_val is not None else ""
    lines = "  \n- ".join(filter(None, [xe_part or carb_part, dose_part, sugar_part]))

    reply = f"💉 Расчёт завершён:\n\n{date_str}  \n- {lines}\n\nСохранить это в дневник?"
    await update.message.reply_text(reply, reply_markup=confirm_keyboard())
    return ConversationHandler.END


async def chat_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Placeholder GPT chat handler."""
    await update.message.reply_text("🗨️ Чат с GPT временно недоступен.")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, demo: bool = False):
    """Process food photos and trigger nutrition analysis."""
    message = update.message or update.callback_query.message
    user_id = update.effective_user.id

    if context.user_data.get(WAITING_GPT_FLAG):
        await message.reply_text("⏳ Уже обрабатываю фото, подождите…")
        return ConversationHandler.END
    context.user_data[WAITING_GPT_FLAG] = True

    file_path = context.user_data.pop("__file_path", None)
    if not file_path:
        try:
            photo = update.message.photo[-1]
        except (AttributeError, IndexError, TypeError):
            await message.reply_text("❗ Файл не распознан как изображение.")
            context.user_data.pop(WAITING_GPT_FLAG, None)
            return ConversationHandler.END

        os.makedirs("photos", exist_ok=True)
        file_path = f"photos/{user_id}_{photo.file_unique_id}.jpg"
        try:
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(file_path)
        except OSError as exc:
            logging.exception("[PHOTO] Failed to save photo: %s", exc)
            await message.reply_text("⚠️ Не удалось сохранить фото. Попробуйте ещё раз.")
            context.user_data.pop(WAITING_GPT_FLAG, None)
            _cleanup_file(file_path)
            return ConversationHandler.END

    logging.info("[PHOTO] Saved to %s", file_path)

    try:
        thread_id = context.user_data.get("thread_id")
        if not thread_id:
            with SessionLocal() as session:
                user = session.get(User, user_id)
                if user:
                    thread_id = user.thread_id
                else:
                    thread_id = create_thread()
                    session.add(User(telegram_id=user_id, thread_id=thread_id))
                    if not commit_session(session):
                        await message.reply_text(
                            "⚠️ Не удалось сохранить данные пользователя."
                        )
                        _cleanup_file(file_path)
                        return ConversationHandler.END
            context.user_data["thread_id"] = thread_id

        run = send_message(
            thread_id=thread_id,
            content=(
                "Определи количество углеводов и ХЕ на фото блюда. "
                "Используй формат из системных инструкций ассистента."
            ),
            image_path=file_path,
            keep_image=True,
        )
        await message.reply_text("🔍 Анализирую фото (это займёт 5‑10 с)…")

        max_attempts = 15
        for _ in range(max_attempts):
            if run.status in ("completed", "failed", "cancelled", "expired"):
                break
            await asyncio.sleep(2)
            run = _get_client().beta.threads.runs.retrieve(
                thread_id=run.thread_id,
                run_id=run.id,
            )

        if run.status not in ("completed", "failed", "cancelled", "expired"):
            logger.warning("[VISION][TIMEOUT] run.id=%s", run.id)
            await message.reply_text("⚠️ Время ожидания Vision истекло. Попробуйте позже.")
            _cleanup_file(file_path)
            return ConversationHandler.END

        if run.status != "completed":
            logging.error("[VISION][RUN_FAILED] run.status=%s", run.status)
            await message.reply_text("⚠️ Vision не смог обработать фото.")
            _cleanup_file(file_path)
            return ConversationHandler.END

        messages = _get_client().beta.threads.messages.list(thread_id=run.thread_id)
        for m in messages.data:
            content = _sanitize(m.content)
            logger.debug("[VISION][MSG] m.role=%s; content=%s", m.role, content)

        vision_text = next(
            (m.content[0].text.value for m in messages.data if m.role == "assistant" and m.content),
            "",
        )
        logger.debug(
            "[VISION][RESPONSE] Ответ Vision для %s:\n%s",
            file_path,
            _sanitize(vision_text),
        )

        carbs_g, xe = extract_nutrition_info(vision_text)
        if carbs_g is None and xe is None:
            logger.debug(
                "[VISION][NO_PARSE] Ответ ассистента: %r для файла: %s",
                _sanitize(vision_text),
                file_path,
            )
            await message.reply_text(
                "⚠️ Не смог разобрать углеводы на фото.\n\n"
                f"Вот полный ответ Vision:\n<pre>{vision_text}</pre>\n"
                "Введите /dose и укажите их вручную.",
                parse_mode="HTML",
                reply_markup=menu_keyboard,
            )
            _cleanup_file(file_path)
            return ConversationHandler.END

        context.user_data.update({"carbs": carbs_g, "xe": xe, "photo_path": file_path})
        await message.reply_text(
            f"🍽️ На фото:\n{vision_text}\n\n"
            "Введите текущий сахар (ммоль/л) — и я рассчитаю дозу инсулина.",
            reply_markup=menu_keyboard,
        )
        return PHOTO_SUGAR

    except OSError as exc:
        logging.exception("[PHOTO] File processing error: %s", exc)
        await message.reply_text("⚠️ Ошибка при обработке файла изображения. Попробуйте ещё раз.")
        _cleanup_file(file_path)
        return ConversationHandler.END
    except OpenAIError as exc:
        logging.exception("[PHOTO] Vision API error: %s", exc)
        await message.reply_text("⚠️ Vision не смог обработать фото. Попробуйте ещё раз.")
        _cleanup_file(file_path)
        return ConversationHandler.END
    except ValueError as exc:
        logging.exception("[PHOTO] Parsing error: %s", exc)
        await message.reply_text("⚠️ Не удалось распознать фото. Попробуйте ещё раз.")
        _cleanup_file(file_path)
        return ConversationHandler.END
    except Exception as exc:  # pragma: no cover - unexpected
        logging.exception("[PHOTO] Unexpected error: %s", exc)
        raise
    finally:
        context.user_data.pop(WAITING_GPT_FLAG, None)


async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle images sent as documents."""
    document = update.message.document
    if not document:
        return ConversationHandler.END

    mime_type = document.mime_type
    if not mime_type or not mime_type.startswith("image/"):
        return ConversationHandler.END

    user_id = update.effective_user.id
    ext = Path(document.file_name).suffix or ".jpg"
    path = f"photos/{user_id}_{document.file_unique_id}{ext}"
    os.makedirs("photos", exist_ok=True)

    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(path)

    context.user_data["__file_path"] = path
    update.message.photo = []
    return await photo_handler(update, context)


__all__ = [
    "PHOTO_SUGAR",
    "WAITING_GPT_FLAG",
    "freeform_handler",
    "photo_handler",
    "doc_handler",
    "ConversationHandler",
]
