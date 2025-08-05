import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from diabetes.db import Base, User, Reminder, ReminderLog
import diabetes.reminder_handlers as handlers
from diabetes.common_handlers import commit_session


class DummyMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class DummyQuery:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or DummyMessage()

    async def answer(self):
        pass


class DummyBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


class DummyJob:
    def __init__(self, callback, data, name):
        self.callback = callback
        self.data = data
        self.name = name
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class DummyJobQueue:
    def __init__(self):
        self.jobs = []

    def run_daily(self, callback, time, data=None, name=None):
        self.jobs.append(DummyJob(callback, data, name))

    def run_repeating(self, callback, interval, data=None, name=None):
        self.jobs.append(DummyJob(callback, data, name))

    def run_once(self, callback, when, data=None, name=None):
        self.jobs.append(DummyJob(callback, data, name))

    def get_jobs_by_name(self, name):
        return [j for j in self.jobs if j.name == name]


@pytest.mark.asyncio
async def test_add_reminder_flow(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    handlers.SessionLocal = TestSession
    handlers.commit_session = commit_session

    with TestSession() as session:
        session.add(User(telegram_id=1, thread_id="t"))
        session.commit()

    job_queue = DummyJobQueue()
    context = SimpleNamespace(user_data={}, job_queue=job_queue)

    msg_start = DummyMessage()
    update_start = SimpleNamespace(message=msg_start, effective_user=SimpleNamespace(id=1))
    state = await handlers.add_reminder(update_start, context)
    assert state == handlers.ADDREM_TYPE
    assert "Выберите тип" in msg_start.replies[0]

    query = DummyQuery("remtype:sugar", message=msg_start)
    update_type = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
    state2 = await handlers.add_reminder_type(update_type, context)
    assert state2 == handlers.ADDREM_VALUE
    assert "Введите время" in msg_start.replies[-1]

    msg_val = DummyMessage("23:00")
    update_val = SimpleNamespace(message=msg_val, effective_user=SimpleNamespace(id=1))
    result = await handlers.add_reminder_value(update_val, context)
    assert result == handlers.ConversationHandler.END
    assert msg_val.replies[0].startswith("✅ Напоминание сохранено")

    with TestSession() as session:
        rem = session.query(Reminder).one()
        rid = rem.id
    assert job_queue.jobs[0].name == f"reminder_{rid}"

    msg_del = DummyMessage()
    update_del = SimpleNamespace(message=msg_del, effective_user=SimpleNamespace(id=1))
    context_del = SimpleNamespace(args=[str(rid)], job_queue=job_queue)
    await handlers.delete_reminder(update_del, context_del)
    with TestSession() as session:
        assert session.query(Reminder).count() == 0


@pytest.mark.asyncio
async def test_add_reminder_invalid_input(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    handlers.SessionLocal = TestSession
    handlers.commit_session = commit_session

    with TestSession() as session:
        session.add(User(telegram_id=1, thread_id="t"))
        session.commit()

    job_queue = DummyJobQueue()
    context = SimpleNamespace(user_data={}, job_queue=job_queue)

    msg_start = DummyMessage()
    update_start = SimpleNamespace(message=msg_start, effective_user=SimpleNamespace(id=1))
    await handlers.add_reminder(update_start, context)

    query = DummyQuery("remtype:sugar", message=msg_start)
    update_type = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
    await handlers.add_reminder_type(update_type, context)

    msg_bad = DummyMessage("abc")
    update_bad = SimpleNamespace(message=msg_bad, effective_user=SimpleNamespace(id=1))
    state = await handlers.add_reminder_value(update_bad, context)
    assert state == handlers.ADDREM_VALUE
    assert msg_bad.replies == ["Интервал должен быть числом."]

    msg_good = DummyMessage("5")
    update_good = SimpleNamespace(message=msg_good, effective_user=SimpleNamespace(id=1))
    result = await handlers.add_reminder_value(update_good, context)
    assert result == handlers.ConversationHandler.END

    with TestSession() as session:
        rem = session.query(Reminder).one()
        assert rem.interval_hours == 5


@pytest.mark.asyncio
async def test_add_reminder_cancel(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    handlers.SessionLocal = TestSession
    handlers.commit_session = commit_session

    with TestSession() as session:
        session.add(User(telegram_id=1, thread_id="t"))
        session.commit()

    context = SimpleNamespace(user_data={}, job_queue=DummyJobQueue())
    msg_start = DummyMessage()
    update_start = SimpleNamespace(message=msg_start, effective_user=SimpleNamespace(id=1))
    await handlers.add_reminder(update_start, context)

    msg_cancel = DummyMessage()
    update_cancel = SimpleNamespace(message=msg_cancel, effective_user=SimpleNamespace(id=1))
    result = await handlers.add_reminder_cancel(update_cancel, context)
    assert result == handlers.ConversationHandler.END
    assert msg_cancel.replies == ["❌ Напоминание отменено."]


@pytest.mark.asyncio
async def test_trigger_job_logs(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    handlers.SessionLocal = TestSession
    handlers.commit_session = commit_session

    with TestSession() as session:
        session.add(User(telegram_id=1, thread_id="t"))
        session.add(Reminder(id=1, telegram_id=1, type="sugar", time="23:00"))
        session.commit()

    job_queue = DummyJobQueue()
    with TestSession() as session:
        rem_db = session.get(Reminder, 1)
        rem = Reminder(
            id=rem_db.id,
            telegram_id=rem_db.telegram_id,
            type=rem_db.type,
            time=rem_db.time,
        )
    handlers.schedule_reminder(rem, job_queue)
    bot = DummyBot()
    context = SimpleNamespace(
        bot=bot,
        job=SimpleNamespace(data={"reminder_id": 1, "chat_id": 1}),
        job_queue=job_queue,
    )
    await handlers.reminder_job(context)
    assert bot.messages[0][1].startswith("Замерить сахар")
    with TestSession() as session:
        log = session.query(ReminderLog).first()
        assert log.action == "trigger"
