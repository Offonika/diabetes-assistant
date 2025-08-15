import os, json, logging, asyncio
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_PROXY, validate_tokens


client: OpenAI | None = None


def init_command_parser() -> None:
    """Initialize OpenAI client and validate required tokens."""
    global client

    validate_tokens()

    # 1️⃣ СРАЗУ ставим переменные окружения — до создания клиента!
    if OPENAI_PROXY is not None:
        os.environ["HTTP_PROXY"] = OPENAI_PROXY
        os.environ["HTTPS_PROXY"] = OPENAI_PROXY

    # 2️⃣ Создаём обычный клиент OpenAI — без extra‑аргументов,
    #    он возьмёт прокси из env автоматически.
    client = OpenAI(api_key=OPENAI_API_KEY)

# gpt_command_parser.py  ← замените весь блок SYSTEM_PROMPT
SYSTEM_PROMPT = (
    "Ты — парсер дневника диабетика.\n"
    "Из свободного текста пользователя извлеки команду и верни СТРОГО ОДИН "
    "JSON‑объект без пояснений.\n\n"

    "Формат:\n"
    "{\n"
    '  "action": "add_entry" | "update_entry" | "delete_entry" | '
    '"update_profile" | "set_reminder" | "get_stats" | "get_day_summary",\n'
    '  "entry_date": "YYYY-MM-DDTHH:MM:SS",      // ⇦ указывай ТОЛЬКО если есть полная дата\n'
    '  "time": "HH:MM",                          // ⇦ если в сообщении было лишь время\n'
    '  "message": "text",                       // ⇦ для set_reminder\n'
    '  "fields": { ... }                         // xe, carbs_g, dose, sugar_before и пр.\n'
    "}\n\n"

    "📌  Правила временных полей:\n"
    "•  Если пользователь назвал только время (напр. «в 9:00») — заполни поле "
    "\"time\", а «entry_date» НЕ добавляй.\n"
    "•  Слова «сегодня», «вчера» игнорируй — бот сам подставит дату.\n"
    "•  Если в сообщении указаны день/месяц/год — запиши их в "
    "\"entry_date\" в формате ISO 8601 (YYYY‑MM‑DDTHH:MM:SS) и НЕ пиши поле "
    "\"time\".\n"
    "•  Часы и минуты всегда с ведущими нулями (09:00).\n\n"

    "Пример 1 (только время):\n"
    "  {\"action\":\"add_entry\",\"time\":\"09:00\","
    "\"fields\":{\"xe\":5,\"dose\":10,\"sugar_before\":15}}\n"
    "Пример 2 (полная дата):\n"
    "  {\"action\":\"add_entry\",\"entry_date\":\"2025-05-04T20:00:00\","
    "\"fields\":{\"carbs_g\":60,\"dose\":6}}\n",
    "Пример 3 (напоминание):\n",
    "  {\"action\":\"set_reminder\",\"time\":\"09:00\",\"message\":\"измерить сахар\"}\n",
)


async def parse_command(text: str) -> dict | None:
    """Parse user's free-form text into a structured command.

    The OpenAI client call is executed in a background thread to avoid
    blocking the event loop.
    """
    if client is None:
        raise RuntimeError("gpt_command_parser is not initialized. Call init_command_parser()")

    try:
        # Run the blocking client call in a separate thread so the event loop
        # remains responsive.
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text}
            ],
            temperature=0,
            max_tokens=256
        )
        choices = getattr(response, "choices", [])
        if not choices:
            logging.error("OpenAI completion returned no choices")
            return None
        content = choices[0].message.content.strip()
        logging.info("GPT parse response: %s", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON response: {content}")
            return None
    except Exception as e:
        logging.error(f"Command parsing failed: {e}")
        return None
