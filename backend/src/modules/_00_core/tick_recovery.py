"""
Startup recovery of interrupted tick_log rows (deploy backlog §7).

A container that dies mid-tick leaves its tick_log row RUNNING forever.
The stale row blocks nothing — the advisory lock is the only tick mutex
and it dies with the connection — but the journal would lie and the
admin panel would show a ghost run. On boot, under the same advisory
lock the tick itself takes, every leftover RUNNING row is marked FAILED
with the ``interrupted by restart`` note and one WARNING line reports
the count. A tick alive on another instance holds the lock, so the try
fails and the boot touches nothing; SQLite (single writer) marks
directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.tick.orchestrator import TICK_ADVISORY_LOCK_KEY
from modules._00_core.models import TickLog, TickLogStatus

logger = logging.getLogger(__name__)

INTERRUPTED_NOTE = "interrupted by restart"

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def mark_interrupted_ticks(session: AsyncSession) -> int:
    """
    Flip every still-RUNNING tick_log row to FAILED — ``finished_at``
    now, ``error_message`` = :data:`INTERRUPTED_NOTE` — and return the
    marked count. Runs inside the caller's transaction: the caller owns
    the lock and the commit.
    """
    result = await session.execute(
        update(TickLog)
        .where(TickLog.status == TickLogStatus.RUNNING)
        .values(
            status=TickLogStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_message=INTERRUPTED_NOTE,
        )
    )
    return result.rowcount


async def recover_interrupted_ticks(
    session_factory: SessionFactory,
) -> int | None:
    """
    Boot-time repair pass — lifespan calls it before the scheduler
    starts.

    PostgreSQL: ``pg_try_advisory_xact_lock`` on the recovery
    transaction — the very lock ``run_tick`` takes first, so a tick
    alive anywhere else (an overlapping deploy) makes the try fail:
    nothing is touched and ``None`` is returned. On success the commit
    persists the marks and releases the lock.

    SQLite: no advisory locks (single writer) — marks directly.

    Returns the marked count (0 when the journal was clean), or ``None``
    when the lock was not taken.
    """
    marked = 0
    async with session_factory() as session:
        async with session.begin():
            if session.bind.dialect.name == "postgresql":
                locked = (
                    await session.execute(
                        text("SELECT pg_try_advisory_xact_lock(:key)"),
                        {"key": TICK_ADVISORY_LOCK_KEY},
                    )
                ).scalar_one()
                if not locked:
                    return None
            marked = await mark_interrupted_ticks(session)
    if marked:
        logger.warning(
            "Marked %s interrupted tick_log row(s) FAILED (%s)",
            marked,
            INTERRUPTED_NOTE,
        )
    return marked
