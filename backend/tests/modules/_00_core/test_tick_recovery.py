"""
SQLite tests of the tick_log restart-recovery pass (deploy backlog §7).

A container killed mid-tick leaves RUNNING rows forever;
``mark_interrupted_ticks`` flips them to FAILED with the restart note.
The PostgreSQL side — the advisory lock around the pass — lives in
test_tick_safety_pg.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules._00_core.models import TickLog, TickLogStatus
from modules._00_core.tick_recovery import (
    INTERRUPTED_NOTE,
    mark_interrupted_ticks,
    recover_interrupted_ticks,
)


async def test_mark_interrupted_ticks_flips_only_running(test_db_session):
    """
    RUNNING rows become FAILED with ``interrupted by restart``; finished
    rows keep their status and their original error text.
    """
    now = datetime.now(timezone.utc)
    test_db_session.add_all(
        [
            TickLog(turn_number=1, started_at=now, status=TickLogStatus.RUNNING),
            TickLog(turn_number=2, started_at=now, status=TickLogStatus.RUNNING),
            TickLog(
                turn_number=3,
                started_at=now,
                finished_at=now,
                status=TickLogStatus.COMPLETED,
            ),
            TickLog(
                turn_number=4,
                started_at=now,
                finished_at=now,
                status=TickLogStatus.FAILED,
                error_message="boom",
            ),
        ]
    )
    await test_db_session.flush()

    assert await mark_interrupted_ticks(test_db_session) == 2

    rows = (
        (await test_db_session.execute(select(TickLog).order_by(TickLog.id)))
        .scalars()
        .all()
    )
    assert [row.status for row in rows] == [
        TickLogStatus.FAILED,
        TickLogStatus.FAILED,
        TickLogStatus.COMPLETED,
        TickLogStatus.FAILED,
    ]
    assert rows[0].error_message == INTERRUPTED_NOTE
    assert rows[1].error_message == INTERRUPTED_NOTE
    assert rows[0].finished_at is not None
    assert rows[1].finished_at is not None
    assert rows[2].error_message is None
    assert rows[3].error_message == "boom"


async def test_recover_on_sqlite_marks_and_warns_once(test_db_engine, caplog):
    """
    On the single-writer dialect there is no advisory lock: the pass
    marks directly through a session factory — the lifespan path — and
    logs one WARNING with the count.
    """
    maker = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        session.add(
            TickLog(
                turn_number=1,
                started_at=datetime.now(timezone.utc),
                status=TickLogStatus.RUNNING,
            )
        )
        await session.commit()

    with caplog.at_level(logging.WARNING, logger="modules._00_core.tick_recovery"):
        assert await recover_interrupted_ticks(maker) == 1

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "1" in warnings[0].getMessage()

    async with maker() as session:
        row = (await session.execute(select(TickLog))).scalar_one()
    assert row.status == TickLogStatus.FAILED
    assert row.error_message == INTERRUPTED_NOTE

    # A clean journal marks nothing and stays quiet.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="modules._00_core.tick_recovery"):
        assert await recover_interrupted_ticks(maker) == 0
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
