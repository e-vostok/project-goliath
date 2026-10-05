"""
Integration tests for the admin-panel HTTP API (Issue 2).

Follows the test_app_startup.py pattern: the REAL app over its real ASGI
lifespan (LifespanManager), a real Alembic-migrated temporary SQLite
file, real JWTs obtained through /api/v1/auth/vk — no dependency
overrides and no mocked DB state (Anti-Mock Guard).

ADMIN_VK_USER_IDS is set per test via monkeypatch. Class-level hook
registries (AdminRegistry, TickOrchestrator) are snapshotted and restored
around each test so extra hooks registered here cannot leak into the rest
of the suite.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, func, select, text

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator, TickPhase
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import GameClock, Province, TickLog, TickLogStatus
from modules._00_core.tick_schedule import next_tick_after
from modules._01_map.models import MapOwnershipLog
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import (
    MAP_MINI_DIR,
    make_land_province,
    map_mini_node_ids,
)
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

ADMIN_VK_ID = 424242
USER_VK_ID = 777001

# The lifespan startup syncs the whole mini map into provinces, so every
# live test sees exactly these rows (plus nothing extra).
MINI_NODE_COUNT = len(map_mini_node_ids())

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/me", None),
    ("GET", "/api/v1/admin/state", None),
    ("GET", "/api/v1/admin/tick-log", None),
    ("POST", "/api/v1/admin/tick/run", None),
    ("POST", "/api/v1/admin/state/reset", {"confirm": True}),
]


def _sync_url(url: str) -> str:
    """Strip the async driver marker for a synchronous engine/psycopg2."""
    for suffix in ("+asyncpg", "+aiosqlite"):
        if suffix in url:
            return url.replace(suffix, "", 1)
    return url


def _probe_pg_test_url() -> str | None:
    """
    Return the DATABASE_URL_TEST PostgreSQL URL when it is set AND
    reachable, else None. The env var may come from the process
    environment or the repo-root .env (same file main.py loads).
    """
    raw = os.environ.get("DATABASE_URL_TEST") or dotenv_values(
        REPO_ROOT / ".env"
    ).get("DATABASE_URL_TEST")
    if not raw or not raw.startswith(("postgresql://", "postgres://", "postgresql+")):
        return None
    try:
        engine = create_engine(_sync_url(raw), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return None
    return raw


PG_TEST_URL = _probe_pg_test_url()


def _reset_pg_schema(url: str) -> None:
    """Drop and recreate the public schema for per-test isolation."""
    engine = create_engine(_sync_url(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _async_url(url: str) -> str:
    """Point a bare postgresql:// URL at the asyncpg driver."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    Serve the real app over its real lifespan against a migrated
    temporary database — the dedicated PostgreSQL test DB when
    DATABASE_URL_TEST is reachable, else a tmp SQLite file — and
    snapshot/restore the class-level hook registries.
    """
    if PG_TEST_URL is not None:
        _reset_pg_schema(PG_TEST_URL)
        db_url = _async_url(PG_TEST_URL)
    else:
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    # DEP-4: the reset gate reads ADMIN_ALLOW_RESET at request time.
    # Enabled here so the pre-existing reset scenarios keep working;
    # the RESET_DISABLED tests override it per test.
    monkeypatch.setenv("ADMIN_ALLOW_RESET", "true")
    # The lifespan startup syncs the mini map into provinces and
    # registers the 01_map hooks — the app's provinces are the fixture's
    # 10 nodes for the whole test.
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_handlers = {
        phase: list(handlers)
        for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback
    saved_extensions = snapshot_extension_points()
    saved_map_service = map_service_module._instance

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
    restore_extension_points(saved_extensions)
    map_service_module._instance = saved_map_service


async def _auth_headers(client: AsyncClient, vk_user_id: int) -> dict:
    """Real login through /api/v1/auth/vk -> Authorization header."""
    response = await client.post(
        "/api/v1/auth/vk",
        json={
            "launch_params": make_launch_params(
                vk_user_id=vk_user_id, secret=TEST_VK_SECRET
            )
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _admin_headers(client: AsyncClient) -> dict:
    return await _auth_headers(client, ADMIN_VK_ID)


async def _request(client: AsyncClient, method: str, url: str, body, headers):
    if method == "GET":
        return await client.get(url, headers=headers)
    return await client.post(url, json=body, headers=headers)


async def _seed_provinces(ids: list[int]) -> None:
    """Insert land provinces straight into the app's live database.

    The migration no longer seeds placeholder rows, so tests that need
    provinces seed exactly the ids they use.
    """
    async with get_session_context() as session:
        for pid in ids:
            await make_land_province(session, id=pid)
        await session.commit()


async def _insert_tick_log(
    turn_number: int,
    status: TickLogStatus = TickLogStatus.COMPLETED,
    error_message: str | None = None,
    finished: bool = True,
) -> datetime:
    """Seed a tick_log row straight into the app's live database.

    finished=False leaves finished_at NULL, like an in-flight RUNNING row.
    Returns the stored started_at instant for exact comparisons.
    """
    now = datetime.now(timezone.utc)
    async with get_session_context() as session:
        session.add(
            TickLog(
                turn_number=turn_number,
                started_at=now,
                finished_at=now if finished else None,
                status=status,
                error_message=error_message,
            )
        )
        await session.commit()
    return now


ADMIN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ADMIN_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _expected_game_time(instant: datetime) -> str:
    """The display string format_game_time must produce for `instant`."""
    tz = ZoneInfo(CORE_CONFIG.tick.tick_timezone)
    return instant.astimezone(tz).strftime(ADMIN_TIME_FORMAT)


class TestAdminAuthorization:
    """Every admin route is gated by require_admin."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,url,body", ADMIN_ROUTES, ids=[r[1] for r in ADMIN_ROUTES]
    )
    async def test_no_token_returns_401(
        self, live_client, monkeypatch, method, url, body
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))

        response = await _request(live_client, method, url, body, headers=None)

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,url,body", ADMIN_ROUTES, ids=[r[1] for r in ADMIN_ROUTES]
    )
    async def test_non_admin_returns_403(
        self, live_client, monkeypatch, method, url, body
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        response = await _request(live_client, method, url, body, headers)

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,url,body", ADMIN_ROUTES, ids=[r[1] for r in ADMIN_ROUTES]
    )
    async def test_admin_gets_200(
        self, live_client, monkeypatch, method, url, body
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await _request(live_client, method, url, body, headers)

        assert response.status_code == 200


class TestAdminMe:
    """GET /api/v1/admin/me is the UI's admin probe."""

    @pytest.mark.asyncio
    async def test_admin_gets_is_admin_true(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.get("/api/v1/admin/me", headers=headers)

        assert response.status_code == 200
        assert response.json() == {"is_admin": True}


class TestAdminState:
    """GET /api/v1/admin/state aggregates module state views."""

    @pytest.mark.asyncio
    async def test_state_contains_00_core_view(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_provinces([1001, 1002, 1003])

        response = await live_client.get("/api/v1/admin/state", headers=headers)

        assert response.status_code == 200
        modules = response.json()["modules"]
        # 02_bot registers its state view in the lifespan since Issue 2.
        assert list(modules) == ["00_core", "02_bot"]
        core = modules["00_core"]
        assert core["clock"]["current_turn"] == 0
        assert core["clock"]["next_tick_at"] is not None
        assert core["counts"]["provinces_total"] == MINI_NODE_COUNT
        assert core["counts"]["provinces_owned"] == 0
        assert core["counts"]["players"] == 1  # the admin login created one
        assert core["players"][0]["vk_user_id"] == ADMIN_VK_ID
        assert core["players"][0]["nation_id"] is None
        assert core["nations"] == []

    @pytest.mark.asyncio
    async def test_state_reflects_created_nation(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_provinces([1001, 1002])
        created = await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Admin Nation",
                "color_hex": "#0A1B2C",
                "province_ids": [1001, 1002],
                **VALID_PROFILE,
            },
        )
        assert created.status_code == 201

        response = await live_client.get("/api/v1/admin/state", headers=headers)

        core = response.json()["modules"]["00_core"]
        assert core["counts"] == {
            "players": 1,
            "nations": 1,
            "provinces_total": MINI_NODE_COUNT,
            "provinces_owned": 2,
        }
        nation = core["nations"][0]
        assert nation["name"] == "Admin Nation"
        assert nation["province_ids"] == [1001, 1002]
        assert core["players"][0]["nation_id"] == nation["id"]

    @pytest.mark.asyncio
    async def test_failing_hook_is_isolated(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        async def boom_view(session):
            raise ValueError("boom")

        AdminRegistry.register_state_view("zzz_broken", boom_view)

        response = await live_client.get("/api/v1/admin/state", headers=headers)

        assert response.status_code == 200
        modules = response.json()["modules"]
        assert modules["zzz_broken"] == {"error": "ValueError"}
        assert (
            modules["00_core"]["counts"]["provinces_total"]
            == MINI_NODE_COUNT
        )


class TestAdminTickLog:
    """GET /api/v1/admin/tick-log lists the audit trail newest-first."""

    @pytest.mark.asyncio
    async def test_newest_first_with_fields(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        for turn in (1, 2, 3):
            await _insert_tick_log(turn)

        response = await live_client.get(
            "/api/v1/admin/tick-log", headers=headers
        )

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 3
        assert [r["turn_number"] for r in rows] == [3, 2, 1]
        assert rows[0]["id"] > rows[1]["id"] > rows[2]["id"]
        for row in rows:
            assert set(row) == {
                "id",
                "turn_number",
                "started_at",
                "finished_at",
                "status",
                "error_message",
            }
            assert row["status"] == "COMPLETED"
            assert ADMIN_TIME_PATTERN.match(row["finished_at"])

    @pytest.mark.asyncio
    async def test_rows_render_game_timezone_times(
        self, live_client, monkeypatch
    ):
        """Times are 'YYYY-MM-DD HH:MM:SS' in tick_timezone under their
        plain names — no offsets, no *_local keys; NULL stays NULL."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        done_instant = await _insert_tick_log(1)
        running_instant = await _insert_tick_log(
            2, status=TickLogStatus.RUNNING, finished=False
        )

        response = await live_client.get(
            "/api/v1/admin/tick-log", headers=headers
        )

        assert response.status_code == 200
        running, done = response.json()  # newest first
        assert not any(
            key.endswith("_local") for row in (running, done) for key in row
        )
        assert running["status"] == "RUNNING"
        assert running["finished_at"] is None
        assert running["started_at"] == _expected_game_time(running_instant)
        assert done["started_at"] == _expected_game_time(done_instant)
        assert done["finished_at"] == _expected_game_time(done_instant)

    @pytest.mark.asyncio
    async def test_limit_param(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        for turn in (1, 2):
            await _insert_tick_log(turn)

        response = await live_client.get(
            "/api/v1/admin/tick-log", params={"limit": 1}, headers=headers
        )

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["turn_number"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, 101])
    async def test_limit_out_of_range_422(
        self, live_client, monkeypatch, limit
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.get(
            "/api/v1/admin/tick-log", params={"limit": limit}, headers=headers
        )

        assert response.status_code == 422


class TestAdminTickRun:
    """POST /api/v1/admin/tick/run drives a real tick through the same
    run_scheduled_tick path the scheduler uses.

    The orchestrator records the COMPLETED status inside the tick's own
    transaction, so a successful tick no longer needs a second writer —
    these tests run on file-based SQLite as well as PostgreSQL.
    """

    @pytest.mark.asyncio
    async def test_manual_tick_advances_turn(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        before = datetime.now(timezone.utc)

        response = await live_client.post(
            "/api/v1/admin/tick/run", headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["current_turn"] == 1
        candidates = {
            _expected_game_time(
                next_tick_after(
                    t,
                    CORE_CONFIG.tick.tick_time,
                    CORE_CONFIG.tick.tick_timezone,
                )
            )
            for t in (before, datetime.now(timezone.utc))
        }
        assert body["next_tick_at"] in candidates
        # tick_time 00:00 in tick_timezone -> local wall clock ends 00:00:00.
        assert body["next_tick_at"].endswith(" 00:00:00")
        assert not any(key.endswith("_local") for key in body)
        assert body["tick_log"]["turn_number"] == 1
        assert body["tick_log"]["status"] == "COMPLETED"
        assert not any(key.endswith("_local") for key in body["tick_log"])
        assert ADMIN_TIME_PATTERN.match(body["tick_log"]["started_at"])
        assert ADMIN_TIME_PATTERN.match(body["tick_log"]["finished_at"])

    @pytest.mark.asyncio
    async def test_failed_phase_handler_returns_ok_false(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        async def failing_handler(session, turn_number):
            raise RuntimeError("phase exploded")

        TickOrchestrator.register(
            TickPhase.PHASE_1_ENVIRONMENT, failing_handler
        )

        response = await live_client.post(
            "/api/v1/admin/tick/run", headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["current_turn"] == 0  # rolled back, turn unchanged
        assert body["tick_log"]["status"] == "FAILED"
        assert "phase exploded" in body["tick_log"]["error_message"]

    @pytest.mark.asyncio
    async def test_tick_run_without_tick_log_row_returns_null(
        self, live_client, monkeypatch
    ):
        """If the tick leaves no tick_log row, the endpoint reports
        tick_log: null instead of crashing on scalar_one()."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        async def wipe_log(session, turn_number):
            # The RUNNING row was committed on a separate connection; a
            # phase handler that wipes it leaves the response with no
            # latest tick_log to report.
            await session.execute(delete(TickLog))

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, wipe_log)

        response = await live_client.post(
            "/api/v1/admin/tick/run", headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["current_turn"] == 1
        assert body["tick_log"] is None

    @pytest.mark.asyncio
    async def test_tick_run_without_game_clock_returns_404(
        self, live_client, monkeypatch
    ):
        """A missing game_clock row maps to the existing 404
        GAME_CLOCK_NOT_FOUND mechanism instead of a 500."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        async with get_session_context() as session:
            await session.execute(delete(GameClock))
            await session.commit()

        response = await live_client.post(
            "/api/v1/admin/tick/run", headers=headers
        )

        assert response.status_code == 404
        assert response.json()["code"] == "GAME_CLOCK_NOT_FOUND"


class TestAdminStateReset:
    """POST /api/v1/admin/state/reset wipes the world via module hooks."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": 1}])
    async def test_without_literal_confirm_returns_400(
        self, live_client, monkeypatch, body
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_provinces([1001])
        await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Keep Me",
                "color_hex": "#102030",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )

        response = await live_client.post(
            "/api/v1/admin/state/reset", json=body, headers=headers
        )

        assert response.status_code == 400
        assert response.json()["code"] == "CONFIRM_REQUIRED"
        # DB untouched: the nation still exists.
        me = await live_client.get("/api/v1/nations/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["name"] == "Keep Me"

    @pytest.mark.asyncio
    async def test_unknown_module_slug_returns_404(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True, "module_slug": "nope"},
            headers=headers,
        )

        assert response.status_code == 404
        assert response.json()["code"] == "MODULE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_reset_removes_world_and_frees_provinces(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_provinces([1001, 1002])
        created = await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Doomed Nation",
                "color_hex": "#3A4B5C",
                "province_ids": [1001, 1002],
                **VALID_PROFILE,
            },
        )
        assert created.status_code == 201

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True},
            headers=headers,
        )

        assert response.status_code == 200
        # 02_bot's queue reset runs first (reverse registration order:
        # 02_bot registered last in the lifespan), then 01_map's
        # journal hook, then 00_core wipes the world.
        assert response.json() == {"reset": ["02_bot", "01_map", "00_core"]}

        me = await live_client.get("/api/v1/nations/me", headers=headers)
        assert me.status_code == 404

        provinces = await live_client.get(
            "/api/v1/provinces",
            params={"free_only": True},
            headers=headers,
        )
        assert len(provinces.json()) == MINI_NODE_COUNT

        clock = await live_client.get("/api/v1/game-clock", headers=headers)
        assert clock.json()["current_turn"] == 0

        # The map reset hook wiped the ownership journal (INV-M8): the
        # create wrote rows, the bulk free during reset writes none.
        async with get_session_context() as session:
            result = await session.execute(
                select(func.count()).select_from(MapOwnershipLog)
            )
            assert result.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_reset_single_module_slug(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True, "module_slug": "00_core"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json() == {"reset": ["00_core"]}

    @pytest.mark.asyncio
    async def test_reset_hooks_run_in_reverse_registration_order(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        calls: list[str] = []

        async def hook_a(session):
            calls.append("mod_a")

        async def hook_b(session):
            calls.append("mod_b")

        AdminRegistry.register_reset("mod_a", hook_a)
        AdminRegistry.register_reset("mod_b", hook_b)

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True},
            headers=headers,
        )

        assert response.status_code == 200
        # Registration order: 00_core, 01_map, 02_bot (lifespan),
        # mod_a, mod_b -> executed reversed.
        assert response.json()["reset"] == [
            "mod_b",
            "mod_a",
            "02_bot",
            "01_map",
            "00_core",
        ]
        assert calls == ["mod_b", "mod_a"]

    @pytest.mark.asyncio
    async def test_failing_hook_rolls_back_earlier_mutations(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_provinces([1001, 1002])
        created = await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Rollback Nation",
                "color_hex": "#5C4B3A",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )
        assert created.status_code == 201

        async def fails_second(session):
            raise RuntimeError("reset blew up")

        async def mutates_first(session):
            await session.execute(
                delete(Province).where(Province.id == 1002)
            )

        # Execution order is reversed registration: mutates_first runs
        # before fails_second.
        AdminRegistry.register_reset("fails_second", fails_second)
        AdminRegistry.register_reset("mutates_first", mutates_first)

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True},
            headers=headers,
        )

        assert response.status_code == 500
        assert response.json()["code"] == "RESET_FAILED"
        assert "fails_second" in response.json()["detail"]

        # mutates_first's delete was rolled back; 00_core never ran, so
        # the nation and all provinces are untouched.
        me = await live_client.get("/api/v1/nations/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["province_ids"] == [1001]
        provinces = await live_client.get("/api/v1/provinces", headers=headers)
        assert len(provinces.json()) == MINI_NODE_COUNT

    @pytest.mark.asyncio
    async def test_reset_clears_tick_log_and_keeps_players(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _insert_tick_log(turn_number=1)

        response = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True},
            headers=headers,
        )
        assert response.status_code == 200

        # The journal is wiped; the admin player still authenticates.
        tick_log = await live_client.get(
            "/api/v1/admin/tick-log", headers=headers
        )
        assert tick_log.json() == []
        state = await live_client.get("/api/v1/admin/state", headers=headers)
        assert state.json()["modules"]["00_core"]["counts"]["players"] == 1


