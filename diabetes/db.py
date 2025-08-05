# db.py  ← полный и единственный источник моделей


from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String,
    Float, Text, TIMESTAMP, ForeignKey, Boolean, func,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from diabetes.config import DB_HOST, DB_PORT, DB_NAME, DB_USER


# ────────────────── подключение к Postgres ──────────────────
engine = None
SessionLocal = sessionmaker(autoflush=False, autocommit=False)
Base = declarative_base()


# ───────────────────────── модели ────────────────────────────
class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, index=True)
    thread_id = Column(String, nullable=False)
    onboarding_complete = Column(Boolean, default=False)
    plan = Column(String, default="free")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Profile(Base):
    __tablename__ = "profiles"

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        primary_key=True,
    )
    icr = Column(Float)  # г углеводов на 1 Е инсулина
    cf = Column(Float)  # коэффициент коррекции
    target_bg = Column(Float)  # целевой сахар
    low_threshold = Column(Float)  # нижний порог сахара
    high_threshold = Column(Float)  # верхний порог сахара
    sos_contact = Column(String)  # контакт для экстренной связи
    sos_alerts_enabled = Column(Boolean, default=True)
    user = relationship("User")


class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"))

    event_time = Column(TIMESTAMP(timezone=True), nullable=False)  # время приёма
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())

    photo_path = Column(String)
    carbs_g = Column(Float)
    xe = Column(Float)
    sugar_before = Column(Float)
    dose = Column(Float)
    gpt_summary = Column(Text)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    sugar = Column(Float)
    type = Column(String)
    ts = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved = Column(Boolean, default=False)
    user = relationship("User")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    type = Column(String, nullable=False)
    time = Column(String)  # HH:MM format for daily reminders
    interval_hours = Column(Integer)  # for repeating reminders
    minutes_after = Column(Integer)  # for after-meal reminders
    is_enabled = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    user = relationship("User")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id"))
    telegram_id = Column(BigInteger)
    action = Column(String)  # triggered, snoozed, cancelled
    event_time = Column(TIMESTAMP(timezone=True), server_default=func.now())


# ────────────────────── инициализация ────────────────────────
def init_db() -> None:
    """Создать таблицы, если их ещё нет (для локального запуска)."""
    from diabetes import config

    if not config.DB_PASSWORD:
        raise ValueError("DB_PASSWORD environment variable must be set")
    database_url = URL.create(
        "postgresql",
        username=DB_USER,
        password=config.DB_PASSWORD,
        host=DB_HOST,
        port=int(DB_PORT),
        database=DB_NAME,
    )

    global engine
    if engine is None or engine.url != database_url:
        if engine is not None:
            engine.dispose()
        engine = create_engine(database_url)
        SessionLocal.configure(bind=engine)

    Base.metadata.create_all(bind=engine)
