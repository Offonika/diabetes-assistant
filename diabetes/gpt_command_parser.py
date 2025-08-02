import asyncio
import os
import json
import logging
from openai import OpenAI, OpenAIError
from diabetes.config import OPENAI_API_KEY, OPENAI_PROXY

# 1️⃣ СРАЗУ ставим переменные окружения — до создания клиента!
if OPENAI_PROXY:
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


def _extract_first_json(text: str) -> dict | None:
    """Return the first JSON object found in *text* or ``None`` if absent."""
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        start = text.find("{", idx)
        if start == -1:
            return None
        try:
            obj, end = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            idx = start + 1


async def parse_command(text: str, timeout: float = 10) -> dict | None:
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0,
                max_tokens=256,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content.strip()
        logging.info(f"GPT raw response: {content}")
        parsed = _extract_first_json(content)
        if parsed is None:
            logging.error("No JSON object found in response")
            return None
        return parsed
    except asyncio.TimeoutError:
        logging.error("Command parsing timed out")
        return None
    except OpenAIError:
        logging.exception("Command parsing failed")
        return None
