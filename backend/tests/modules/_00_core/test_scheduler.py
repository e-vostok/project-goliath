"""
Tests for the automatic tick scheduler (Issue 6).

Real test DB throughout (Anti-Mock Guard): sessions come from a real
async_sessionmaker bound to the in-memory test engine — the same engine
run_tick's internal log sessions bind to. Wall-clock delay is controlled
by seeding next_tick_at in the past or by patching asyncio.sleep; both
exercise real code paths.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.tick.orchestrator import TickOrchestrator, TickPhase
from core.tick.scheduler import run_scheduled_tick, scheduler_loop, seconds_until
from main import app
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import GameClock, TickLog, TickLogStatus
from modules._00_core.tick_handler import register_tick_handlers
from tests.fixtures.factories import GameClockFactory
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import TEST_JWT_SECRET, TEST_VK_SECRET

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def tick_handlers():
    """Wire the real finalize callback; clear phase handlers afterwards."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


@pytest_asyncio.fixture
async def session_maker(test_db_engine):
    """Session factory bound to the real in-memory test DB."""
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_game_clock(
    session_maker,
    next_tick_at: datetime | None = None,
    current_turn: int = 0,
) -> None:
    """Persist the game_clock singleton row via a real committed session."""
    clock = GameClockFactory.build(
        current_turn=current_turn,
        next_tick_at=next_tick_at or datetime.now(timezone.utc),
    )
    async with session_maker() as session:
        session.add(clock)
        await session.commit()


async def _fetch_clock(session_maker) -> GameClock:
    async with session_maker() as session:
        result = await session.execute(select(GameClock).where(GameClock.id == 1))
        return result.scalar_one()


class TestSecondsUntil:
    """Pure function: time remaining until the next tick."""

    def test_future_timestamp_returns_positive_seconds(self):
        now = datetime.now(timezone.utc)
        assert seconds_until(now + timedelta(hours=1), now) == 3600.0

    def test_past_timestamp_clamps_to_zero(self):
        now = datetime.now(timezone.utc)
        assert seconds_until(now - timedelta(hours=1), now) == 0.0


async def _fetch_tick_logs(session_maker, turn_number: int) -> list[TickLog]:
    """All tick_log rows for a turn, oldest attempt first."""
    async with session_maker() as session:
        result = await session.execute(
            select(TickLog)
            .where(TickLog.turn_number == turn_number)
            .order_by(TickLog.id)
        )
        return list(result.scalars().all())


class TestRunScheduledTick:
    """One scheduled tick against the real DB."""

    @pytest.mark.asyncio
    async def test_happy_path_increments_current_turn(self, session_maker):
        await _seed_game_clock(session_maker)

        async with session_maker() as session:
            assert await run_scheduled_tick(session) is True

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 1
        assert clock.last_tick_at is not None

        logs = await _fetch_tick_logs(session_maker, turn_number=1)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED
        assert logs[0].finished_at is not None

    @pytest.mark.asyncio
    async def test_two_failed_attempts_keep_two_failed_rows(self, session_maker):
        """
        A handler that raises must not wedge the mechanism: each call
        returns normally (False), the turn is rolled back, and every
        attempt is recorded — multiple rows may share a turn_number
        (INV-TICK-ATOMICITY).
        """
        await _seed_game_clock(session_maker)

        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)

        for _ in range(2):
            async with session_maker() as session:
                assert await run_scheduled_tick(session) is False

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 0

        logs = await _fetch_tick_logs(session_maker, turn_number=1)
        assert len(logs) == 2
        assert all(log.status == TickLogStatus.FAILED for log in logs)
        assert all(
            "Simulated handler failure" in log.error_message for log in logs
        )

    @pytest.mark.asyncio
    async def test_later_successful_attempt_keeps_failure_history(
        self, session_maker
    ):
        """
        After failures are resolved, the next scheduled tick completes
        and the earlier FAILED rows remain — full attempt history.
        """
        await _seed_game_clock(session_maker)

        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)

        for _ in range(2):
            async with session_maker() as session:
                await run_scheduled_tick(session)

        # Transient failure resolved — the next scheduled tick succeeds.
        TickOrchestrator.clear_handlers()

        async with session_maker() as session:
            assert await run_scheduled_tick(session) is True

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 1

        logs = await _fetch_tick_logs(session_maker, turn_number=1)
        assert [log.status for log in logs] == [
            TickLogStatus.FAILED,
            TickLogStatus.FAILED,
            TickLogStatus.COMPLETED,
        ]


