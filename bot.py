from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_TOKEN
from db import init_db
from bot.startup import setup
from bot.conversations import (
    onboarding_conv,
    sugar_conv,
    photo_conv,
    dose_conv,
    profile_conv,
)
from bot.handlers import (
    start,
    menu_handler,
    reset_handler,
    history_handler,
    profile_command,
    profile_view,
    sugar_start,
    photo_request,
    report_handler,
    callback_router,
    freeform_handler,
    help_handler,
)


logger = setup()


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a notification to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла непредвиденная ошибка. Попробуйте еще раз позже.",
            )
        except Exception:  # pragma: no cover - best effort to notify
            logger.exception("Failed to send error message to user")

def main() -> None:
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_error_handler(error_handler)
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
