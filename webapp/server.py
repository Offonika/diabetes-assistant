# file: webapp/server.py
"""Minimal FastAPI application serving the SPA and API endpoints."""
from __future__ import annotations

import asyncio
import os
import json
import logging
from json import JSONDecodeError
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

app = FastAPI()
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent
REMINDERS_FILE = BASE_DIR / "reminders.json"
TIMEZONE_FILE = BASE_DIR / "timezone.txt"

# ---------- NEW: UI (lovable) mount ----------
UI_DIR = BASE_DIR / "ui"
if UI_DIR.exists():
    # Статика ассетов Vite (css/js/chunks)
    app.mount("/ui/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="ui-assets")

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/", include_in_schema=False)
    async def ui_index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    # History fallback: любые вложенные маршруты SPA → index.html
    @app.get("/ui/{path:path}", include_in_schema=False)
    async def ui_catch_all(path: str) -> HTMLResponse:
        idx = UI_DIR / "index.html"
        if idx.exists():
            return HTMLResponse(idx.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="UI not found")
# ---------- /NEW ----------


async def _write_timezone(value: str) -> None:
    """Persist timezone value to a text file."""

    def _write() -> None:
        with TIMEZONE_FILE.open("w", encoding="utf-8") as fh:
            fh.write(value)

    await asyncio.to_thread(_write)


async def _read_reminders() -> dict[int, dict]:
    """Read reminders from JSON file."""

    def _read() -> dict[int, dict]:
        if REMINDERS_FILE.exists():
            try:
                with REMINDERS_FILE.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except JSONDecodeError:
                logger.warning("Failed to decode %s; backing up and resetting", REMINDERS_FILE)
                backup = REMINDERS_FILE.with_suffix(REMINDERS_FILE.suffix + ".bak")
                try:
                    REMINDERS_FILE.replace(backup)
                except OSError:
                    REMINDERS_FILE.unlink(missing_ok=True)
                return {}
            return {int(k): v for k, v in data.items()}
        return {}

    return await asyncio.to_thread(_read)


async def _write_reminders(data: dict[int, dict]) -> None:
    """Write reminders to JSON file."""

    def _write() -> None:
        with REMINDERS_FILE.open("w", encoding="utf-8") as fh:
            json.dump({int(k): v for k, v in data.items()}, fh)

    await asyncio.to_thread(_write)


class ProfileSchema(BaseModel):
    """Schema for profile data."""

    icr: float
    cf: float
    target: float
    low: float
    high: float


class ReminderSchema(BaseModel):
    """Schema for reminder data."""

    id: int | None = None
    type: str | None = None
    value: str | None = None
    text: str | None = None


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    """Redirect the root URL to the SPA at /ui."""
    return RedirectResponse(url="/ui")


@app.post("/api/timezone")
async def timezone_post(request: Request) -> dict:
    """Persist timezone submitted by the client."""
    try:
        data = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    tz = data.get("tz")
    if not isinstance(tz, str) or not tz:
        raise HTTPException(status_code=400, detail="invalid data")
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="invalid timezone") from exc
    await _write_timezone(tz)
    return {"status": "ok"}


@app.post("/profile")
async def save_profile(request: Request) -> dict:  # pragma: no cover - simple
    """Accept submitted profile data."""
    try:
        data = await request.json()
    except JSONDecodeError as exc:  # pragma: no cover - validation
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    try:
        ProfileSchema(**data)
    except ValidationError as exc:  # pragma: no cover - validation
        raise HTTPException(status_code=400, detail="invalid data") from exc
    return {"status": "ok"}


@app.get("/reminders")
async def reminders_get(id: int | None = None) -> dict | list[dict]:  # pragma: no cover - simple
    """Return stored reminders from JSON file."""
    store = await _read_reminders()
    if id is None:
        return list(store.values())
    return store.get(id, {})


@app.post("/reminders")
async def reminders_post(request: Request) -> dict:  # pragma: no cover - simple
    """Save reminder data to JSON store."""
    try:
        data = await request.json()
    except JSONDecodeError as exc:  # pragma: no cover - validation
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    try:
        reminder = ReminderSchema(**data)
    except ValidationError as exc:  # pragma: no cover - validation
        raise HTTPException(status_code=400, detail="invalid data") from exc

    store = await _read_reminders()
    # migrate old reminders using "rem_type" to unified "type" key
    for item in store.values():
        if "rem_type" in item and "type" not in item:
            item["type"] = item.pop("rem_type")
    rid = reminder.id if reminder.id is not None else max(store.keys(), default=0) + 1
    if rid < 0:
        raise HTTPException(status_code=400, detail="id must be non-negative")
    store[rid] = {**reminder.model_dump(exclude_none=True), "id": rid}
    await _write_reminders(store)
    return {"status": "ok", "id": rid}


if __name__ == "__main__":  # pragma: no cover - manual start
    import uvicorn

    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    uvicorn.run(
        "webapp.server:app",
        host="0.0.0.0",
        port=8000,
        workers=workers,
    )
