"""Minimal FastAPI application serving the timezone detector page."""
from __future__ import annotations

import asyncio
import os
import json
from json import JSONDecodeError
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

app = FastAPI()
BASE_DIR = Path(__file__).parent
REMINDERS_FILE = BASE_DIR / "reminders.json"


async def _read_reminders() -> dict[int, dict]:
    """Read reminders from JSON file."""

    def _read() -> dict[int, dict]:
        if REMINDERS_FILE.exists():
            with REMINDERS_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
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


@app.get("/")
async def index() -> FileResponse:  # pragma: no cover - trivial
    """Return the main page."""
    return FileResponse(BASE_DIR / "index.html")


@app.get("/profile")
async def profile() -> FileResponse:  # pragma: no cover - trivial
    """Return the profile form page."""
    return FileResponse(BASE_DIR / "profile.html")


@app.post("/profile")
async def profile_post(request: Request) -> dict:  # pragma: no cover - simple
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


@app.get("/reminder")
async def reminder_form() -> FileResponse:  # pragma: no cover - trivial
    """Return the reminder form page."""
    return FileResponse(BASE_DIR / "reminder.html")


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
    rid = reminder.id if reminder.id is not None else max(store.keys(), default=0) + 1
    if rid < 0:
        raise HTTPException(status_code=400, detail="id must be non-negative")

    store[rid] = {
        "id": rid,
        "type": reminder.type,
        **reminder.model_dump(exclude={"id", "type"}, exclude_none=True),
    }
    _write_reminders(store)

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
