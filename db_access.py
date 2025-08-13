import logging
from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict
from db import SessionLocal, Profile, Entry, Reminder


class EntryData(BaseModel):
    telegram_id: int
    event_time: datetime
    photo_path: str | None = None
    carbs_g: float | None = None
    xe: float | None = None
    sugar_before: float | None = None
    dose: float | None = None
    gpt_summary: str | None = None

    model_config = ConfigDict(extra="forbid")


def save_profile(user_id: int, icr: float, cf: float, target: float) -> None:
    with SessionLocal() as session:
        profile = session.get(Profile, user_id)
        if not profile:
            profile = Profile(telegram_id=user_id)
            session.add(profile)
        profile.icr = icr
        profile.cf = cf
        profile.target_bg = target
        session.commit()


def get_profile(user_id: int) -> Profile | None:
    with SessionLocal() as session:
        return session.get(Profile, user_id)


def add_entry(entry_data: dict) -> None:
    data = EntryData.model_validate(entry_data)
    with SessionLocal() as session:
        entry = Entry(**data.model_dump())
        session.add(entry)
        try:
            session.commit()
        except Exception:
            logging.exception("Failed to add entry")
            session.rollback()
            raise


def get_entries_since(user_id: int, date_from: datetime) -> List[Entry]:
    with SessionLocal() as s:
        return (
            s.query(Entry)
            .filter(Entry.telegram_id == user_id)
            .filter(Entry.event_time >= date_from)
            .order_by(Entry.event_time)
            .all()
        )


def add_reminder(user_id: int, time: datetime, message: str) -> Reminder:
    with SessionLocal() as session:
        reminder = Reminder(telegram_id=user_id, time=time, message=message)
        session.add(reminder)
        session.commit()
        session.refresh(reminder)
        return reminder


def get_reminders(user_id: int) -> List[Reminder]:
    with SessionLocal() as session:
        return (
            session.query(Reminder)
            .filter(Reminder.telegram_id == user_id)
            .order_by(Reminder.time)
            .all()
        )


def delete_reminder(reminder_id: int) -> None:
    with SessionLocal() as session:
        reminder = session.get(Reminder, reminder_id)
        if reminder:
            session.delete(reminder)
            session.commit()
