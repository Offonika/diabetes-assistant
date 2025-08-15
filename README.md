# Diabetes Bot

## Описание
Телеграм-бот для помощи диабетикам 2 типа:
- распознаёт еду по фото через GPT-4o
- рассчитывает углеводы и ХЕ
- (в будущем) подсказывает дозу инсулина
- ведёт простой дневник

## Установка

1. Клонировать репозиторий:
   ```bash
   git clone <repo_url>
   cd diabetes_bot
   ```
2. Скопируйте файл `.env.example` в `.env` и заполните значения переменных.

### Переменные окружения

- `TELEGRAM_TOKEN` – токен вашего Telegram-бота
- `OPENAI_API_KEY` – ключ API OpenAI
- `OPENAI_ASSISTANT_ID` – ID ассистента OpenAI
- `OPENAI_PROXY` – опциональный прокси для запросов к OpenAI
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` – настройки базы данных
- `WEBAPP_URL` – базовый адрес Telegram WebApp
- `WEBAPP_VERSION` – версия WebApp для пробивания кеша (git SHA или timestamp)

3. Установите зависимости из файла `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
4. Запустите миграции базы данных:
   ```bash
   alembic upgrade head
   ```

## Запуск

- Телеграм-бот:
  ```bash
  python bot.py
  ```
- REST API:
  ```bash
  uvicorn api:app --reload
  ```

### Обновление WebApp

Перед деплоем соберите статические файлы:

```bash
npm run build:clean && npm run build
```

Telegram кэширует URL веб‑приложения без параметров. После каждого
релиза обновляйте значение `WEBAPP_VERSION`, чтобы к адресу WebApp
добавлялся параметр `?v=…` и Telegram загружал свежую версию. Обычно
достаточно указать короткий git SHA:

```bash
export WEBAPP_VERSION=$(git rev-parse --short HEAD)
```

## REST API

### POST `/v1/ai/diagnose`

Возвращает протокол лечения для переданного диагноза.

**Пример запроса:**

```bash
curl -X POST http://localhost:8000/v1/ai/diagnose \
  -H 'Content-Type: application/json' \
  -d '{"diagnosis": "диабет 2 типа"}'
```

**Успешный ответ:**

```json
{ "protocol": "standard protocol" }
```

Если диагноз не найден, возвращается ошибка `404 Protocol not found`.

## Примеры использования

После запуска бота отправьте фото еды в личный чат – бот вернёт карточку с
подсчётом углеводов и кнопку «Протокол».

Для получения протокола из стороннего приложения используйте REST API
(`POST /v1/ai/diagnose`).

Чтобы сохранить напоминание, отправьте боту фразу вида
«Напомни принять таблетку в 21:00» — в указанное время бот пришлёт сообщение.

Подробнее см. сценарии из
[tests/manual_test_cases.md](tests/manual_test_cases.md).

## Напоминания

Бот поддерживает создание напоминаний через обычный текст. Каждый
запрос сохраняется в базе и будет отправлен пользователю в указанное время.

**Пример:**

```
Напомни измерить сахар в 09:00
```

После обработки вы получите подтверждение, а в 09:00 бот пришлёт сообщение
с текстом напоминания.

## Тестирование и линтинг

Перед запуском тестов убедитесь, что установлены все зависимости из
`requirements.txt`. Важно, чтобы были установлены базовые пакеты,
такие как `fastapi` и другие зависимости, используемые приложением.

1. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   # зависимости для тестов, включая pytest и pytest-asyncio
   pip install -r requirements-test.txt
   ```
2. Запустите проверки:
   ```bash
   flake8
   pytest
   ```
