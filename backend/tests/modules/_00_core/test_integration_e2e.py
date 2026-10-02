"""
End-to-end integration tests for module 00_core.

Drives one continuous lifecycle through the real HTTP layer and the real
tick engine against the shared in-memory test DB: VK launch-params auth ->
nation founding -> server tick via TickOrchestrator.

No mocking of the DB session, the HTTP client, or TickOrchestrator
internals (Anti-Mock Guard, INV-TICK-ATOMICITY).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.db import get_session
from core.tick.orchestrator import TickOrchestrator, TickPhase
from main import app
from modules._00_core.models import (
    GameClock,
    Nation,
    Province,
    TickLog,
    TickLogStatus,
)
from modules._00_core.tick_handler import register_tick_handlers

from .test_router import seed_provinces
from .test_security import TEST_APP_SECRET, make_launch_params
from tests.fixtures.profile import VALID_PROFILE

TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"

VK_USER_ID = 424242
NATION_NAME = "Northern Syndicate"
NATION_COLOR = "#E64545"


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide VK/JWT secrets for every test."""
    monkeypatch.setenv("VK_APP_SECRET", TEST_APP_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


@pytest.fixture(autouse=True)
def tick_handlers():
    """Wire the real finalize callback; clear phase handlers afterwards."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test DB session."""
    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def seed_game_clock(session, current_turn: int = 0) -> GameClock:
    """Seed the game_clock singleton row required by run_tick."""
    clock = GameClock(
        id=1,
        current_turn=current_turn,
        last_tick_at=None,
        next_tick_at=datetime.now(timezone.utc),
    )
    session.add(clock)
    await session.flush()
    return clock


async def fetch_nation_reservations(session) -> dict[int, str | None]:
    """Read every province's nation_id straight from the DB."""
    result = await session.execute(select(Province).order_by(Province.id))
    return {p.id: p.nation_id for p in result.scalars().all()}


class TestEndToEnd:
    """Full lifecycle: auth -> found nation -> tick (INV-3, atomicity)."""

    async def _auth_and_found_nation(
        self, client, test_db_session
    ) -> tuple[str, str]:
        """
        Drive the two-request entry flow every player takes: signed VK
        launch params -> Bearer JWT -> POST /nations. Returns
        (player_id, nation_id) after verifying the rows in the DB.
        """
        auth = await client.post(
            "/api/v1/auth/vk",
            json={"launch_params": make_launch_params(vk_user_id=VK_USER_ID)},
        )
        assert auth.status_code == 200
        token = auth.json()["access_token"]
        player_id = auth.json()["player"]["id"]

        create = await client.post(
            "/api/v1/nations",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": NATION_NAME,
                "color_hex": NATION_COLOR,
                "province_ids": [1001, 1002],
                **VALID_PROFILE,
            },
        )
        assert create.status_code == 201
        nation_id = create.json()["id"]

        # DB-direct check (INV-3): the nation row and its province
        # reservations match exactly what was requested — nothing more,
        # nothing less.
        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one()
        assert nation.name == NATION_NAME
        assert nation.color_hex == NATION_COLOR
        assert nation.owner_player_id == player_id

        reservations = await fetch_nation_reservations(test_db_session)
        assert reservations == {1001: nation_id, 1002: nation_id, 1003: None}

        return player_id, nation_id

    async def test_auth_nation_tick_happy_path(self, client, test_db_session):
        """VK auth -> nation founding -> tick: all state lands and turns."""
        await seed_provinces(test_db_session, [1001, 1002, 1003])
        clock = await seed_game_clock(test_db_session)
        initial_turn = clock.current_turn

        await self._auth_and_found_nation(client, test_db_session)

        await TickOrchestrator.run_tick(test_db_session)

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        assert result.scalar_one().current_turn == initial_turn + 1

        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.COMPLETED
        assert tick_log.finished_at is not None
        assert tick_log.error_message is None

    async def test_failed_tick_rolls_back_together(
        self, client, test_db_session
    ):
        """A blowing-up phase handler must roll back the whole tick
        transaction: in-tick mutations are discarded, committed pre-tick
        state is untouched, and tick_log still records FAILED."""
        await seed_provinces(test_db_session, [1001, 1002, 1003])
        clock = await seed_game_clock(test_db_session)
        initial_turn = clock.current_turn

        _, nation_id = await self._auth_and_found_nation(
            client, test_db_session
        )

        async def corrupting_handler(session, turn_number):
            """Dirties tick-scoped state, then blows up.

            The mutations stay pending in the tick transaction; the raise
            must make run_tick propagate so the caller rolls them back.
            """
            result = await session.execute(
                select(Nation).where(Nation.id == nation_id)
            )
            nation = result.scalar_one()
            result = await session.execute(
                select(Province).where(Province.id == 1001)
            )
            province = result.scalar_one()
            nation.name = "Corrupted Name"
            province.nation_id = None
            raise RuntimeError("Simulated tick failure")

        TickOrchestrator.register(
            TickPhase.PHASE_1_ENVIRONMENT, corrupting_handler
        )

        with pytest.raises(RuntimeError, match="Simulated tick failure"):
            await TickOrchestrator.run_tick(test_db_session)

        # The real caller's contract after a propagated failure.
        await test_db_session.rollback()

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        assert result.scalar_one().current_turn == initial_turn

        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.FAILED
        assert tick_log.finished_at is not None
        assert "Simulated tick failure" in tick_log.error_message

        # Committed pre-tick state is untouched: nation still exists with
        # its original name and exactly its reserved provinces.
        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one()
        assert nation.name == NATION_NAME
        assert nation.color_hex == NATION_COLOR

        reservations = await fetch_nation_reservations(test_db_session)
        assert reservations == {1001: nation_id, 1002: nation_id, 1003: None}
