"""
Automatic tick scheduling for the game loop.

Wraps TickOrchestrator.run_tick() in a periodic asyncio loop driven by
game_clock.next_tick_at. A failed tick never stops the schedule: the
orchestrator already guarantees the failed attempt is atomic and recorded
in tick_log (INV-TICK-ATOMICITY), so the scheduler's only job is to keep
going.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def seconds_until(next_tick_at: datetime, now: datetime) -> float:
    """
    Seconds remaining until next_tick_at.

    Returns 0 when next_tick_at is already in the past (overdue tick),
    never a negative value.
    """
    return max(0.0, (next_tick_at - now).total_seconds())


async def run_scheduled_tick(session: AsyncSession) -> None:
    """
    Run one game tick on the given session.

    Owns the transaction boundary: commits on success, rolls back on
    failure. Any exception is logged and swallowed — a failed tick must
    never crash the scheduler loop.

    Retry semantics: a failed attempt leaves a committed FAILED row in
    tick_log (INV-TICK-ATOMICITY), and tick_log.turn_number is UNIQUE.
    Since current_turn does not advance on failure, the next scheduled
    tick retries the same turn_number — so the superseded FAILED row is
    removed in its own committed transaction *before* run_tick inserts
    the new RUNNING row, otherwise the retry could never start.
    """
    from modules._00_core.models import GameClock, TickLog, TickLogStatus

    try:
        async with session.begin():
            current_turn = (
                await session.execute(
                    select(GameClock.current_turn).where(GameClock.id == 1)
                )
            ).scalar_one()
            await session.execute(
                delete(TickLog).where(
                    TickLog.turn_number == current_turn + 1,
                    TickLog.status == TickLogStatus.FAILED,
                )
            )

        async with session.begin():
            await TickOrchestrator.run_tick(session)
    except Exception:
        logger.exception("Scheduled tick failed")


async def scheduler_loop(
    session_maker: SessionFactory | None = None,
    max_iterations: int | None = None,
) -> None:
    """
    Infinite tick loop: wait for game_clock.next_tick_at, fire, repeat.

    Each iteration opens a fresh session via session_maker (defaults to
    core.db.get_session_context, the documented non-request entry point).
    If next_tick_at is already in the past when the loop starts, the
    computed sleep is 0 and the tick fires immediately — exactly once —
    then normal cadence resumes from the newly written next_tick_at.

    max_iterations bounds the loop for tests; production leaves it None.
    """
    # Deferred import mirrors orchestrator.run_tick: keeps core.tick free
    # of import-time dependencies on modules.* (which import core.*).
    from modules._00_core.models import GameClock

    session_factory = session_maker if session_maker is not None else get_session_context
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        async with session_factory() as session:
            result = await session.execute(
                select(GameClock.next_tick_at).where(GameClock.id == 1)
            )
            next_tick_at = result.scalar_one()

        # SQLite returns naive datetimes even for timezone=True columns.
        if next_tick_at.tzinfo is None:
            next_tick_at = next_tick_at.replace(tzinfo=timezone.utc)

        await asyncio.sleep(seconds_until(next_tick_at, datetime.now(timezone.utc)))

        async with session_factory() as session:
            await run_scheduled_tick(session)

        iterations += 1
