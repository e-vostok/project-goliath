"""
File-based SQLite regression tests for the tick path (INV-TICK-ATOMICITY).

The shared in-memory test engine (StaticPool) routes every session through
one DBAPI connection, so it can never expose SQLite's single-writer rule.
These tests run against a real Alembic-migrated tmp_path database file —
the deployment shape — where a tick whose handler writes would deadlock
the tick_log update on a second connection ("database is locked").
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.admin.registry import AdminRegistry
from core.tick.orchestrator import TickOrchestrator, TickPhase
from core.tick.scheduler import run_scheduled_tick
from main import app
from modules._00_core.models import (
    GameClock,
    ScheduledAction,
    ScheduledActionStatus,
    TickLog,
    TickLogStatus,
)
from modules._00_core.tick_handler import register_tick_handlers
from tests.fixtures.factories import ScheduledActionFactory
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]

ADMIN_VK_ID = 424242


@pytest.fixture(autouse=True)
def tick_handlers():
    """Wire the real finalize callback; clear phase handlers afterwards."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


@pytest_asyncio.fixture
async def file_session_maker(tmp_path, monkeypatch):
    """
    Session factory over a real Alembic-migrated SQLite FILE — a separate
    physical connection per session, so the single-writer rule applies.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'tick.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_async_engine(db_url)
    maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    yield maker
    await engine.dispose()


async def _seed_pending_action(session_maker) -> str:
    """Commit one PENDING scheduled_action (nation_id is nullable)."""
    async with session_maker() as session:
        action = ScheduledActionFactory.build(nation=None)
        session.add(action)
        await session.commit()
        return action.id


async def _fetch_clock(session_maker) -> GameClock:
    async with session_maker() as session:
        result = await session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        return result.scalar_one()


async def _fetch_tick_logs(session_maker, turn_number: int) -> list[TickLog]:
    """All tick_log rows for a turn, oldest attempt first."""
    async with session_maker() as session:
        result = await session.execute(
            select(TickLog)
            .where(TickLog.turn_number == turn_number)
            .order_by(TickLog.id)
        )
        return list(result.scalars().all())


def _apply_action_handler(action_id: str):
    """A phase handler that writes to the DB (applies a pending action)."""

    async def handler(session: AsyncSession, turn_number: int) -> None:
        await session.execute(
            update(ScheduledAction)
            .where(ScheduledAction.id == action_id)
            .values(status=ScheduledActionStatus.APPLIED)
        )

    return handler


class TestTickOnFileSQLite:
    """run_scheduled_tick — the production path — on a real DB file."""

    @pytest.mark.asyncio
    async def test_writing_handler_completes_tick(self, file_session_maker):
        """
        A handler that writes must not deadlock the COMPLETED write: the
        tick transaction already holds the SQLite write lock, so tick_log
        is updated on the same connection, not a second one.
        """
        action_id = await _seed_pending_action(file_session_maker)
        TickOrchestrator.register(
            TickPhase.PHASE_4_RESOLVE, _apply_action_handler(action_id)
        )

        async with file_session_maker() as session:
            assert await run_scheduled_tick(session) is True

        clock = await _fetch_clock(file_session_maker)
        assert clock.current_turn == 1

        logs = await _fetch_tick_logs(file_session_maker, turn_number=1)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED
        assert logs[0].finished_at is not None
        assert logs[0].error_message is None

        async with file_session_maker() as session:
            action = await session.get(ScheduledAction, action_id)
        assert action.status == ScheduledActionStatus.APPLIED

    @pytest.mark.asyncio
    async def test_failing_handler_records_failed_and_rolls_back(
        self, file_session_maker
    ):
        """
        A handler that writes and then raises: the tick transaction is
        rolled back (turn unchanged, action still PENDING), the tick_log
        row lands as FAILED with the handler's error — not RUNNING and not
        "database is locked".
        """
        action_id = await _seed_pending_action(file_session_maker)

        async def write_then_fail(session: AsyncSession, turn_number: int) -> None:
            await session.execute(
                update(ScheduledAction)
                .where(ScheduledAction.id == action_id)
                .values(status=ScheduledActionStatus.APPLIED)
            )
            raise ValueError("Handler exploded mid-tick")

        TickOrchestrator.register(TickPhase.PHASE_4_RESOLVE, write_then_fail)

        async with file_session_maker() as session:
            assert await run_scheduled_tick(session) is False

        clock = await _fetch_clock(file_session_maker)
        assert clock.current_turn == 0

        logs = await _fetch_tick_logs(file_session_maker, turn_number=1)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.FAILED
        assert logs[0].finished_at is not None
        assert "Handler exploded mid-tick" in logs[0].error_message
        assert "database is locked" not in logs[0].error_message

        async with file_session_maker() as session:
            action = await session.get(ScheduledAction, action_id)
        assert action.status == ScheduledActionStatus.PENDING

    @pytest.mark.asyncio
    async def test_successful_tick_after_failure(self, file_session_maker):
        """A failed tick leaves no lock or RUNNING residue behind: the next
        attempt runs clean, turns +1 and logs COMPLETED after the FAILED row."""
        async def failing_handler(session: AsyncSession, turn_number: int) -> None:
            raise ValueError("Transient failure")

        TickOrchestrator.register(
            TickPhase.PHASE_1_ENVIRONMENT, failing_handler
        )

        async with file_session_maker() as session:
            assert await run_scheduled_tick(session) is False

        TickOrchestrator.clear_handlers()

        async with file_session_maker() as session:
            assert await run_scheduled_tick(session) is True

        clock = await _fetch_clock(file_session_maker)
        assert clock.current_turn == 1

        logs = await _fetch_tick_logs(file_session_maker, turn_number=1)
        assert [log.status for log in logs] == [
            TickLogStatus.FAILED,
            TickLogStatus.COMPLETED,
        ]


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch):
    """
    The real app over its real ASGI lifespan on a migrated tmp SQLite
    file (the test_app_startup.py pattern). Class-level registries are
    snapshotted and restored so lifespan wiring cannot leak into the
    rest of the suite.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'e2e.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_handlers = {
        phase: list(handlers)
        for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client

    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize


@pytest.mark.asyncio
async def test_admin_tick_run_endpoint_on_file_sqlite(live_client):
    """
    End-to-end: POST /api/v1/admin/tick/run on the live app over a real
    DB file returns ok and advances the turn — the exact deployment path
    that deadlocked before this fix.
    """
    response = await live_client.post(
        "/api/v1/auth/vk",
        json={
            "launch_params": make_launch_params(
                vk_user_id=ADMIN_VK_ID, secret=TEST_VK_SECRET
            )
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await live_client.post(
        "/api/v1/admin/tick/run", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["current_turn"] == 1
    assert body["tick_log"]["turn_number"] == 1
    assert body["tick_log"]["status"] == TickLogStatus.COMPLETED.value
    assert body["next_tick_at"] is not None
