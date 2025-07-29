import os, json, logging
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_PROXY

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
    "\"fields\":{\"carbs_g\":60,\"dose\":6}}\n"
)


async def parse_command(text: str) -> dict | None:
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text}
            ],
            temperature=0,
            max_tokens=256
        )
        content = response.choices[0].message.content.strip()
        logging.info(f"GPT parse response: {content}")
        return json.loads(content)
    except Exception as e:
        logging.error(f"Command parsing failed: {e}")
        return None
