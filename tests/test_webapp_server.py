"""Tests for minimal FastAPI webapp used for reminders."""

from pathlib import Path
import logging

import pytest
from fastapi.testclient import TestClient

import webapp.server as server


client = TestClient(server.app)
INDEX_HTML = (server.UI_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def temp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a temporary JSON file for reminder storage in tests."""
    monkeypatch.setattr(server, "REMINDERS_FILE", tmp_path / "reminders.json")


def test_root_redirects_to_ui() -> None:
    """Root URL should redirect to the UI."""
    response = client.get("/", allow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/ui"


def test_static_files_available() -> None:
    """Timezone page and related assets should be served as static files."""
    assert client.get("/timezone.html").status_code == 200
    css_files = list((server.UI_DIR / "assets").glob("index-*.css"))
    assert css_files, "CSS build missing"
    css_name = css_files[0].name
    assert client.get(f"/ui/assets/{css_name}").status_code == 200
    assert client.get("/static/telegram-init.js").status_code == 200


def test_storage_files_inaccessible() -> None:
    """Internal storage files should not be exposed over HTTP."""
    assert client.get("/reminders.json").status_code == 404
    assert client.get("/timezone.txt").status_code == 404


@pytest.mark.parametrize("path", ["/ui/reminders", "/ui/unknown/path"])
def test_spa_routes_fall_back_to_index(path: str) -> None:
    """SPA routes should return the main index.html file."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_reminders_post_accepts_str_and_int_ids() -> None:
    """Posting reminders with string or int IDs stores numeric IDs."""
    response = client.post("/api/reminders", json={"id": 5, "text": "foo"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "id": 5}
    assert client.get("/api/reminders?id=5").json()["id"] == 5

    response = client.post("/api/reminders", json={"id": "6", "text": "bar"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "id": 6}
    assert client.get("/api/reminders?id=6").json()["id"] == 6

    # Auto-generate ID when not provided
    response = client.post("/api/reminders", json={"text": "baz"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "id": 7}


def test_profile_rejects_invalid_json() -> None:
    """Posting malformed JSON to /api/profile returns an error."""
    response = client.post(
        "/api/profile",
        content=b"{bad",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid JSON format"}


@pytest.mark.parametrize("rid", [-1, "-1"])
def test_reminders_post_rejects_negative_id(rid: int | str) -> None:
    """Posting a negative ID should return a validation error."""
    response = client.post("/api/reminders", json={"id": rid, "text": "oops"})
    assert response.status_code == 400
    assert client.get("/api/reminders").json() == []


def test_reminders_post_rejects_invalid_json() -> None:
    """Malformed JSON for /api/reminders should return an error and keep state empty."""
    response = client.post(
        "/api/reminders",
        content=b"{bad",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid JSON format"}
    assert client.get("/api/reminders").json() == []


def test_reminders_post_storage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(server.json, "dump", raise_oserror)
    response = client.post("/api/reminders", json={"text": "foo"})
    assert response.status_code == 500
    assert response.json() == {"detail": "storage error"}


def test_reminders_post_storage_error_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.REMINDERS_FILE.write_text("{}", encoding="utf-8")
    original_open = Path.open

    def raise_oserror(self, *args, **kwargs):  # noqa: ANN001
        if self == server.REMINDERS_FILE:
            raise OSError("disk full")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", raise_oserror)
    response = client.post("/api/reminders", json={"text": "foo"})
    assert response.status_code == 500
    assert response.json() == {"detail": "storage error"}


def test_reminders_get_storage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(self, *args, **kwargs):
        if self == server.REMINDERS_FILE:
            raise OSError("disk full")
        return original_open(self, *args, **kwargs)

    server.REMINDERS_FILE.write_text("{}", encoding="utf-8")
    original_open = Path.open
    monkeypatch.setattr(Path, "open", raise_oserror)
    response = client.get("/api/reminders")
    assert response.status_code == 500
    assert response.json() == {"detail": "storage error"}


def test_reminders_get_storage_error_on_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server.REMINDERS_FILE.write_text("{bad", encoding="utf-8")
    original_write_text = Path.write_text

    def raise_oserror(self, *args, **kwargs):  # noqa: ANN001
        if self == server.REMINDERS_FILE:
            raise OSError("disk full")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", raise_oserror)
    response = client.get("/api/reminders")
    assert response.status_code == 500
    assert response.json() == {"detail": "storage error"}


def test_reminders_get_handles_invalid_json(caplog: pytest.LogCaptureFixture) -> None:
    """Reading invalid JSON should log a warning and reset the file."""
    server.REMINDERS_FILE.write_text("{bad", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert client.get("/api/reminders").json() == []

    assert server.REMINDERS_FILE.read_text(encoding="utf-8") == "{}"
    assert "invalid reminders JSON" in caplog.text


def test_reminders_get_handles_non_numeric_keys(caplog: pytest.LogCaptureFixture) -> None:
    """Non-numeric reminder keys should log a warning and reset the file."""
    server.REMINDERS_FILE.write_text('{"foo": {"text": "bar"}}', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert client.get("/api/reminders").json() == []

    assert server.REMINDERS_FILE.read_text(encoding="utf-8") == "{}"
    assert "non-numeric reminder key" in caplog.text
