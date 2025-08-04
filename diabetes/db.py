# db.py  ← полный и единственный источник моделей


from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String,
    Float, Text, TIMESTAMP, ForeignKey, Boolean, func,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from diabetes.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


# ────────────────── подключение к Postgres ──────────────────
DATABASE_URL = URL.create(
    "postgresql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ───────────────────────── модели ────────────────────────────
class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, index=True)
    thread_id = Column(String, nullable=False)
    onboarding_complete = Column(Boolean, default=False)
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


# ────────────────────── инициализация ────────────────────────
def init_db() -> None:
    """Создать таблицы, если их ещё нет (для локального запуска)."""
    if not DB_PASSWORD:
        raise ValueError("DB_PASSWORD environment variable must be set")
    Base.metadata.create_all(bind=engine)
