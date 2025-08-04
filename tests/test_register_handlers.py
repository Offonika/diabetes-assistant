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

    assert dose_handlers.freeform_handler in callbacks
    assert dose_handlers.photo_handler in callbacks
    assert dose_handlers.doc_handler in callbacks
    assert dose_handlers.prompt_photo in callbacks
    assert dose_handlers.prompt_sugar in callbacks
    assert dose_handlers.dose_cancel in callbacks
    assert callback_router in callbacks
    assert reporting_handlers.report_period_callback in callbacks
    assert profile_handlers.profile_view in callbacks
    assert profile_handlers.profile_back in callbacks
    assert reporting_handlers.report_request in callbacks
    assert reporting_handlers.history_view in callbacks
    assert dose_handlers.chat_with_gpt in callbacks

    onb_conv = [
        h
        for h in handlers
        if isinstance(h, ConversationHandler)
        and any(
            isinstance(ep, CommandHandler)
            and ep.callback is start_command
            and "start" in ep.commands
            for ep in h.entry_points
        )
    ]
    assert onb_conv


    conv_handlers = [h for h in handlers if isinstance(h, ConversationHandler)]
    assert dose_handlers.dose_conv in conv_handlers
    assert dose_handlers.sugar_conv in conv_handlers
    assert profile_handlers.profile_conv in conv_handlers
    assert onb_conv[0] in conv_handlers
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
    profile_conv_cmd = [
        ep
        for ep in profile_handlers.profile_conv.entry_points
        if isinstance(ep, CommandHandler)
        and ep.callback is profile_handlers.profile_command
        and "profile" in ep.commands
    ]
    assert profile_conv_cmd
    profile_conv_cb = [
        ep
        for ep in profile_handlers.profile_conv.entry_points
        if isinstance(ep, CallbackQueryHandler)
        and ep.callback is profile_handlers.profile_edit
    ]
    assert profile_conv_cb

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

    cancel_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is dose_handlers.dose_cancel
    ]
    assert cancel_cmd and "cancel" in cancel_cmd[0].commands

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

    gpt_cmd = [
        h
        for h in handlers
        if isinstance(h, CommandHandler) and h.callback is dose_handlers.chat_with_gpt
    ]
    assert gpt_cmd and "gpt" in gpt_cmd[0].commands

    history_handlers = [
        h
        for h in handlers
        if isinstance(h, MessageHandler) and h.callback is reporting_handlers.history_view
    ]
    assert history_handlers

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
    profile_back_handlers = [
        h
        for h in handlers
        if isinstance(h, CallbackQueryHandler)
        and h.callback is profile_handlers.profile_back
    ]
    assert profile_back_handlers
