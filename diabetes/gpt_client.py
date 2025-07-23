# gpt_client.py

import openai
import os
import logging
from diabetes.config import OPENAI_API_KEY, OPENAI_ASSISTANT_ID, OPENAI_PROXY

# --- Только здесь прописываем прокси ---
# Если переменная OPENAI_PROXY указана, выставляем HTTP(S)_PROXY
if OPENAI_PROXY:
    os.environ["HTTP_PROXY"] = OPENAI_PROXY
    os.environ["HTTPS_PROXY"] = OPENAI_PROXY

client = openai.OpenAI(api_key=OPENAI_API_KEY)

logging.info("[OpenAI] Using assistant: %s", OPENAI_ASSISTANT_ID)


def create_thread() -> str:
    """Создаём пустой thread (ассистент задаётся позже, в runs.create)."""
    thread = client.beta.threads.create()
    return thread.id

def send_message(thread_id: str, content: str | None = None, image_path: str | None = None):
    """
    Отправляет текст или (изображение + текст) в thread
    и запускает run с ассистентом.  Возвращает объект run.
    """
    # 1. Подготовка контента
    if image_path:
        try:
            with open(image_path, "rb") as f:
                file = client.files.create(file=f, purpose="vision")
            logging.info("[OpenAI] Uploaded image %s, file_id=%s", image_path, file.id)
            content_block = [
                {"type": "image_file", "image_file": {"file_id": file.id}},
                {"type": "text",       "text": content or "Что изображено на фото?"}
            ]
        except Exception as e:
            logging.exception("[OpenAI] Failed to upload %s: %s", image_path, e)
            raise
    else:
        content_block = content

    # 2. Создаём сообщение в thread
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=content_block
    )

    # 3. Запускаем ассистента
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=OPENAI_ASSISTANT_ID
    )
    logging.debug("[OpenAI] Run %s started (thread %s)", run.id, thread_id)
    return run