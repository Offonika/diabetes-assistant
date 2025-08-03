import os

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
)

from diabetes.common_handlers import register_handlers, callback_router, start_command


def test_register_handlers_attaches_expected_handlers(monkeypatch):
    os.environ.setdefault("OPENAI_API_KEY", "test")
    os.environ.setdefault("OPENAI_ASSISTANT_ID", "asst_test")
    import diabetes.openai_utils as openai_utils  # noqa: F401
    from diabetes import dose_handlers, profile_handlers, reporting_handlers

    app = ApplicationBuilder().token("TESTTOKEN").build()
    register_handlers(app)

    handlers = app.handlers[0]
    callbacks = [getattr(h, "callback", None) for h in handlers]

    assert start_command in callbacks
    assert profile_handlers.profile_command in callbacks
    assert dose_handlers.freeform_handler in callbacks
    assert dose_handlers.photo_handler in callbacks
    assert dose_handlers.doc_handler in callbacks
    assert dose_handlers.prompt_photo in callbacks
    assert dose_handlers.prompt_sugar in callbacks
    assert callback_router in callbacks
    assert reporting_handlers.report_period_callback in callbacks
    assert profile_handlers.profile_view in callbacks
    assert reporting_handlers.report_request in callbacks
    assert reporting_handlers.history_view in callbacks

    start_cmd = [
        h for h in handlers if isinstance(h, CommandHandler) and h.callback is start_command
    ]
    assert start_cmd and "start" in start_cmd[0].commands

    profile_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is profile_handlers.profile_command
    ]
    assert profile_cmd and "profile" in profile_cmd[0].commands

    conv_handlers = [h for h in handlers if isinstance(h, ConversationHandler)]
    assert dose_handlers.dose_conv in conv_handlers
    assert dose_handlers.sugar_conv in conv_handlers
    conv_cmds = [
        ep
        for ep in dose_handlers.dose_conv.entry_points
        if isinstance(ep, CommandHandler)
    ]
    assert conv_cmds and "dose" in conv_cmds[0].commands
    sugar_conv_cmds = [
        ep
        for ep in dose_handlers.sugar_conv.entry_points
        if isinstance(ep, CommandHandler)
    ]
    assert sugar_conv_cmds and "sugar" in sugar_conv_cmds[0].commands

    text_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is dose_handlers.freeform_handler
    ]
    assert text_handlers

    photo_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is dose_handlers.photo_handler
    ]
    assert photo_handlers

    doc_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is dose_handlers.doc_handler
    ]
    assert doc_handlers

    photo_prompt_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is dose_handlers.photo_prompt
    ]
    assert photo_prompt_handlers

    sugar_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is dose_handlers.sugar_start
    ]
    assert sugar_cmd and "sugar" in sugar_cmd[0].commands

    profile_view_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is profile_handlers.profile_view
    ]
    assert profile_view_handlers

    report_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is reporting_handlers.report_request
    ]
    assert report_handlers

    report_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is reporting_handlers.report_request
    ]
    assert report_cmd and "report" in report_cmd[0].commands

    history_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is reporting_handlers.history_view
    ]
    assert history_handlers

    history_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is reporting_handlers.history_view
    ]
    assert history_cmd and "history" in history_cmd[0].commands

    cb_handlers = [
        h
        for h in handlers
        if isinstance(h, CallbackQueryHandler) and h.callback is callback_router
    ]
    assert cb_handlers
    report_cb_handlers = [
        h
        for h in handlers
        if isinstance(h, CallbackQueryHandler)
        and h.callback is reporting_handlers.report_period_callback
    ]
    assert report_cb_handlers