class TestAdminResetGate:
    """ADMIN_ALLOW_RESET gates POST /state/reset (DEP-4).

    The live_client fixture sets the flag to "true"; these tests flip it
    per test — the gate reads the variable at request time. Reset
    semantics under an enabled flag are covered by TestAdminStateReset.
    """

    RESET_URL = "/api/v1/admin/state/reset"

    @pytest.mark.asyncio
    async def test_unset_flag_returns_403_reset_disabled(
        self, live_client, monkeypatch
    ):
        monkeypatch.delenv("ADMIN_ALLOW_RESET", raising=False)
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.post(
            self.RESET_URL, json={"confirm": True}, headers=headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "RESET_DISABLED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value", ["false", "0", "off", "no", "FALSE ", " random"]
    )
    async def test_falsy_flag_values_return_403_reset_disabled(
        self, live_client, monkeypatch, value
    ):
        """Anything outside the truthy set fails closed."""
        monkeypatch.setenv("ADMIN_ALLOW_RESET", value)
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.post(
            self.RESET_URL, json={"confirm": True}, headers=headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "RESET_DISABLED"

    @pytest.mark.asyncio
    async def test_enabled_flag_allows_reset(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_ALLOW_RESET", "true")
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        response = await live_client.post(
            self.RESET_URL, json={"confirm": True}, headers=headers
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_gets_admin_required_not_reset_disabled(
        self, live_client, monkeypatch
    ):
        """require_admin runs BEFORE the gate: a non-admin sees
        ADMIN_REQUIRED even when reset is disabled."""
        monkeypatch.delenv("ADMIN_ALLOW_RESET", raising=False)
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        response = await live_client.post(
            self.RESET_URL, json={"confirm": True}, headers=headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"