class TestSchedulerLoop:
    """The bounded loop against the real DB."""

    @pytest.mark.asyncio
    async def test_two_iterations_increment_turn_twice(
        self, session_maker, monkeypatch
    ):
        """
        next_tick_at seeded in the past fires immediately (startup
        catch-up); asyncio.sleep is patched to a real zero-yield so the
        post-tick 24h cadence doesn't block the test — both iterations
        still execute real ticks on the real DB.
        """
        real_sleep = asyncio.sleep

        async def immediate_sleep(_delay: float) -> None:
            await real_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)

        await _seed_game_clock(
            session_maker,
            next_tick_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        await scheduler_loop(session_maker, max_iterations=2)

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 2

        async with session_maker() as session:
            result = await session.execute(
                select(TickLog).order_by(TickLog.turn_number)
            )
            logs = result.scalars().all()
        assert len(logs) == 2
        assert [log.turn_number for log in logs] == [1, 2]
        assert all(log.status == TickLogStatus.COMPLETED for log in logs)

    @pytest.mark.asyncio
    async def test_failed_tick_waits_retry_delay(
        self, session_maker
    ):
        """
        A persistent failure must not spin in a hot loop: the next_tick
        wait resolves to 0 (next_tick_at rolled back unchanged), so the
        loop paces itself on retry_delay_seconds — exercised at the
        minimum allowed value (1s) with real sleeps.
        """
        await _seed_game_clock(
            session_maker,
            next_tick_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)

        started = time.monotonic()
        await scheduler_loop(
            session_maker, max_iterations=2, retry_delay_seconds=1
        )
        elapsed = time.monotonic() - started

        # Two failed attempts -> two paced retries (~1s each), while the
        # overdue next_tick_at itself contributed ~0 of waiting.
        assert elapsed >= 1.9
        assert elapsed < 30

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 0

        logs = await _fetch_tick_logs(session_maker, turn_number=1)
        assert len(logs) == 2
        assert all(log.status == TickLogStatus.FAILED for log in logs)


class TestLifespanWiring:
    """
    The scheduler task lives and dies with the app lifespan.

    Reuses the test_app_startup.py pattern: real app, real ASGI
    lifespan, real migrated SQLite file — the only path that exercises
    the production scheduler wiring.
    """

    @pytest.mark.asyncio
    async def test_scheduler_task_starts_and_cancels_cleanly(
        self, tmp_path, monkeypatch
    ):
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'scheduler.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
        monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
        # Lifespan startup syncs the mini map — never the real one.
        monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

        alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")

        saved_resets = AdminRegistry.get_reset_hooks()
        saved_extensions = snapshot_extension_points()
        saved_map_service = map_service_module._instance
        try:
            async with LifespanManager(app):
                tasks = [
                    t
                    for t in asyncio.all_tasks()
                    if t.get_name() == "tick-scheduler"
                ]
                assert len(tasks) == 1
                scheduler_task = tasks[0]
                assert not scheduler_task.done()
        finally:
            AdminRegistry._reset_hooks.clear()
            AdminRegistry._reset_hooks.update(saved_resets)
            restore_extension_points(saved_extensions)
            map_service_module._instance = saved_map_service

        # Shutdown must cancel it without leaking CancelledError.
        assert scheduler_task.cancelled()
