"""
Startup wiring of 01_map (Spec Part 2 "Порядок запуска", INV-M5/M9).

Real databases only: a migrated tmp SQLite file per test (Alembic, the
same path the app uses) and one real-map run. MAP_DATA_DIR selects the
map directory exactly like production.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import modules._01_map.service as map_service_module
import core.db as core_db
from core.admin.registry import AdminRegistry
from core.db import get_session_context, init_engine
from main import app
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    get_ownership_listeners,
    get_registration_checks,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Province
from modules._01_map.loader import MapDataError
from modules._01_map.startup import resolve_data_dir, startup_map
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import TEST_JWT_SECRET, TEST_VK_SECRET

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
REAL_MAP_DIR = REPO_ROOT / "data" / "map"


@pytest_asyncio.fixture
async def booted_db(tmp_path, monkeypatch):
    """
    A migrated tmp SQLite file with the app's engine initialised —
    the minimum environment ``startup_map()`` needs outside lifespan.
    """
    db_file = tmp_path / "startup.db"
    sync_url = f"sqlite:///{db_file.as_posix()}"
    async_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", sync_url)
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    init_engine(async_url)
    yield async_url
    await core_db.get_engine().dispose()
    core_db._engine = None
    core_db._async_session_maker = None


@pytest.fixture
def map_env(monkeypatch, extension_snapshot, mini_map_config):
    """Point MAP_DATA_DIR at the mini fixture (and the config frame at
    the mini view_box via ``mini_map_config``); restore registries."""
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    yield


async def _province_kinds(session) -> dict[int, str]:
    result = await session.execute(sa.select(Province.id, Province.kind))
    return {row.id: row.kind for row in result.all()}


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_startup_syncs_mini_map_and_registers(
        self, booted_db, map_env
    ):
        service = await startup_map()

        assert map_service_module._instance is service
        assert len(service.all_nodes()) == 10

        async with get_session_context() as session:
            kinds = await _province_kinds(session)
        assert set(kinds) == {
            1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 2001, 2002
        }
        assert kinds[2001] == "SEA" and kinds[1001] == "LAND"

        assert list(get_ownership_listeners()) == ["01_map.ownership_log"]
        assert list(get_registration_checks(STAGE_AFTER_FREE)) == [
            "01_map.land_only"
        ]
        assert list(get_registration_checks(STAGE_AFTER_COUNT)) == [
            "01_map.connected_group"
        ]
        assert "01_map" in AdminRegistry.get_reset_hooks()

    @pytest.mark.asyncio
    async def test_startup_twice_does_not_double_register(
        self, booted_db, map_env
    ):
        first = await startup_map()
        second = await startup_map()

        assert second is not first
        assert map_service_module._instance is second
        assert len(get_ownership_listeners()) == 1
        assert len(get_registration_checks(STAGE_AFTER_FREE)) == 1
        assert len(get_registration_checks(STAGE_AFTER_COUNT)) == 1
        assert list(AdminRegistry.get_reset_hooks()).count("01_map") == 1

    @pytest.mark.asyncio
    async def test_default_data_dir_is_repo_data_map(self, monkeypatch):
        monkeypatch.delenv("MAP_DATA_DIR", raising=False)
        assert resolve_data_dir() == REAL_MAP_DIR

    @pytest.mark.asyncio
    async def test_lifespan_boots_with_hooks_registered(
        self, tmp_path, monkeypatch, extension_snapshot, mini_map_config
    ):
        """The real ASGI lifespan: provinces synced, service installed."""
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'live.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
        monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
        monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

        async with LifespanManager(app) as manager:
            assert get_ownership_listeners() != {}
            assert len(
                map_service_module.get_map_service().all_nodes()
            ) == 10
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/health")
                assert resp.status_code == 200


class TestInvM5:
    """DB/manifest divergence is fatal and leaves hooks unregistered."""

    @pytest.mark.asyncio
    async def test_extra_row_in_db_is_fatal(
        self, booted_db, map_env
    ):
        async with get_session_context() as session:
            session.add(Province(id=9999, kind="LAND", nation_id=None))
            await session.commit()

        with pytest.raises(MapDataError) as exc_info:
            await startup_map()

        assert exc_info.value.code == "INV_M5"
        assert "9999" in exc_info.value.message
        assert "reset" in exc_info.value.message
        assert get_ownership_listeners() == {}
        assert "01_map" not in AdminRegistry.get_reset_hooks()

    @pytest.mark.asyncio
    async def test_kind_mismatch_is_fatal(self, booted_db, map_env):
        async with get_session_context() as session:
            # Pre-seed 1001 with the wrong kind; ensure_nodes will not
            # repair it and INV-M5 must stop the boot.
            session.add(Province(id=1001, kind="SEA", nation_id=None))
            await session.commit()

        with pytest.raises(MapDataError) as exc_info:
            await startup_map()

        assert exc_info.value.code == "INV_M5"
        assert "1001" in exc_info.value.message
        assert get_ownership_listeners() == {}
        assert "01_map" not in AdminRegistry.get_reset_hooks()


class TestMapDataFailure:
    @pytest.mark.asyncio
    async def test_corrupted_map_file_stops_startup(
        self, tmp_path, monkeypatch, booted_db, extension_snapshot,
        mini_map_config
    ):
        """Touching an input file breaks inputs_sha256 -> INV_M10."""
        from tests.modules._01_map.conftest import copy_map_mini

        data_dir = copy_map_mini(tmp_path)
        boundary = data_dir / "boundary.yaml"
        boundary.write_text(
            boundary.read_text(encoding="utf-8") + "\n# touched\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAP_DATA_DIR", str(data_dir))

        with pytest.raises(MapDataError) as exc_info:
            await startup_map()

        assert exc_info.value.code == "INV_M10"
        assert get_ownership_listeners() == {}


class TestRealMap:
    @pytest.mark.asyncio
    async def test_real_map_syncs_1123_nodes(
        self, tmp_path, monkeypatch, extension_snapshot
    ):
        """The production map loads and syncs into an empty test DB."""
        db_file = tmp_path / "real_map.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        init_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
        monkeypatch.delenv("MAP_DATA_DIR", raising=False)

        started = time.monotonic()
        try:
            service = await startup_map()
        finally:
            elapsed = time.monotonic() - started
        print(f"\n[real-map startup] {elapsed:.2f}s")

        assert len(service.all_nodes()) == 1123
        async with get_session_context() as session:
            count = await session.execute(
                sa.select(sa.func.count()).select_from(Province)
            )
            assert count.scalar_one() == 1123
        await core_db.get_engine().dispose()
        core_db._engine = None
        core_db._async_session_maker = None
