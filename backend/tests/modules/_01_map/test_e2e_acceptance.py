"""
01_map Issue 6 — end-to-end acceptance on the REAL map.

One continuous scenario over the production ``data/map`` tree and the
real ASGI lifespan (production engine path, no get_session override —
Anti-Mock Guard): VK login -> manifest/ETag -> geometry ->
starting-group check -> registration errors (sea, disconnected) ->
founding on the connected five -> ownership + journal -> admin tick ->
history reads -> nation deletion -> releases + past-turn snapshot.

A second test covers the startup contract: a copy of data/map with one
byte altered in manifest.json must fail the boot with MapDataError
(INV-M6), while the real files boot cleanly (proven by this module's
own lifespan run). The real files are never modified.

Runs on SQLite (tmp file) and, marked, on PostgreSQL via
DATABASE_URL_TEST (tests/fixtures/postgres.py guard chain).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import core.db as core_db
import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._01_map.loader import MapDataError
from modules._01_map.ownership_service import (
    owners_at_turn,
    records_for_province,
)
from tests.fixtures.postgres import (
    ADMIN_VK_ID,
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,
)
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
REAL_MAP_DIR = REPO_ROOT / "data" / "map"

MANIFEST_URL = "/api/v1/map/manifest"
STATE_URL = "/api/v1/map/state"
CHECK_URL = "/api/v1/map/starting-group/check"

# Verified against data/map: a single connected component over
# land/strait edges (Aargau, Bern, Neuchatel, Rhine Valley, Schwarzwald).
CONNECTED_FIVE = [1001, 1122, 1592, 1748, 1796]
# 1001 (Aargau) and 1050 (Arborea, Sardinia) share no path — 2 parts.
DISCONNECTED_PAIR = [1001, 1050]
SEA_NODE = 2087


def _snapshot_process_state() -> dict:
    """Everything the lifespan registers process-wide — restored after."""
    return {
        "views": AdminRegistry.get_state_view_hooks(),
        "resets": AdminRegistry.get_reset_hooks(),
        "handlers": {
            phase: list(handlers)
            for phase, handlers in TickOrchestrator._handlers.items()
        },
        "finalize": TickOrchestrator._finalize_callback,
        "extensions": snapshot_extension_points(),
        "map_service": map_service_module._instance,
    }


def _restore_process_state(saved: dict) -> None:
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved["views"])
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved["resets"])
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved["handlers"])
    TickOrchestrator._finalize_callback = saved["finalize"]
    restore_extension_points(saved["extensions"])
    map_service_module._instance = saved["map_service"]


def _set_test_env(monkeypatch, db_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
    # Unset -> resolve_data_dir() returns the real <repo>/data/map.
    monkeypatch.delenv("MAP_DATA_DIR", raising=False)


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch):
    """
    The real app over its real ASGI lifespan on a migrated tmp SQLite
    file with the REAL map tree (no MAP_DATA_DIR override).
    """
    db_file = tmp_path / "e2e.db"
    # Alembic's env.py reads DATABASE_URL — point it at the tmp file.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    _set_test_env(
        monkeypatch, f"sqlite+aiosqlite:///{db_file.as_posix()}"
    )
    saved = _snapshot_process_state()
    try:
        started = time.monotonic()
        async with LifespanManager(app) as manager:
            print(
                f"\n[e2e startup, real map] "
                f"{time.monotonic() - started:.2f}s"
            )
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                yield client
    finally:
        _restore_process_state(saved)
        if core_db._engine is not None:
            await core_db.get_engine().dispose()
            core_db._engine = None
            core_db._async_session_maker = None


@pytest_asyncio.fixture
async def pg_real_map_client(
    pg_url: str, pg_clean: None, monkeypatch
):
    """Same as ``pg_live_client`` but on the REAL map tree."""
    _set_test_env(monkeypatch, pg_url)
    saved = _snapshot_process_state()
    try:
        async with LifespanManager(app) as manager:
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                yield client
    finally:
        _restore_process_state(saved)


async def _auth(client: AsyncClient, vk_user_id: int) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/vk",
        json={"launch_params": make_launch_params(vk_user_id=vk_user_id)},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _full_scenario(client: AsyncClient) -> None:
    """The shared e2e body — identical on SQLite and PostgreSQL."""
    player = await _auth(client, 424243)
    admin = await _auth(client, ADMIN_VK_ID)

    # -- manifest + ETag + 304 revalidation ---------------------------
    manifest = await client.get(MANIFEST_URL, headers=player)
    assert manifest.status_code == 200
    assert "etag" in manifest.headers
    body = manifest.json()
    assert len(body["nodes"]) == 1067
    assert len(body["edges"]) == 3091  # map2_11: transfers/detach recompute
    etag = manifest.headers["etag"]

    geometry = await client.get(
        f"/api/v1/map/geometry/{body['geometry_version']}",
        headers=player,
    )
    assert geometry.status_code == 200
    geo_body = geometry.json()
    assert len(geo_body["paths"]) == 1067
    # ~1.9 MB of SVG path data — a sane floor proves it is the real file.
    assert len(geometry.content) > 1_000_000

    again = await client.get(
        MANIFEST_URL, headers={**player, "If-None-Match": etag}
    )
    assert again.status_code == 304

    # -- starting-group check ------------------------------------------
    connected = await client.post(
        CHECK_URL, headers=player, json={"province_ids": CONNECTED_FIVE}
    )
    assert connected.status_code == 200
    assert connected.json() == {"connected": True, "component_count": 1}

    split = await client.post(
        CHECK_URL, headers=player, json={"province_ids": DISCONNECTED_PAIR}
    )
    assert split.status_code == 200
    assert split.json() == {"connected": False, "component_count": 2}

    # -- registration refusals ------------------------------------------
    sea = await client.post(
        "/api/v1/nations",
        headers=player,
        json={
            "name": "Sea Claim",
            "color_hex": "#112233",
            "province_ids": [SEA_NODE],
            **VALID_PROFILE,
        },
    )
    assert sea.status_code == 422
    assert sea.json()["code"] == "PROVINCE_NOT_LAND"

    split_reg = await client.post(
        "/api/v1/nations",
        headers=player,
        json={
            "name": "Split Realm",
            "color_hex": "#112233",
            "province_ids": DISCONNECTED_PAIR,
            **VALID_PROFILE,
        },
    )
    assert split_reg.status_code == 422
    assert split_reg.json()["code"] == "STARTING_GROUP_NOT_CONNECTED"

    # -- founding on the connected five ---------------------------------
    created = await client.post(
        "/api/v1/nations",
        headers=player,
        json={
            "name": "Alpine League",
            "color_hex": "#4A90D9",
            "province_ids": CONNECTED_FIVE,
            **VALID_PROFILE,
        },
    )
    assert created.status_code == 201, created.text
    nation = created.json()
    assert sorted(nation["province_ids"]) == sorted(CONNECTED_FIVE)
    nation_id = nation["id"]

    state = await client.get(STATE_URL, headers=player)
    assert state.status_code == 200
    state_body = state.json()
    assert state_body["turn"] == 0
    assert sorted(pid for pid, _ in state_body["owners"]) == sorted(
        CONNECTED_FIVE
    )
    owner_entry = state_body["nations"][0]
    assert owner_entry["id"] == nation_id
    assert owner_entry["name"] == "Alpine League"
    assert owner_entry["color_hex"] == "#4A90D9"

    # -- the journal through the module's service ------------------------
    async with get_session_context() as session:
        for pid in CONNECTED_FIVE:
            rows = await records_for_province(session, pid)
            assert len(rows) == 1
            assert rows[0].turn_number == 0
            assert rows[0].prev_nation_id is None
            assert rows[0].new_nation_id == nation_id
            assert rows[0].new_nation_name == "Alpine League"
        owners0 = await owners_at_turn(session, 0)
    assert sorted(owners0) == sorted(CONNECTED_FIVE)

    # -- advance the turn through the admin path ------------------------
    tick = await client.post("/api/v1/admin/tick/run", headers=admin)
    assert tick.status_code == 200
    assert tick.json()["ok"] is True
    assert tick.json()["current_turn"] == 1

    # Turn 0 keeps the owner as at turn 0; a future turn is out of range.
    past = await client.get(STATE_URL, params={"turn": 0}, headers=player)
    assert past.status_code == 200
    assert sorted(p for p, _ in past.json()["owners"]) == sorted(
        CONNECTED_FIVE
    )
    out_of_range = await client.get(
        STATE_URL, params={"turn": 2}, headers=player
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["code"] == "TURN_OUT_OF_RANGE"

    # -- deletion: releases journaled, history preserved -----------------
    deleted = await client.request(
        "DELETE",
        "/api/v1/nations/me",
        headers=player,
        json={"confirm": True},
    )
    assert deleted.status_code == 204

    async with get_session_context() as session:
        for pid in CONNECTED_FIVE:
            rows = await records_for_province(session, pid)
            assert len(rows) == 2
            release = rows[1]
            assert release.turn_number == 1
            assert release.new_nation_id is None
            assert release.prev_nation_id == nation_id

    current = await client.get(STATE_URL, headers=player)
    assert current.status_code == 200
    assert current.json()["owners"] == []
    assert current.json()["nations"] == []

    # The past-turn view still shows the owner — with id = null now
    # that the nation is gone (name/colour survive on the journal).
    past_after_delete = await client.get(
        STATE_URL, params={"turn": 0}, headers=player
    )
    assert past_after_delete.status_code == 200
    past_body = past_after_delete.json()
    assert sorted(p for p, _ in past_body["owners"]) == sorted(
        CONNECTED_FIVE
    )
    assert past_body["nations"] == [
        {"id": None, "name": "Alpine League", "color_hex": "#4A90D9"}
    ]


class TestE2EAcceptance:
    @pytest.mark.asyncio
    async def test_full_lifecycle_on_real_map_sqlite(self, live_client):
        started = time.monotonic()
        await _full_scenario(live_client)
        print(f"\n[e2e scenario, SQLite] {time.monotonic() - started:.2f}s")


@pytest.mark.postgres
class TestE2EAcceptancePostgres:
    @pytest.mark.asyncio
    async def test_full_lifecycle_on_real_map_pg(self, pg_real_map_client):
        started = time.monotonic()
        await _full_scenario(pg_real_map_client)
        print(f"\n[e2e scenario, PostgreSQL] {time.monotonic() - started:.2f}s")


class TestStartupFailure:
    @pytest.mark.asyncio
    async def test_altered_manifest_byte_fails_boot(
        self, tmp_path, monkeypatch
    ):
        """
        A copy of data/map with ONE byte flipped in manifest.json must
        fail startup with MapDataError (INV-M6: geometry pin mismatch);
        the real files are never touched.
        """
        data_copy = tmp_path / "map_copy"
        shutil.copytree(REAL_MAP_DIR, data_copy)
        manifest_path = data_copy / "manifest.json"
        raw = manifest_path.read_bytes()
        # Flip the first hex digit of "geometry_version": "a18a…" -> "b18a…".
        marker = b'"geometry_version"'
        pos = raw.index(marker) + len(marker)
        colon = raw.index(b":", pos)
        quote = raw.index(b'"', colon) + 1
        corrupted = raw[:quote] + b"b" + raw[quote + 1 :]
        assert corrupted != raw and len(corrupted) == len(raw)
        manifest_path.write_bytes(corrupted)

        db_file = tmp_path / "corrupt.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )
        command.upgrade(
            Config(str(BACKEND_DIR / "alembic.ini")), "head"
        )
        _set_test_env(
            monkeypatch, f"sqlite+aiosqlite:///{db_file.as_posix()}"
        )
        monkeypatch.setenv("MAP_DATA_DIR", str(data_copy))
        saved = _snapshot_process_state()
        try:
            with pytest.raises(MapDataError) as exc_info:
                async with LifespanManager(app):
                    pass
            assert exc_info.value.code == "INV_M6"
        finally:
            _restore_process_state(saved)
            if core_db._engine is not None:
                await core_db.get_engine().dispose()
                core_db._engine = None
                core_db._async_session_maker = None

    @pytest.mark.asyncio
    async def test_real_files_boot(self, tmp_path, monkeypatch):
        """The unmodified data/map boots — the e2e's positive control."""
        db_file = tmp_path / "boot.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        _set_test_env(
            monkeypatch, f"sqlite+aiosqlite:///{db_file.as_posix()}"
        )
        saved = _snapshot_process_state()
        try:
            started = time.monotonic()
            async with LifespanManager(app) as manager:
                elapsed = time.monotonic() - started
                print(f"\n[real-map lifespan boot] {elapsed:.2f}s")
                assert (
                    len(map_service_module.get_map_service().all_nodes())
                    == 1067
                )
                transport = ASGITransport(app=manager.app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    assert (
                        await client.get("/health")
                    ).status_code == 200
        finally:
            _restore_process_state(saved)
            if core_db._engine is not None:
                await core_db.get_engine().dispose()
                core_db._engine = None
                core_db._async_session_maker = None
