"""
Tests for the 00_core admin-panel hooks (state view + reset).

Anti-Mock Guard: hooks run against the real test DB session with rows
seeded through the shared polyfactory fixtures — no mocked sessions.
When DATABASE_URL_TEST is set, the module-scoped engine targets that
PostgreSQL instance instead of in-memory SQLite (datetime handling).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.admin.registry import AdminRegistry
from core.db import Base
from modules._00_core.admin_hooks import (
    LIST_CAP,
    MODULE_SLUG,
    admin_reset,
    admin_state_view,
    register_admin_hooks,
)
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    TickLog,
    TickLogStatus,
)
from modules._00_core.tick_schedule import next_tick_after
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.factories import (
    GameClockFactory,
    NationFactory,
    PlayerFactory,
    ProvinceFactory,
    ScheduledActionFactory,
    TickLogFactory,
)

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _async_driver_url(url: str) -> str:
    """Point a sync PostgreSQL URL at the asyncpg driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


def _pg_test_url() -> str | None:
    """
    DATABASE_URL_TEST (env or repo-root .env) when it names a reachable
    PostgreSQL instance, else None — hook tests then stay on SQLite.
    """
    raw = os.environ.get("DATABASE_URL_TEST") or dotenv_values(
        _REPO_ROOT / ".env"
    ).get("DATABASE_URL_TEST")
    if not raw or not raw.startswith(("postgresql://", "postgres://", "postgresql+")):
        return None
    try:
        engine = create_engine(raw.replace("+asyncpg", ""))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return None
    return raw


