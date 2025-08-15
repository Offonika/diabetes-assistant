import logging
from config import validate_tokens
from gpt_command_parser import init_command_parser


def setup() -> logging.Logger:
    """Configure logging and validate tokens."""
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[
            logging.FileHandler("bot.log"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logger = logging.getLogger("bot")

    validate_tokens()
    init_command_parser()

    for name in ("httpcore", "httpx", "telegram", "telegram.ext"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.info("=== Bot started ===")
    logger.info("Логгер настроен, бот запускается")
    return logger
