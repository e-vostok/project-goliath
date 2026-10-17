"""
Root-logging configuration tests (deploy backlog: app INFO lines must
reach ``docker compose logs``).

``configure_logging`` is the lifespan's first statement; these tests
exercise it directly so the env-var cases stay cheap and unit-level.
"""

from __future__ import annotations

import logging

import main


def test_root_logger_emits_modules_info_and_bad_level_falls_back(monkeypatch, caplog):
    """
    An invalid LOG_LEVEL falls back to INFO; after configuration a
    ``modules.*`` INFO record propagates to the root handler (the lines
    uvicorn used to drop), repeated calls never stack a second handler,
    and httpx/httpcore stay at WARNING so request URLs stay out of logs.
    """
    monkeypatch.setenv("LOG_LEVEL", "potato")
    main.configure_logging()
    main.configure_logging()

    root = logging.getLogger()
    assert root.level == logging.INFO
    our_handlers = [h for h in root.handlers if h.name == main._LOG_HANDLER_NAME]
    assert len(our_handlers) == 1
    assert our_handlers[0].formatter._fmt == main._LOG_FORMAT

    probe = logging.getLogger("modules._00_core.tick_handler")
    with caplog.at_level(logging.INFO, logger=probe.name):
        probe.info("Tick %s completed", 42)
    assert any(
        record.name == probe.name
        and record.levelno == logging.INFO
        and "Tick 42 completed" in record.getMessage()
        for record in caplog.records
    )

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