@pytest_asyncio.fixture(scope="function")
async def test_db_engine() -> Any:
    """
    Engine for hook tests: in-memory SQLite, or the real test PostgreSQL
    when DATABASE_URL_TEST is reachable. Schema is dropped+created per
    test so the shared PG database stays isolated between runs.
    """
    pg_url = _pg_test_url()
    url = (
        _async_driver_url(pg_url)
        if pg_url
        else "sqlite+aiosqlite:///:memory:"
    )
    engine = create_async_engine(url, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_db_session(test_db_engine: Any) -> AsyncSession:
    """Session bound to the (possibly PostgreSQL) test engine."""
    session_maker = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_maker() as session:
        await session.begin()
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
def registry_guard():
    """Isolate class-level AdminRegistry state from other test modules."""
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    AdminRegistry.clear_handlers()
    yield
    AdminRegistry.clear_handlers()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.update(saved_resets)


def _utc(dt: datetime) -> datetime:
    """Normalize a possibly-naive DB datetime to aware UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _seed_player(
    session: AsyncSession, vk_user_id: int, created_at: datetime | None = None
) -> Player:
    # polyfactory auto-fills relationships; nations=[] keeps the seed exact.
    player = PlayerFactory.build(
        vk_user_id=vk_user_id,
        created_at=created_at or datetime.now(timezone.utc),
        nations=[],
    )
    session.add(player)
    await session.flush()
    return player


async def _seed_nation(
    session: AsyncSession,
    owner: Player,
    name: str,
    color_hex: str,
    province_ids: list[int],
) -> Nation:
    nation = NationFactory.build(
        owner=owner,
        name=name,
        color_hex=color_hex,
        provinces=[],
        scheduled_actions=[],
    )
    session.add(nation)
    await session.flush()
    for pid in province_ids:
        result = await session.execute(select(Province).where(Province.id == pid))
        result.scalar_one().nation_id = nation.id
    await session.flush()
    return nation


async def _seed_provinces(session: AsyncSession, ids: list[int]) -> None:
    for pid in ids:
        session.add(ProvinceFactory.build(id=pid, nation_id=None, nation=None))
    await session.flush()


class TestRegisterAdminHooks:
    """Registration is idempotent — the lifespan calls it on every boot."""

    def test_registers_both_hooks_under_module_slug(self):
        register_admin_hooks()

        assert AdminRegistry.get_state_view_hooks()[MODULE_SLUG] is admin_state_view
        assert AdminRegistry.get_reset_hooks()[MODULE_SLUG] is admin_reset

    def test_repeated_calls_do_not_raise(self):
        register_admin_hooks()
        register_admin_hooks()
        register_admin_hooks()

        assert list(AdminRegistry.get_state_view_hooks()) == [MODULE_SLUG]
        assert list(AdminRegistry.get_reset_hooks()) == [MODULE_SLUG]


class TestAdminStateView:
    """The read-only JSON snapshot of the 00_core world."""

    @pytest.mark.asyncio
    async def test_state_view_content(self, test_db_session):
        t0 = datetime.now(timezone.utc)
        owner = await _seed_player(test_db_session, vk_user_id=1001, created_at=t0)
        free_player = await _seed_player(
            test_db_session,
            vk_user_id=1002,
            created_at=t0 + timedelta(seconds=1),
        )
        await _seed_provinces(test_db_session, [1, 2, 3])
        nation = await _seed_nation(
            test_db_session, owner, "View Nation", "#112233", [2, 1]
        )
        clock = GameClockFactory.build(
            current_turn=7,
            last_tick_at=t0 - timedelta(hours=1),
            next_tick_at=t0 + timedelta(hours=23),
        )
        test_db_session.add(clock)
        await test_db_session.flush()

        view = await admin_state_view(test_db_session)

        # The whole snapshot must be JSON-serializable.
        json.dumps(view)

        assert view["clock"]["current_turn"] == 7
        # Times render as 'YYYY-MM-DD HH:MM:SS' in tick_timezone.
        tz = ZoneInfo(CORE_CONFIG.tick.tick_timezone)
        fmt = "%Y-%m-%d %H:%M:%S"
        assert view["clock"]["last_tick_at"] == _utc(
            clock.last_tick_at
        ).astimezone(tz).strftime(fmt)
        assert view["clock"]["next_tick_at"] == _utc(
            clock.next_tick_at
        ).astimezone(tz).strftime(fmt)

        assert view["counts"] == {
            "players": 2,
            "nations": 1,
            "provinces_total": 3,
            "provinces_owned": 2,
        }

        assert view["players_total"] == 2
        assert view["players_truncated"] is False
        assert [p["vk_user_id"] for p in view["players"]] == [1001, 1002]
        owner_row = view["players"][0]
        assert owner_row["id"] == owner.id
        assert owner_row["nation_id"] == nation.id
        assert owner_row["created_at"] == _utc(owner.created_at).astimezone(
            tz
        ).strftime(fmt)
        assert view["players"][1]["id"] == free_player.id
        assert view["players"][1]["nation_id"] is None

        assert view["nations_total"] == 1
        assert view["nations_truncated"] is False
        nation_row = view["nations"][0]
        assert nation_row["id"] == nation.id
        assert nation_row["name"] == "View Nation"
        assert nation_row["color_hex"] == "#112233"
        assert nation_row["owner_player_id"] == owner.id
        assert nation_row["province_ids"] == [1, 2]
        assert nation_row["leader_name"] == VALID_PROFILE["leader_name"]
        assert nation_row["leader_title"] == VALID_PROFILE["leader_title"]
        assert nation_row["history_url"] == VALID_PROFILE["history_url"]
        assert nation_row["created_at"] == _utc(nation.created_at).astimezone(
            tz
        ).strftime(fmt)

    @pytest.mark.asyncio
    async def test_state_view_missing_clock_returns_none(self, test_db_session):
        view = await admin_state_view(test_db_session)

        assert view["clock"] is None
        assert view["counts"] == {
            "players": 0,
            "nations": 0,
            "provinces_total": 0,
            "provinces_owned": 0,
        }
        assert view["players"] == []
        assert view["nations"] == []

    @pytest.mark.asyncio
    async def test_state_view_caps_lists_at_200(self, test_db_session):
        base = datetime.now(timezone.utc)
        for i in range(LIST_CAP + 5):
            player = await _seed_player(
                test_db_session,
                vk_user_id=900000 + i,
                created_at=base + timedelta(seconds=i),
            )
            nation = NationFactory.build(
                owner=player,
                name=f"Nation {i:03d}",
                color_hex=f"#{(i % 0xFFFFFF):06X}",
                created_at=base + timedelta(seconds=i),
                provinces=[],
                scheduled_actions=[],
            )
            test_db_session.add(nation)
        await test_db_session.flush()

        view = await admin_state_view(test_db_session)

        assert len(view["players"]) == LIST_CAP
        assert view["players_total"] == LIST_CAP + 5
        assert view["players_truncated"] is True
        # Order is created_at then id: the first LIST_CAP rows in time order.
        assert [p["vk_user_id"] for p in view["players"]] == [
            900000 + i for i in range(LIST_CAP)
        ]

        assert len(view["nations"]) == LIST_CAP
        assert view["nations_total"] == LIST_CAP + 5
        assert view["nations_truncated"] is True
        assert view["truncated"] is True


class TestAdminReset:
    """The world-reset hook: all-or-nothing state wipe, no commit."""

    @pytest.mark.asyncio
    async def test_reset_wipes_world_and_tick_log_but_keeps_players(
        self, test_db_session
    ):
        owner = await _seed_player(test_db_session, vk_user_id=3001)
        await _seed_provinces(test_db_session, [1, 2, 3])
        nation = await _seed_nation(
            test_db_session, owner, "Doomed Nation", "#445566", [1, 2]
        )
        test_db_session.add(
            ScheduledActionFactory.build(nation=nation)
        )
        test_db_session.add(
            GameClockFactory.build(
                current_turn=9,
                last_tick_at=datetime.now(timezone.utc),
                next_tick_at=datetime.now(timezone.utc),
            )
        )
        test_db_session.add(
            TickLogFactory.build(
                turn_number=9, status=TickLogStatus.COMPLETED
            )
        )
        await test_db_session.flush()

        before = datetime.now(timezone.utc)
        await admin_reset(test_db_session)
        await test_db_session.flush()
        after = datetime.now(timezone.utc)

        result = await test_db_session.execute(select(func.count()).select_from(Nation))
        assert result.scalar_one() == 0
        result = await test_db_session.execute(
            select(func.count()).select_from(ScheduledAction)
        )
        assert result.scalar_one() == 0

        result = await test_db_session.execute(select(Province))
        provinces = result.scalars().all()
        assert len(provinces) == 3
        assert all(p.nation_id is None for p in provinces)

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = result.scalar_one()
        assert clock.current_turn == 0
        assert clock.last_tick_at is None
        candidates = {
            next_tick_after(
                t,
                CORE_CONFIG.tick.tick_time,
                CORE_CONFIG.tick.tick_timezone,
            )
            for t in (before, after)
        }
        assert _utc(clock.next_tick_at) in candidates

        # Survivors: players only — the tick audit trail is wiped too.
        result = await test_db_session.execute(select(Player))
        assert [p.vk_user_id for p in result.scalars().all()] == [3001]
        result = await test_db_session.execute(
            select(func.count()).select_from(TickLog)
        )
        assert result.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_reset_on_empty_world(self, test_db_session):
        """No nations/actions and no clock row: reset still succeeds."""
        await admin_reset(test_db_session)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = result.scalar_one()
        assert clock.current_turn == 0
        assert clock.last_tick_at is None
        assert _utc(clock.next_tick_at) > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_reset_inserts_missing_clock_row(self, test_db_session):
        """A populated world without game_clock gets the singleton back."""
        owner = await _seed_player(test_db_session, vk_user_id=4001)
        await _seed_provinces(test_db_session, [1])
        await _seed_nation(
            test_db_session, owner, "Clockless", "#778899", [1]
        )

        await admin_reset(test_db_session)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = result.scalar_one()
        assert clock.current_turn == 0
        assert clock.next_tick_at is not None
        result = await test_db_session.execute(
            select(func.count()).select_from(Nation)
        )
        assert result.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_reset_hook_via_registry(self, test_db_session):
        """The registered reset hook is the real admin_reset function."""
        register_admin_hooks()
        hook = AdminRegistry.get_reset_hooks()[MODULE_SLUG]

        await _seed_player(test_db_session, vk_user_id=5001)
        await hook(test_db_session)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        assert result.scalar_one().current_turn == 0


class TestAdminEndpointFunctions:
    """
    Direct invocations of the admin router's endpoint functions against
    the real test DB session — the same code the ASGI layer calls, but
    exercised in-line so every handler branch is covered without HTTP.
    """

    @pytest.fixture(autouse=True)
    def _engine(self, test_db_engine):
        """Bind core.db globals to the test engine for get_session_context()."""
        from core import db as core_db

        saved_engine, saved_maker = core_db._engine, core_db._async_session_maker
        core_db._engine = test_db_engine
        core_db._async_session_maker = async_sessionmaker(
            test_db_engine, class_=AsyncSession, expire_on_commit=False
        )
        yield
        core_db._engine, core_db._async_session_maker = (
            saved_engine, saved_maker,
        )

    @pytest.fixture(autouse=True)
    def _tick_handlers(self):
        """Wire the real finalize callback; restore orchestrator state."""
        from core.tick.orchestrator import TickOrchestrator
        from modules._00_core.tick_handler import register_tick_handlers

        saved_handlers = {
            phase: list(handlers)
            for phase, handlers in TickOrchestrator._handlers.items()
        }
        saved_finalize = TickOrchestrator._finalize_callback
        TickOrchestrator.clear_handlers()
        register_tick_handlers()
        yield
        TickOrchestrator._handlers.clear()
        TickOrchestrator._handlers.update(saved_handlers)
        TickOrchestrator._finalize_callback = saved_finalize

    @pytest.mark.asyncio
    async def test_admin_state_direct(self, test_db_session):
        from core.admin.router import admin_state

        register_admin_hooks()

        async def boom(session):
            raise ValueError("view exploded")

        AdminRegistry.register_state_view("boom_view", boom)

        view = await admin_state(admin=None, session=test_db_session)

        assert set(view["modules"]) == {"00_core", "boom_view"}
        assert view["modules"]["boom_view"] == {"error": "ValueError"}
        assert view["modules"]["00_core"]["counts"]["players"] == 0

    @pytest.mark.asyncio
    async def test_admin_tick_log_direct(self, test_db_session):
        from core.admin.router import admin_tick_log

        for turn in (1, 2, 3):
            test_db_session.add(
                TickLog(
                    turn_number=turn,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    status=TickLogStatus.COMPLETED,
                )
            )
        await test_db_session.flush()

        rows = await admin_tick_log(
            admin=None, session=test_db_session, limit=2
        )

        assert [r["turn_number"] for r in rows] == [3, 2]
        assert rows[0]["status"] == "COMPLETED"
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", rows[0]["started_at"]
        )

    @pytest.mark.asyncio
    async def test_admin_tick_run_direct(self, test_db_session):
        from core.admin.router import admin_tick_run

        test_db_session.add(GameClockFactory.build(current_turn=0))
        await test_db_session.flush()
        await test_db_session.commit()

        result = await admin_tick_run(admin=None, session=test_db_session)

        assert result["ok"] is True
        assert result["current_turn"] == 1
        assert result["tick_log"]["status"] == "COMPLETED"
        assert result["tick_log"]["turn_number"] == 1
        # Daily tick at 00:00 tick_timezone -> local string ends 00:00:00.
        assert result["next_tick_at"].endswith(" 00:00:00")

    @pytest.mark.asyncio
    async def test_reset_restarts_tick_log_ids_from_1(
        self, test_db_session
    ):
        """Real ticks push ids past 1; after reset the next row is id 1."""
        from core.admin.router import admin_tick_run

        test_db_session.add(GameClockFactory.build(current_turn=0))
        await test_db_session.commit()

        for _ in range(3):
            result = await admin_tick_run(
                admin=None, session=test_db_session
            )
            assert result["ok"] is True
        assert result["tick_log"]["id"] == 3

        await admin_reset(test_db_session)
        await test_db_session.commit()

        result = await admin_tick_run(admin=None, session=test_db_session)
        assert result["ok"] is True
        assert result["current_turn"] == 1
        assert result["tick_log"]["id"] == 1
        assert result["tick_log"]["turn_number"] == 1

    @pytest.mark.asyncio
    async def test_reset_on_empty_tick_log_next_id_is_1(
        self, test_db_session
    ):
        """Resetting an empty journal is fine and the first tick still
        gets id 1."""
        from core.admin.router import admin_tick_run

        test_db_session.add(GameClockFactory.build(current_turn=0))
        await test_db_session.commit()

        await admin_reset(test_db_session)
        await test_db_session.commit()

        result = await admin_tick_run(admin=None, session=test_db_session)
        assert result["ok"] is True
        assert result["tick_log"]["id"] == 1

    @pytest.mark.asyncio
    async def test_failed_later_hook_rolls_back_id_counter(
        self, test_db_session
    ):
        """A failing hook after 00_core rolls the whole reset back: the
        old tick_log rows return AND the id counter is not restarted —
        the next insert resumes above the restored rows instead of
        colliding with them."""
        from core.admin.router import (
            ResetFailedError,
            StateResetRequest,
            admin_state_reset,
        )

        # Reversed registration order: 00_core runs first, fails_later
        # blows up after the row delete + counter reset were applied.
        async def fails_later(session):
            raise RuntimeError("later hook failed")

        AdminRegistry.register_reset("fails_later", fails_later)
        register_admin_hooks()

        # Rows inserted WITHOUT explicit ids so they consume the real
        # counter (identity sequence on Postgres, rowid on SQLite): 1,2,3.
        for turn in (1, 2, 3):
            now = datetime.now(timezone.utc)
            test_db_session.add(
                TickLog(
                    turn_number=turn,
                    started_at=now,
                    finished_at=now,
                    status=TickLogStatus.COMPLETED,
                )
            )
        await test_db_session.commit()

        with pytest.raises(ResetFailedError):
            await admin_state_reset(
                body=StateResetRequest(confirm=True),
                admin=None,
                session=test_db_session,
            )

        result = await test_db_session.execute(select(TickLog))
        assert len(result.scalars().all()) == 3

        now = datetime.now(timezone.utc)
        new_row = TickLog(
            turn_number=99,
            started_at=now,
            finished_at=now,
            status=TickLogStatus.COMPLETED,
        )
        test_db_session.add(new_row)
        await test_db_session.flush()
        assert new_row.id == 4

    @pytest.mark.asyncio
    async def test_admin_state_reset_direct(self, test_db_session):
        from core.admin.router import (
            ConfirmRequiredError,
            ResetFailedError,
            StateResetRequest,
            admin_state_reset,
        )

        register_admin_hooks()

        # confirm must be literal True — falsy and non-bool both rejected.
        for body in (
            StateResetRequest(confirm=False),
            StateResetRequest(confirm=1),
            StateResetRequest(),
        ):
            with pytest.raises(ConfirmRequiredError):
                await admin_state_reset(
                    body=body, admin=None, session=test_db_session
                )

        # Success path: all hooks commit, response lists slugs in
        # execution order (reverse registration — only 00_core here).
        result = await admin_state_reset(
            body=StateResetRequest(confirm=True),
            admin=None,
            session=test_db_session,
        )
        assert result["reset"] == ["00_core"]

        # A failing hook aborts the whole reset and names its own slug.
        async def mutates(session):
            await session.execute(update(Player).values(vk_user_id=1))

        async def fails(session):
            raise RuntimeError("later hook failed")

        AdminRegistry.register_reset("fails_later", fails)
        AdminRegistry.register_reset("mutates_early", mutates)

        with pytest.raises(ResetFailedError) as exc_info:
            await admin_state_reset(
                body=StateResetRequest(confirm=True),
                admin=None,
                session=test_db_session,
            )
        assert exc_info.value.code == "RESET_FAILED"
        assert "fails_later" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_admin_state_reset_module_not_found(self, test_db_session):
        from core.admin.router import (
            AdminModuleNotFoundError,
            StateResetRequest,
            admin_state_reset,
        )

        register_admin_hooks()
        with pytest.raises(AdminModuleNotFoundError):
            await admin_state_reset(
                body=StateResetRequest(confirm=True, module_slug="ghost"),
                admin=None,
                session=test_db_session,
            )
