# Diabetes Bot

## Описание
Телеграм-бот для помощи диабетикам 2 типа:
- распознаёт еду по фото через GPT-4o
- рассчитывает углеводы и ХЕ
- (в будущем) подсказывает дозу инсулина
- ведёт простой дневник

## Установка и запуск

1. Клонируйте репозиторий:
   ```bash
   git clone <repo_url>
   cd diabetes-assistant
   ```
2. Создайте и активируйте виртуальное окружение:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Создайте файл `.env` со следующими переменными:
   ```bash
   TELEGRAM_TOKEN=YOUR_TELEGRAM_TOKEN
   OPENAI_API_KEY=YOUR_OPENAI_KEY
   OPENAI_ASSISTANT_ID=YOUR_ASSISTANT_ID
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=diabetes_bot
   DB_USER=diabetes_user
   DB_PASSWORD=your_password
   ```
5. Инициализируйте базу данных:
   ```bash
   alembic upgrade head
   ```
6. Запустите бота:
   ```bash
   python bot.py
   ```

## Тесты

Тесты запускаются с помощью `pytest`:
```bash
pytest
```
