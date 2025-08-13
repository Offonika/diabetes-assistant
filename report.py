import asyncio
import io
import logging
import os
import re
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth

DEFAULT_FONT = "Helvetica"
DEFAULT_FONT_BOLD = "Helvetica-Bold"

# Fallback font with Cyrillic support
FALLBACK_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
FALLBACK_FONT_BOLD_PATH = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"


def _register_fonts() -> tuple[str, str]:
    """Register DejaVu fonts if available, else return defaults.

    The font paths can be overridden via ``FONT_PATH`` and ``FONT_BOLD_PATH``
    environment variables. If the files are not found, built-in Helvetica
    fonts are used as a fallback.
    """
    regular_path = os.getenv(
        "FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    bold_path = os.getenv(
        "FONT_BOLD_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )

    if os.path.exists(regular_path) and os.path.exists(bold_path):
        pdfmetrics.registerFont(TTFont("DejaVuSans", regular_path))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
        return "DejaVuSans", "DejaVuSans-Bold"

    fallback_regular = os.getenv("FALLBACK_FONT_PATH", FALLBACK_FONT_PATH)
    fallback_bold = os.getenv("FALLBACK_FONT_BOLD_PATH", FALLBACK_FONT_BOLD_PATH)
    if os.path.exists(fallback_regular) and os.path.exists(fallback_bold):
        pdfmetrics.registerFont(TTFont("NotoSans", fallback_regular))
        pdfmetrics.registerFont(TTFont("NotoSans-Bold", fallback_bold))
        logging.warning(
            "DejaVu fonts not found; using fallback fonts %s and %s",
            "NotoSans",
            "NotoSans-Bold",
        )
        return "NotoSans", "NotoSans-Bold"

    logging.warning(
        "DejaVu and Noto fonts not found; using default fonts %s and %s",
        DEFAULT_FONT,
        DEFAULT_FONT_BOLD,
    )
    return DEFAULT_FONT, DEFAULT_FONT_BOLD


FONT_REGULAR, FONT_BOLD = _register_fonts()

from db_access import get_entries_since
from gpt_client import client


def clean_markdown(text: str) -> str:
    """Remove basic Markdown formatting"""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\*\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


def split_text_by_width(text: str, font_name: str, font_size: int, max_width_mm: int):
    """Split a line so it does not exceed max_width_mm."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        width = stringWidth(test, font_name, font_size) / mm
        if width > max_width_mm and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf_graph):
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    y = height - 20 * mm
    c.setFont(FONT_BOLD, 16)
    c.drawString(20 * mm, y, "Отчёт по диабетическому дневнику")
    y -= 12 * mm
    c.setFont(FONT_REGULAR, 11)
    for line in summary_lines:
        c.drawString(20 * mm, y, line)
        y -= 7 * mm
    if errors:
        y -= 5 * mm
        c.setFont(FONT_BOLD, 11)
        c.drawString(20 * mm, y, "Ошибки и критические значения:")
        y -= 7 * mm
        c.setFont(FONT_REGULAR, 11)
        for line in errors:
            c.drawString(22 * mm, y, line)
            y -= 6 * mm
    y -= 5 * mm
    c.setFont(FONT_BOLD, 11)
    c.drawString(20 * mm, y, "Динамика по дням:")
    y -= 7 * mm
    c.setFont(FONT_REGULAR, 11)
    text_obj = c.beginText(22 * mm, y)
    text_obj.setFont(FONT_REGULAR, 11)
    for line in clean_markdown(gpt_text).splitlines():
        for sub in split_text_by_width(line, FONT_REGULAR, 11, max_width_mm=170):
            if text_obj.getY() < 30 * mm:
                c.drawText(text_obj)
                c.showPage()
                y = height - 20 * mm
                text_obj = c.beginText(22 * mm, y)
                text_obj.setFont(FONT_REGULAR, 11)
            text_obj.textLine(sub)
    c.drawText(text_obj)
    y = text_obj.getY()
    if y < 30 * mm:
        c.showPage()
        y = height - 20 * mm
    if buf_graph:
        y -= 10 * mm
        try:
            c.drawImage(
                ImageReader(buf_graph),
                20 * mm,
                y - 60 * mm,
                width=170 * mm,
                height=50 * mm,
                preserveAspectRatio=True,
            )
            y -= 60 * mm
        except Exception:
            logging.exception("Failed to render graph in PDF report")
    c.save()
    pdf_buf.seek(0)
    return pdf_buf


async def send_report(update, context, date_from, period_label, query=None):
    user_id = update.effective_user.id
    entries = get_entries_since(user_id, date_from)
    if not entries:
        text = f"Нет записей за {period_label}."
        if query:
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

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
        f"• Средние углеводы: {avg_carbs} г",
    ]
    errors = []
    for e in entries:
        if (e.sugar_before is not None and e.sugar_before < 0) or (
            e.carbs_g is not None and e.carbs_g < 0
        ) or (e.dose is not None and e.dose < 0):
            errors.append(
                f"{e.event_time.strftime('%d.%m %H:%M')}: отрицательные значения в записи"
            )
        if e.sugar_before is not None and e.sugar_before >= 14:
            errors.append(
                f"⚠️ {e.event_time.strftime('%d.%m %H:%M')}: сахар {e.sugar_before} ммоль/л — критически высокий!"
            )

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
        day_lines.append(
            f"{day}: сахар {min_sugar}–{max_sugar}, доза {sum_dose}, углеводы {sum_carbs}"
        )

    fig, ax = plt.subplots(figsize=(7, 3))
    times = [e.event_time for e in entries if e.sugar_before is not None]
    sugars_plot = [e.sugar_before for e in entries if e.sugar_before is not None]
    ax.plot(times, sugars_plot, marker="o", label="Сахар (ммоль/л)")
    ax.set_title(f"Динамика сахара за {period_label}")
    ax.set_xlabel("Дата")
    ax.set_ylabel("Сахар, ммоль/л")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    plt.close(fig)

    summary = []
    for e in entries:
        when = e.event_time.strftime('%Y-%m-%d %H:%M')
        summary.append(
            f"{when}: сахар={e.sugar_before or '-'} ммоль/л, углеводы={e.carbs_g or '-'} г, ХЕ={e.xe or '-'}, доза={e.dose or '-'}"
        )
    summary_text = "\n".join(summary)
    gpt_prompt = (
        f"Вот сводка по дневнику диабетика за {period_label}:\n"
        + "\n".join(summary_lines)
        + "\n"
        + ("\nОшибки и критические значения:\n" + "\n".join(errors) if errors else "")
        + "\nДинамика по дням:\n"
        + "\n".join(day_lines)
        + "\n"
        + "\nПодробные записи:\n"
        + summary_text
        + "\n\n"
        + "Сделай анализ, дай советы по контролю сахара и питанию, укажи возможные проблемы."
    )

    try:
        gpt_response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты — медицинский ассистент для диабетиков."},
                {"role": "user", "content": gpt_prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        gpt_text = gpt_response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Report generation failed: {e}")
        gpt_text = "Не удалось получить рекомендации."

    report_msg = (
        f"<b>📈 Отчёт за {period_label}</b>\n\n"
        + "\n".join(summary_lines)
        + "\n\n"
        + ("<b>Ошибки и критические значения:</b>\n" + "\n".join(errors) + "\n\n" if errors else "")
        + "<b>Динамика по дням:</b>\n" + "\n".join(day_lines) + "\n\n"
        + f"<b>Анализ и рекомендации:</b>\n{gpt_text}\n\n"
        + "ℹ️ Для подробного разбора покажите этот отчёт врачу."
    )

    if query:
        await query.edit_message_text(report_msg, parse_mode="HTML")
        await query.message.reply_photo(buf, caption="График сахара за период")
        buf.seek(0)
        pdf_buf = generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf)
        await query.message.reply_document(
            pdf_buf, filename='diabetes_report.pdf', caption='PDF-отчёт для врача'
        )
    else:
        await update.message.reply_text(report_msg, parse_mode="HTML")
        await update.message.reply_photo(buf, caption="График сахара за период")
        buf.seek(0)
        pdf_buf = generate_pdf_report(summary_lines, errors, day_lines, gpt_text, buf)
        await update.message.reply_document(
            pdf_buf, filename='diabetes_report.pdf', caption='PDF-отчёт для врача'
        )
