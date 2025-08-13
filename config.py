# config.py
import os
from dotenv import load_dotenv

load_dotenv()  # Загрузка переменных из .env файла

TELEGRAM_TOKEN      = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY      = os.getenv('OPENAI_API_KEY')
OPENAI_ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

DB_HOST     = os.getenv('DB_HOST', 'localhost')
DB_PORT     = os.getenv('DB_PORT', '5432')
DB_NAME     = os.getenv('DB_NAME', 'diabetes_bot')
DB_USER     = os.getenv('DB_USER', 'diabetes_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

OPENAI_PROXY = os.getenv('OPENAI_PROXY')


def validate_tokens() -> None:
    """Ensure that all required API tokens are provided."""
    missing = [
        name
        for name, value in [
            ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
            ("OPENAI_API_KEY", OPENAI_API_KEY),
            ("OPENAI_ASSISTANT_ID", OPENAI_ASSISTANT_ID),
            ("DB_HOST", os.getenv("DB_HOST")),
            ("DB_PORT", os.getenv("DB_PORT")),
            ("DB_NAME", os.getenv("DB_NAME")),
            ("DB_USER", os.getenv("DB_USER")),
            ("DB_PASSWORD", os.getenv("DB_PASSWORD")),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
