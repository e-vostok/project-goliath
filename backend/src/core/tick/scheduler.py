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

from sqlalchemy import select
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


async def run_scheduled_tick(session: AsyncSession) -> bool:
    """
    Run one game tick on the given session.

    Owns the transaction boundary: commits on success, rolls back on
    failure. Any exception is logged and swallowed — a failed tick must
    never crash the scheduler loop, and every attempt is kept in
    tick_log (multiple rows may share a turn_number).

    Returns True on success, False on failure.
    """
    try:
        async with session.begin():
            await TickOrchestrator.run_tick(session)
    except Exception:
        logger.exception("Scheduled tick failed")
        return False
    return True


async def scheduler_loop(
    session_maker: SessionFactory | None = None,
    max_iterations: int | None = None,
    retry_delay_seconds: float | None = None,
) -> None:
    """
    Infinite tick loop: wait for game_clock.next_tick_at, fire, repeat.

    Each iteration opens a fresh session via session_maker (defaults to
    core.db.get_session_context, the documented non-request entry point).
    If next_tick_at is already in the past when the loop starts, the
    computed sleep is 0 and the tick fires immediately — exactly once —
    then normal cadence resumes from the newly written next_tick_at.

    After a failed tick the loop sleeps retry_delay_seconds before the
    next attempt: the failed tick's transaction is rolled back, so
    next_tick_at stays overdue and an unpaced loop would spin hot.
    A successful tick is unaffected. Defaults to
    tick.retry_delay_seconds from configs/00_core.yaml.

    max_iterations bounds the loop for tests; production leaves it None.
    """
    # Deferred imports mirror orchestrator.run_tick: keeps core.tick free
    # of import-time dependencies on modules.* (which import core.*).
    from modules._00_core.config_schema import CoreConfig
    from modules._00_core.models import GameClock

    session_factory = session_maker if session_maker is not None else get_session_context
    if retry_delay_seconds is None:
        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        retry_delay_seconds = config.tick.retry_delay_seconds
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
            succeeded = await run_scheduled_tick(session)

        if not succeeded:
            await asyncio.sleep(retry_delay_seconds)

        iterations += 1
