# file: webapp/server.py
"""Minimal FastAPI application serving the SPA and API endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from json import JSONDecodeError
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

app = FastAPI()
app.router.redirect_slashes = True
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()
# The SPA source lives in ``webapp/ui`` and builds to ``webapp/ui/dist``.
# Serve the compiled ``dist`` directory so that the application serves the
# latest build output under the ``/ui`` path.
UI_DIR = (BASE_DIR / "ui" / "dist").resolve()
if not UI_DIR.exists():
    logger.error(
        "UI build directory %s not found. Run `npm run build` in webapp/ui",
        UI_DIR,
    )
    raise RuntimeError("UI build not found; run npm run build in webapp/ui")

# store data files outside the served static directory
STORAGE_DIR = (BASE_DIR.parent / "webapp_data").resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
REMINDERS_FILE = STORAGE_DIR / "reminders.json"
TIMEZONE_FILE = STORAGE_DIR / "timezone.txt"
reminders_lock = asyncio.Lock()
# ---------- API ----------
class ProfileSchema(BaseModel):
    icr: float
    cf: float
    target: float
    low: float
    high: float

class ReminderSchema(BaseModel):
    id: int | None = None
    type: str | None = None
    value: str | None = None
    text: str | None = None

async def _write_timezone(value: str) -> None:
    def _write() -> None:
        with TIMEZONE_FILE.open("w", encoding="utf-8") as fh:
            fh.write(value)
    try:
        await asyncio.to_thread(_write)
    except OSError:
        logger.exception("failed to write timezone")
        raise HTTPException(status_code=500, detail="storage error")

async def _read_reminders() -> dict[int, dict]:
    def _read() -> dict[int, dict]:
        if not REMINDERS_FILE.exists():
            return {}
        try:
            data = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        except JSONDecodeError:
            logger.warning("invalid reminders JSON; resetting storage")
            try:
                REMINDERS_FILE.write_text("{}", encoding="utf-8")
            except OSError as exc:
                logger.exception("failed to reset reminders file")
                raise HTTPException(status_code=500, detail="storage error") from exc
            return {}
        except OSError as exc:
            logger.exception("failed to read reminders")
            raise HTTPException(status_code=500, detail="storage error") from exc
        if not isinstance(data, dict):
            logger.warning("reminders JSON is not a dict; resetting storage")
            try:
                REMINDERS_FILE.write_text("{}", encoding="utf-8")
            except OSError as exc:
                logger.exception("failed to reset reminders file")
                raise HTTPException(status_code=500, detail="storage error") from exc
            return {}
        try:
            return {int(k): v for k, v in data.items()}
        except ValueError:
            logger.warning("non-numeric reminder key; resetting storage")
            try:
                REMINDERS_FILE.write_text("{}", encoding="utf-8")
            except OSError as exc:
                logger.exception("failed to reset reminders file")
                raise HTTPException(status_code=500, detail="storage error") from exc
            return {}
    return await asyncio.to_thread(_read)


async def _write_reminders(store: dict[int, dict]) -> None:
    def _write() -> None:
        with REMINDERS_FILE.open("w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False)

    try:
        await asyncio.to_thread(_write)
    except OSError as exc:
        logger.exception("failed to write reminders")
        raise HTTPException(status_code=500, detail="storage error") from exc

@app.post("/api/timezone")
async def timezone_post(request: Request) -> dict:
    try:
        data = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid data format")
    tz = data.get("tz")
    if not isinstance(tz, str) or not tz:
        raise HTTPException(status_code=400, detail="invalid data")
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="invalid timezone") from exc
    await _write_timezone(tz)
    return {"status": "ok"}

@app.post("/api/profile")
async def save_profile(request: Request) -> dict:
    try:
        data = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid data format")
    try:
        ProfileSchema(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid data") from exc
    return {"status": "ok"}

@app.get("/api/reminders")
async def reminders_get(id: int | None = None) -> dict | list[dict]:
    async with reminders_lock:
        store = await _read_reminders()
    if id is None:
        return list(store.values())
    return store.get(id, {})

@app.post("/api/reminders")
async def reminders_post(request: Request) -> dict:
    try:
        data = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON format") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid data format")
    try:
        reminder = ReminderSchema(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid data") from exc
    async with reminders_lock:
        store = await _read_reminders()
        for item in store.values():
            if "rem_type" in item and "type" not in item:
                item["type"] = item.pop("rem_type")
        rid = reminder.id if reminder.id is not None else max(store.keys(), default=0) + 1
        if rid < 0:
            raise HTTPException(status_code=400, detail="id must be non-negative")
        store[rid] = {**reminder.model_dump(exclude_none=True), "id": rid}
        await _write_reminders(store)
    return {"status": "ok", "id": rid}

# ---------- Совместимость для старых относительных путей из UI ----------
# ВАЖНО: эти маршруты должны быть ДО обработчиков SPA,
# иначе их перехватит UI.

@app.post("/ui/api/timezone")
async def _compat_ui_timezone(request: Request) -> dict:
    # просто проксируем на существующую логику
    return await timezone_post(request)
# -----------------------------------------------------------------------

# ---------- UI (Vite SPA) ----------
# ДОЛЖНО идти ПОСЛЕ совместимых маршрутов!


def serve_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})


if UI_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=UI_DIR / "assets"), name="ui-assets")


@app.get("/ui", include_in_schema=False)
@app.head("/ui", include_in_schema=False)
async def ui_root() -> FileResponse:
    return serve_index()


@app.get("/ui/", include_in_schema=False)
@app.head("/ui/", include_in_schema=False)
async def ui_root_slash() -> FileResponse:
    return serve_index()


@app.get("/ui/{full_path:path}", include_in_schema=False)
async def ui_files(full_path: str) -> FileResponse:
    target = UI_DIR / full_path
    if target.exists():
        return FileResponse(target)
    return serve_index()

# -----------------------------------

# редирект корня на SPA
@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui")

# статические файлы для UI и вспомогательных страниц
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static-files",
)

# корневая статика — файлы из webapp/ доступны по прямым путям
app.mount("/", StaticFiles(directory=str(BASE_DIR)), name="static-root")

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    uvicorn.run("webapp.server:app", host="0.0.0.0", port=8000, workers=workers)
