import importlib


def load_handlers(monkeypatch, url: str, version: str):
    monkeypatch.setenv("WEBAPP_URL", url)
    monkeypatch.setenv("WEBAPP_VERSION", version)
    # Required for module import
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_ASSISTANT_ID", "assistant")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "db")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "pass")
    import bot.handlers as handlers
    return importlib.reload(handlers)


def test_build_webapp_url_without_query(monkeypatch):
    handlers = load_handlers(monkeypatch, "https://example.com/app", "123")
    assert handlers.build_webapp_url() == "https://example.com/app?v=123"


def test_build_webapp_url_with_query(monkeypatch):
    handlers = load_handlers(
        monkeypatch, "https://example.com/app?foo=bar", "456"
    )
    assert handlers.build_webapp_url() == "https://example.com/app?foo=bar&v=456"
