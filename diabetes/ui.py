# file: diabetes/ui.py
"""
UI-компоненты бота «Diabet Buddy».
Здесь живут все клавиатуры (Reply и Inline) и их генераторы.
Импортируйте объекты напрямую:

    from diabetes.ui import menu_keyboard, dose_keyboard, confirm_keyboard
"""

from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

__all__ = ("menu_keyboard", "dose_keyboard", "confirm_keyboard")

# ─────────────── Reply-клавиатуры (отображаются на экране чата) ───────────────

menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📷 Фото еды"), KeyboardButton("❓ Мой сахар")],
        [KeyboardButton("💉 Доза инсулина"), KeyboardButton("📊 История")],
        [KeyboardButton("📈 Отчёт"), KeyboardButton("📄 Мой профиль")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Выберите действие…",
)

dose_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton("↩️ Назад")]],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Введите значение или вернитесь назад…",
)

# ─────────────── Inline-клавиатуры (обрабатываются callback-ами) ───────────────


def confirm_keyboard(back_cb: str | None = None) -> InlineKeyboardMarkup:
    """
    Стандартная клавиатура подтверждения:
        ✅ Подтвердить | ✏️ Исправить | ❌ Отмена | 🔙 Назад (опц.)

    Parameters
    ----------
    back_cb : str | None
        callback_data, которое отправит кнопка «Назад».
        Если None, кнопка не добавляется.
    """
    rows = [
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_ok"),
            InlineKeyboardButton("✏️ Исправить",  callback_data="confirm_edit"),
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data="confirm_cancel"),
        ],
    ]
    if back_cb:
        rows.append(
            [InlineKeyboardButton("🔙 Назад", callback_data=back_cb)]
        )
    return InlineKeyboardMarkup(rows)
