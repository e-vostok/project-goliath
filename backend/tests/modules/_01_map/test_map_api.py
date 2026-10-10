"""
HTTP API tests for 01_map Issue 4 (Spec Part 5).

Two deployment shapes, both real (Anti-Mock Guard):

- ``client`` — the ASGI app over the shared in-memory DB fixture with
  ``get_session`` overridden (the test_router.py pattern); the mini-map
  MapService and the real module hooks are installed by
  ``map_installed``.
- ``live_client`` — the real ASGI lifespan on a migrated tmp SQLite
  file (the test_map_startup.py pattern), so auth, nation writes,
  journal rows and admin ticks all run on the production code path.

The real-map class boots the lifespan on ``data/map`` for the
size/timing smoke of Spec §3.6.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import modules._01_map.api_service as api_service
import core.db as core_db
from core.db import get_session
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.models import GameClock, Province
from modules._00_core.hooks import OwnershipChange
from modules._01_map.loader import load_map_data
from modules._01_map.schemas import (
    MapBordersDTO,
    MapGeometryDTO,
    MapManifestDTO,
    MapStateDTO,
    StartingGroupCheckResponse,
)
from modules._01_map.service import (
    MapService,
    init_map_service,
    record_changes,
)
from modules._01_map.hooks import register_map_hooks
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    bearer_headers,
    make_launch_params,
    seed_player,
)
from tests.modules._01_map.conftest import (
    FIXTURE_DIR,
    load_borders,
    load_geometry,
    load_manifest,
    map_config,
    map_config_disconnected,
    save_manifest,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
REAL_MAP_DIR = REPO_ROOT / "data" / "map"

ADMIN_VK_ID = 515151

MANIFEST_URL = "/api/v1/map/manifest"
GEOMETRY_URL = "/api/v1/map/geometry/{version}"
STATE_URL = "/api/v1/map/state"
CHECK_URL = "/api/v1/map/starting-group/check"


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide VK/JWT secrets for every test."""
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


@pytest.fixture
def map_installed(extension_snapshot, flat_map_service, config):
    """Install the mini-map service + the real module hooks."""
    register_map_hooks(flat_map_service, config)
    init_map_service(flat_map_service)
    saved = (api_service._payloads, api_service._payloads_service)
    yield flat_map_service
    api_service._payloads, api_service._payloads_service = saved


@pytest_asyncio.fixture
async def client(map_db_session, map_installed):
    """HTTP client on the shared test session (provinces synced)."""
    async def _override_get_session():
        yield map_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _set_turn(session, turn: int) -> None:
    """Bump the game-clock singleton (created when absent)."""
    result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    clock = result.scalar_one_or_none()
    if clock is None:
        session.add(
            GameClock(
                id=1,
                current_turn=turn,
                next_tick_at=datetime.now(timezone.utc)
                + timedelta(days=1),
            )
        )
    else:
        clock.current_turn = turn
    await session.flush()


async def _create_nation(
    client, player, name: str, color_hex: str, province_ids: list[int]
):
    resp = await client.post(
        "/api/v1/nations",
        headers=bearer_headers(player.id),
        json={
            "name": name,
            "color_hex": color_hex,
            "province_ids": province_ids,
            **VALID_PROFILE,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _auth_headers(client, vk_user_id: int) -> dict[str, str]:
    """Register/log in a player through the real VK auth endpoint."""
    resp = await client.post(
        "/api/v1/auth/vk",
        json={"launch_params": make_launch_params(vk_user_id=vk_user_id)},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def live_client(
    tmp_path, monkeypatch, extension_snapshot, mini_map_config
):
    """
    The real ASGI lifespan on a migrated tmp SQLite file — the
    production engine path, no get_session override. Admin allowlist
    enabled so the tick can be advanced via POST /admin/tick/run.
    ``mini_map_config`` swaps view.frame for a rect inside the mini
    fixture's view_box.
    """
    db_file = tmp_path / "live.db"
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
    )
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}"
    )
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))

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

    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize
    await core_db.get_engine().dispose()
    core_db._engine = None
    core_db._async_session_maker = None


class TestManifest:
    """GET /api/v1/map/manifest (Spec 5: DTO, rules, ETag/304)."""

    async def test_manifest_shape_and_content(
        self, client, map_db_session, map_installed
    ):
        player = await seed_player(map_db_session)
        resp = await client.get(
            MANIFEST_URL, headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        dto = MapManifestDTO.model_validate(resp.json())

        manifest = load_manifest(FIXTURE_DIR)
        assert dto.schema_version == manifest["schema_version"]
        assert dto.geometry_version == map_installed.geometry_version
        assert dto.view_box == manifest["view_box"]
        assert dto.playable_bbox == manifest["playable_bbox"]
        assert len(dto.nodes) == 10
        assert len(dto.edges) == 10
        # Deterministic ordering: nodes ascending by id.
        assert [n.id for n in dto.nodes] == sorted(
            n["id"] for n in manifest["nodes"]
        )
        node = dto.nodes[0]
        assert node.id == 1001 and node.key == "mini_alpha"
        assert node.kind == "LAND" and node.name == "Mini Alpha"
        assert node.name_ru is None
        assert node.anchor == [5.0, 25.0]
        assert node.bbox == [0.0, 20.0, 10.0, 30.0]
        assert node.area == 100.0
        sea = next(n for n in dto.nodes if n.id == 2001)
        assert sea.kind == "SEA"
        # The manifest field `len` is never exposed.
        assert all("len" not in e.model_dump() for e in dto.edges)
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["etag"] == api_service.get_api_payloads().manifest_etag

    async def test_strait_multipliers(self, client, map_db_session):
        """Explicit 0.3, default 0.5 from config, null elsewhere."""
        player = await seed_player(map_db_session)
        resp = await client.get(
            MANIFEST_URL, headers=bearer_headers(player.id)
        )
        edges = {
            (e["a"], e["b"]): e for e in resp.json()["edges"]
        }
        assert edges[(1005, 1006)]["multiplier"] == 0.5
        assert edges[(1006, 1007)]["multiplier"] == 0.3
        for key, edge in edges.items():
            if edge["type"] != "strait":
                assert edge["multiplier"] is None
        assert edges[(1005, 1006)]["name"]
        # `len` must not leak into the wire body at all.
        assert '"len"' not in resp.text

    async def test_rules_built_from_config(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.get(
            MANIFEST_URL, headers=bearer_headers(player.id)
        )
        config = map_config()
        rules = resp.json()["rules"]
        assert rules["frame"] == [
            config.view.frame.x,
            config.view.frame.y,
            config.view.frame.width,
            config.view.frame.height,
        ]
        assert rules["zoom_max"] == config.view.zoom_max
        assert rules["pan_margin_fraction"] == config.view.pan_margin_fraction
        assert rules["label_min_width_px"] == config.view.label_min_width_px
        assert rules["search_min_chars"] == config.view.search_min_chars
        assert rules["search_max_results"] == config.view.search_max_results
        assert rules["require_connected_start"] == (
            config.starting_group.require_connected
        )
        assert rules["big_window_enabled"] == config.big_window.enabled
        assert rules["hover_fill_opacity"] == config.hover.fill_opacity
        assert rules["hover_stroke_enabled"] == config.hover.stroke_enabled
        assert rules["colors"]["sea"] == config.colors.sea
        assert rules["colors"]["land_underlay"] == config.colors.land_underlay
        borders = rules["borders"]
        for key in (
            "internal_width",
            "internal_opacity",
            "internal_color",
            "state_width",
            "state_color",
            "coast_width",
            "coast_color",
        ):
            assert borders[key] == getattr(config.borders, key)
        selection = rules["selection"]
        for key in (
            "pulse_min_opacity",
            "pulse_max_opacity",
            "pulse_period_s",
            "picked_opacity",
        ):
            assert selection[key] == getattr(config.selection, key)
        refresh = rules["refresh"]
        for key in (
            "tick_refresh_delay_seconds",
            "tick_refresh_jitter_seconds",
            "retry_delay_seconds",
            "max_retries",
            "stale_after_seconds",
        ):
            assert refresh[key] == getattr(config.refresh, key)

    async def test_etag_304_cycle(self, client, map_db_session):
        player = await seed_player(map_db_session)
        headers = bearer_headers(player.id)
        first = await client.get(MANIFEST_URL, headers=headers)
        etag = first.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')

        second = await client.get(
            MANIFEST_URL, headers={**headers, "If-None-Match": etag}
        )
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["etag"] == etag
        assert second.headers["cache-control"] == "no-cache"

    @pytest.mark.parametrize(
        "header",
        [
            '"deadbeefdeadbeef", {etag}',  # a list of tags
            'W/{etag}',                    # weak tag
            '*',                           # wildcard
            'W/"other", W/{etag}',         # weak inside a list
        ],
    )
    async def test_if_none_match_forms(
        self, client, map_db_session, header
    ):
        player = await seed_player(map_db_session)
        headers = bearer_headers(player.id)
        etag = (
            await client.get(MANIFEST_URL, headers=headers)
        ).headers["etag"]
        resp = await client.get(
            MANIFEST_URL,
            headers={**headers, "If-None-Match": header.format(etag=etag)},
        )
        assert resp.status_code == 304

    async def test_if_none_match_miss_returns_200(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        resp = await client.get(
            MANIFEST_URL,
            headers={
                **bearer_headers(player.id),
                "If-None-Match": '"0000000000000000"',
            },
        )
        assert resp.status_code == 200

    async def test_etag_stable_across_rebuilds(
        self, client, map_db_session, flat_map_service, config
    ):
        """Same files + same config -> same tag on a fresh service."""
        player = await seed_player(map_db_session)
        etag = (
            await client.get(
                MANIFEST_URL, headers=bearer_headers(player.id)
            )
        ).headers["etag"]
        again = api_service.build_api_payloads(
            MapService(load_map_data(FIXTURE_DIR, config), config)
        )
        assert again.manifest_etag == etag
        assert again.manifest_body == (
            api_service.get_api_payloads().manifest_body
        )

    async def test_etag_changes_when_rules_change(
        self, client, map_db_session, flat_map_service, config
    ):
        """A config-only edit changes the tag though files did not."""
        player = await seed_player(map_db_session)
        etag = (
            await client.get(
                MANIFEST_URL, headers=bearer_headers(player.id)
            )
        ).headers["etag"]
        changed = config.model_copy(
            update={
                "colors": config.colors.model_copy(
                    update={"hover": "#EEEEEE"}
                )
            }
        )
        other = api_service.build_api_payloads(
            MapService(flat_map_service.map_data, changed)
        )
        assert other.manifest_etag != etag

    async def test_manifest_served_gzipped(self, client, map_db_session):
        """GZipMiddleware compresses bodies >= 1000 bytes."""
        player = await seed_player(map_db_session)
        plain = await client.get(
            MANIFEST_URL,
            headers={
                **bearer_headers(player.id),
                "Accept-Encoding": "identity",
            },
        )
        zipped = await client.get(
            MANIFEST_URL,
            headers={
                **bearer_headers(player.id),
                "Accept-Encoding": "gzip",
            },
        )
        assert "content-encoding" not in plain.headers
        assert zipped.headers["content-encoding"] == "gzip"
        assert int(zipped.headers["content-length"]) < len(plain.content)


def test_names_ru_reach_node_dto(mini_dir, config):
    """map2_3: ``name_ru`` written by import_names into the manifest is
    loaded and exposed in ``MapNodeDTO.name_ru`` (the search/picker read
    it from the manifest payload — nothing else stores names)."""
    names = {"mini_alpha": "Альфа-Земля", "mini_beta": "Бета Ёлка"}
    doc = load_manifest(mini_dir)
    for node in doc["nodes"]:
        if node["key"] in names:
            node["name_ru"] = names[node["key"]]
    save_manifest(mini_dir, doc)

    service = MapService(load_map_data(mini_dir, config), config)
    body = api_service.build_api_payloads(service).manifest_body
    dto = MapManifestDTO.model_validate_json(body)

    got = {n.key: n.name_ru for n in dto.nodes}
    assert got["mini_alpha"] == "Альфа-Земля"
    assert got["mini_beta"] == "Бета Ёлка"
    assert got["mini_gamma"] is None
    assert service.map_data.nodes[1001].name_ru == "Альфа-Земля"


class TestGeometry:
    """GET /api/v1/map/geometry/{version} (Spec 5: immutable body)."""

    async def test_current_version_semantics(
        self, client, map_db_session, map_installed
    ):
        player = await seed_player(map_db_session)
        version = map_installed.geometry_version
        resp = await client.get(
            f"/api/v1/map/geometry/{version}",
            headers=bearer_headers(player.id),
        )

        assert resp.status_code == 200
        dto = MapGeometryDTO.model_validate(resp.json())
        assert dto.version == version
        on_disk = load_geometry(FIXTURE_DIR)
        assert resp.json()["paths"] == on_disk["paths"]
        assert dto.outside == on_disk["outside"]
        # paths keys are exactly the loaded node ids.
        assert set(dto.paths) == {
            n.id for n in map_installed.all_nodes()
        }
        assert resp.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )
        assert resp.headers["etag"] == f'"{version}"'

    async def test_unknown_version_404(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.get(
            "/api/v1/map/geometry/ffffffffffff",
            headers=bearer_headers(player.id),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "MAP_VERSION_UNKNOWN"

    async def test_version_from_manifest_works_end_to_end(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        headers = bearer_headers(player.id)
        manifest = (
            await client.get(MANIFEST_URL, headers=headers)
        ).json()
        resp = await client.get(
            f"/api/v1/map/geometry/{manifest['geometry_version']}",
            headers=headers,
        )
        assert resp.status_code == 200


class TestBorders:
    """GET /api/v1/map/borders/{version} (map2_1B: immutable body)."""

    async def test_current_version_semantics(
        self, client, map_db_session, map_installed
    ):
        player = await seed_player(map_db_session)
        version = map_installed.borders_version
        resp = await client.get(
            f"/api/v1/map/borders/{version}",
            headers=bearer_headers(player.id),
        )

        assert resp.status_code == 200
        dto = MapBordersDTO.model_validate(resp.json())
        assert dto.version == version
        on_disk = load_borders(FIXTURE_DIR)
        assert resp.json()["pairs"] == on_disk["pairs"]
        assert resp.json()["coasts"] == on_disk["coasts"]
        assert resp.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )
        assert resp.headers["etag"] == f'"{version}"'

    async def test_unknown_version_404(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.get(
            "/api/v1/map/borders/ffffffffffff",
            headers=bearer_headers(player.id),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "MAP_VERSION_UNKNOWN"

    async def test_version_from_manifest_works_end_to_end(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        headers = bearer_headers(player.id)
        manifest = (
            await client.get(MANIFEST_URL, headers=headers)
        ).json()
        resp = await client.get(
            f"/api/v1/map/borders/{manifest['borders_version']}",
            headers=headers,
        )
        assert resp.status_code == 200


class TestState:
    """GET /api/v1/map/state — current and journal turns."""

    async def test_empty_world(self, client, map_db_session, map_installed):
        player = await seed_player(map_db_session)
        resp = await client.get(
            STATE_URL, headers=bearer_headers(player.id)
        )
        assert resp.status_code == 200
        dto = MapStateDTO.model_validate(resp.json())
        assert dto.turn == 0
        assert dto.owners == []
        assert dto.nations == []
        assert dto.geometry_version == map_installed.geometry_version

    async def test_current_state_two_nations(
        self, client, map_db_session
    ):
        player_a = await seed_player(map_db_session, vk_user_id=8101)
        player_b = await seed_player(map_db_session, vk_user_id=8102)
        nation_a = await _create_nation(
            client, player_a, "Alpha", "#AA1100", [1001, 1002]
        )
        nation_b = await _create_nation(
            client, player_b, "Bravo", "#2211BB", [1003]
        )

        resp = await client.get(
            STATE_URL, headers=bearer_headers(player_a.id)
        )
        assert resp.status_code == 200
        dto = MapStateDTO.model_validate(resp.json())
        assert dto.turn == 0
        assert dto.owners == [[1001, 0], [1002, 0], [1003, 1]]
        assert [str(n.id) for n in dto.nations] == [
            nation_a["id"], nation_b["id"]
        ]
        assert dto.nations[0].name == "Alpha"
        assert dto.nations[0].color_hex == "#AA1100"
        assert dto.nations[1].name == "Bravo"
        # SEA nodes are never listed.
        assert all(pid < 2001 for pid, _ in dto.owners)

    async def test_past_turn_from_journal(
        self, client, map_db_session
    ):
        """
        Scripted journal rows: claims at turns 0 and 1, a release at
        turn 2. Journal nation ids absent from the live table resolve
        to ``id: null``.
        """
        player = await seed_player(map_db_session)
        await record_changes(
            map_db_session,
            [
                OwnershipChange(
                    province_id=1001,
                    prev_nation_id=None,
                    new_nation_id="nation-gone",
                    new_name="Gone Realm",
                    new_color="#101010",
                    turn=0,
                ),
                OwnershipChange(
                    province_id=1002,
                    prev_nation_id=None,
                    new_nation_id="nation-b",
                    new_name="B Realm",
                    new_color="#202020",
                    turn=1,
                ),
                OwnershipChange(
                    province_id=1001,
                    prev_nation_id="nation-gone",
                    new_nation_id=None,
                    new_name=None,
                    new_color=None,
                    turn=2,
                ),
            ],
        )
        await _set_turn(map_db_session, 3)
        headers = bearer_headers(player.id)

        at_0 = (
            await client.get(
                STATE_URL, params={"turn": 0}, headers=headers
            )
        ).json()
        assert at_0["turn"] == 0
        assert at_0["owners"] == [[1001, 0]]
        assert at_0["nations"] == [
            {"id": None, "name": "Gone Realm", "color_hex": "#101010"}
        ]

        at_1 = (
            await client.get(
                STATE_URL, params={"turn": 1}, headers=headers
            )
        ).json()
        assert at_1["owners"] == [[1001, 0], [1002, 1]]
        assert at_1["nations"][1]["name"] == "B Realm"
        # Two distinct journal ids stay two entries even though both
        # resolve to id=null (unique by (id, name, color)).
        assert [n["id"] for n in at_1["nations"]] == [None, None]

        at_2 = (
            await client.get(
                STATE_URL, params={"turn": 2}, headers=headers
            )
        ).json()
        assert at_2["owners"] == [[1002, 0]]
        assert at_2["nations"] == [
            {"id": None, "name": "B Realm", "color_hex": "#202020"}
        ]

    async def test_turn_equals_current_matches_default(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        await _create_nation(
            client, player, "Alpha", "#AA1100", [1001]
        )
        headers = bearer_headers(player.id)
        plain = (await client.get(STATE_URL, headers=headers)).json()
        explicit = (
            await client.get(
                STATE_URL,
                params={"turn": plain["turn"]},
                headers=headers,
            )
        ).json()
        assert explicit == plain

    async def test_retired_node_never_in_state(
        self, client, map_db_session
    ):
        """
        Spec 1.9: /map/state never returns owners of ids outside the
        active manifest — neither a live provinces row (a retired node's
        leftover) nor a journal entry for a withdrawn node. The owner's
        real provinces and nation entry survive the filtering.
        """
        player = await seed_player(map_db_session)
        nation = await _create_nation(
            client, player, "Alpha", "#AA1100", [1001]
        )
        # An owned row on an id the manifest does not know — the shape
        # a retired-but-owned leftover would have (startup normally
        # refuses this; the read path must still be safe).
        map_db_session.add(
            Province(id=9999, kind="LAND", nation_id=nation["id"])
        )
        # A journal claim on the retired id back at turn 0 (a withdrawn
        # node the journal legitimately remembers).
        await record_changes(
            map_db_session,
            [
                OwnershipChange(
                    province_id=9999,
                    prev_nation_id=None,
                    new_nation_id="nation-old",
                    new_name="Old Realm",
                    new_color="#303030",
                    turn=0,
                ),
            ],
        )
        await _set_turn(map_db_session, 1)
        headers = bearer_headers(player.id)

        current = MapStateDTO.model_validate(
            (await client.get(STATE_URL, headers=headers)).json()
        )
        assert current.owners == [[1001, 0]]
        assert [str(n.id) for n in current.nations] == [nation["id"]]

        at_0 = (
            await client.get(
                STATE_URL, params={"turn": 0}, headers=headers
            )
        ).json()
        # turn 0's snapshot holds 1001 (claimed at registration) and
        # the withdrawn 9999 — only the active id is returned, and the
        # retired node's journal nation disappears with it.
        assert at_0["owners"] == [[1001, 0]]
        assert [n["name"] for n in at_0["nations"]] == ["Alpha"]

    async def test_turn_out_of_range(self, client, map_db_session):
        player = await seed_player(map_db_session)
        await _set_turn(map_db_session, 2)
        headers = bearer_headers(player.id)
        for turn in (-1, 3):
            resp = await client.get(
                STATE_URL, params={"turn": turn}, headers=headers
            )
            assert resp.status_code == 422
            assert resp.json()["code"] == "TURN_OUT_OF_RANGE"
        resp = await client.get(
            STATE_URL, params={"turn": "abc"}, headers=headers
        )
        assert resp.status_code == 422
        # The framework's validation shape, not a domain code.
        assert "code" not in resp.json()


class TestStartingGroupCheck:
    """POST /api/v1/map/starting-group/check (Spec 3.3)."""

    async def test_connected_chain(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 1002, 1003]},
        )
        assert resp.status_code == 200
        dto = StartingGroupCheckResponse.model_validate(resp.json())
        assert dto.connected is True and dto.component_count == 1

    async def test_broken_chain_two_components(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 1005]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"connected": False, "component_count": 2}

    @pytest.mark.parametrize("pair", [[1005, 1006], [1006, 1007]])
    async def test_strait_joined_pair_connected(
        self, client, map_db_session, pair
    ):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": pair},
        )
        assert resp.status_code == 200
        assert resp.json() == {"connected": True, "component_count": 1}

    async def test_single_province_connected(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1008]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"connected": True, "component_count": 1}

    async def test_duplicates_ignored(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 1001, 1002]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"connected": True, "component_count": 1}

    async def test_sea_id_rejected(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 2001]},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "PROVINCE_NOT_LAND"

    async def test_unknown_id_404(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 9999]},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "PROVINCE_NOT_FOUND"

    async def test_empty_list_422(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": []},
        )
        assert resp.status_code == 422

    async def test_list_capped_by_node_count(
        self, client, map_db_session
    ):
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": list(range(1001, 1012))},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "PROVINCE_COUNT_OUT_OF_RANGE"

    async def test_real_connectivity_when_not_required(
        self, client, map_db_session, flat_map_service
    ):
        """require_connected=false: real connectivity still reported."""
        service = MapService(
            flat_map_service.map_data, map_config_disconnected()
        )
        init_map_service(service)
        player = await seed_player(map_db_session)
        resp = await client.post(
            CHECK_URL,
            headers=bearer_headers(player.id),
            json={"province_ids": [1001, 1005]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"connected": False, "component_count": 2}


class TestProvinceDtoKind:
    """ProvinceDTO.kind on GET /api/v1/provinces (Spec 5 §3.5)."""

    async def test_kinds_returned(self, client, map_db_session):
        player = await seed_player(map_db_session)
        resp = await client.get(
            "/api/v1/provinces", headers=bearer_headers(player.id)
        )
        assert resp.status_code == 200
        body = resp.json()
        by_id = {p["id"]: p for p in body}
        assert by_id[1001]["kind"] == "LAND"
        assert by_id[2001]["kind"] == "SEA"
        assert by_id[1001]["nation_id"] is None


class TestContract:
    """OpenAPI shape, absent reserve endpoints, auth on every route."""

    async def test_openapi_lists_exactly_the_map_routes(
        self, client, map_db_session
    ):
        resp = await client.get("/openapi.json")
        paths = resp.json()["paths"]
        map_paths = {
            p for p in paths if p.startswith("/api/v1/map")
        }
        assert map_paths == {
            "/api/v1/map/manifest",
            "/api/v1/map/geometry/{version}",
            "/api/v1/map/borders/{version}",
            "/api/v1/map/state",
            "/api/v1/map/starting-group/check",
        }
        assert "get" in paths["/api/v1/map/manifest"]
        assert "post" in paths["/api/v1/map/starting-group/check"]

    @pytest.mark.parametrize(
        "url",
        ["/api/v1/map/big-window/pass", "/api/v1/auth/pass"],
    )
    async def test_reserve_pass_endpoints_absent(
        self, client, map_db_session, url
    ):
        """Removed in Spec 1.6 — 404 by absence of the route."""
        player = await seed_player(map_db_session)
        resp = await client.post(
            url, headers=bearer_headers(player.id), json={}
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("GET", MANIFEST_URL, None),
            ("GET", "/api/v1/map/geometry/dd7d785f4355", None),
            ("GET", "/api/v1/map/borders/dd7d785f4355", None),
            ("GET", STATE_URL, None),
            ("POST", CHECK_URL, {"province_ids": [1001]}),
        ],
    )
    async def test_every_route_requires_auth(
        self, client, method, url, body
    ):
        resp = await client.request(method, url, json=body)
        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"


class TestLiveHistory:
    """
    The full create -> tick -> rename -> tick -> delete timeline on the
    real lifespan: journal rows come from the Issue-3 hooks and turns
    advance through the admin tick path.
    """

    async def test_past_turns_and_deleted_nation(self, live_client):
        admin = await _auth_headers(live_client, ADMIN_VK_ID)
        player_a = await _auth_headers(live_client, 8101)
        player_b = await _auth_headers(live_client, 8102)

        nation_a = (
            await live_client.post(
                "/api/v1/nations",
                headers=player_a,
                json={
                    "name": "Alpha",
                    "color_hex": "#AA1100",
                    "province_ids": [1001, 1002],
                    **VALID_PROFILE,
                },
            )
        ).json()
        nation_b = (
            await live_client.post(
                "/api/v1/nations",
                headers=player_b,
                json={
                    "name": "Bravo",
                    "color_hex": "#2211BB",
                    "province_ids": [1003],
                    **VALID_PROFILE,
                },
            )
        ).json()

        async def state(turn=None):
            resp = await live_client.get(
                STATE_URL,
                params={} if turn is None else {"turn": turn},
                headers=player_b,
            )
            assert resp.status_code == 200, resp.text
            return resp.json()

        async def tick():
            resp = await live_client.post(
                "/api/v1/admin/tick/run", headers=admin
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["ok"] is True
            return resp.json()["current_turn"]

        # --- turn 0: both nations claimed --------------------------
        now = await state()
        assert now["turn"] == 0
        assert now["owners"] == [
            [1001, 0], [1002, 0], [1003, 1]
        ]
        assert [n["name"] for n in now["nations"]] == [
            "Alpha", "Bravo"
        ]

        # --- tick -> 1, then rename Alpha -> Beta ------------------
        assert await tick() == 1
        resp = await live_client.patch(
            "/api/v1/nations/me",
            headers=player_a,
            json={"name": "Beta", "color_hex": "#CC0011"},
        )
        assert resp.status_code == 200

        at_0 = await state(turn=0)
        assert at_0["nations"][0]["name"] == "Alpha"
        assert at_0["nations"][0]["color_hex"] == "#AA1100"
        assert at_0["nations"][0]["id"] == nation_a["id"]

        current = await state()
        assert current["turn"] == 1
        # The live row carries the new name; the journal keeps the old.
        assert current["nations"][0]["name"] == "Beta"

        # --- tick -> 2, then delete the nation ---------------------
        assert await tick() == 2
        resp = await live_client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=player_a,
            json={"confirm": True},
        )
        assert resp.status_code == 204

        current = await state()
        assert current["turn"] == 2
        assert current["owners"] == [[1003, 0]]
        assert current["nations"] == [
            {
                "id": nation_b["id"],
                "name": "Bravo",
                "color_hex": "#2211BB",
            }
        ]

        # Past turns keep the deleted nation with id = null.
        at_0 = await state(turn=0)
        assert at_0["owners"] == [[1001, 0], [1002, 0], [1003, 1]]
        assert at_0["nations"][0] == {
            "id": None,
            "name": "Alpha",
            "color_hex": "#AA1100",
        }
        assert at_0["nations"][1]["id"] == nation_b["id"]

        at_1 = await state(turn=1)
        # The journal records ownership events only: the rename does
        # not appear in past snapshots (Spec 3.5 formula).
        assert at_1["nations"][0]["name"] == "Alpha"
        assert at_1["nations"][0]["id"] is None

        at_current = await state(turn=2)
        assert at_current == current

        # --- out of range ------------------------------------------
        for turn in (-1, 3):
            resp = await live_client.get(
                STATE_URL, params={"turn": turn}, headers=player_b
            )
            assert resp.status_code == 422
            assert resp.json()["code"] == "TURN_OUT_OF_RANGE"


class TestRealMap:
    """
    Real ``data/map`` smoke (Spec §3.6): manifest/geometry succeed,
    report plain + gzip body sizes and p50 latency over 20 requests.
    """

    async def test_real_map_sizes_and_latency(
        self, tmp_path, monkeypatch, extension_snapshot
    ):
        db_file = tmp_path / "real.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}"
        )
        monkeypatch.delenv("MAP_DATA_DIR", raising=False)
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))

        saved_handlers = {
            phase: list(handlers)
            for phase, handlers in TickOrchestrator._handlers.items()
        }
        saved_finalize = TickOrchestrator._finalize_callback

        try:
            async with LifespanManager(app) as manager:
                transport = ASGITransport(app=manager.app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    headers = await _auth_headers(client, 9001)

                    plain = await client.get(
                        MANIFEST_URL,
                        headers={
                            **headers, "Accept-Encoding": "identity"
                        },
                    )
                    assert plain.status_code == 200
                    body = plain.json()
                    assert len(body["nodes"]) == 1067
                    assert len(body["edges"]) == 3091  # map2_11 edge delta
                    version = body["geometry_version"]
                    manifest_plain = len(plain.content)

                    zipped = await client.get(
                        MANIFEST_URL,
                        headers={**headers, "Accept-Encoding": "gzip"},
                    )
                    assert zipped.headers["content-encoding"] == "gzip"
                    manifest_gzip = int(
                        zipped.headers["content-length"]
                    )

                    revalidated = await client.get(
                        MANIFEST_URL,
                        headers={
                            **headers,
                            "If-None-Match": plain.headers["etag"],
                            "Accept-Encoding": "identity",
                        },
                    )
                    assert revalidated.status_code == 304
                    assert revalidated.content == b""

                    geo_plain = await client.get(
                        f"/api/v1/map/geometry/{version}",
                        headers={
                            **headers, "Accept-Encoding": "identity"
                        },
                    )
                    assert geo_plain.status_code == 200
                    geometry_plain = len(geo_plain.content)
                    geo_zip = await client.get(
                        f"/api/v1/map/geometry/{version}",
                        headers={**headers, "Accept-Encoding": "gzip"},
                    )
                    assert (
                        geo_zip.headers["content-encoding"] == "gzip"
                    )
                    geometry_gzip = int(
                        geo_zip.headers["content-length"]
                    )

                    timings = []
                    for _ in range(20):
                        started = time.perf_counter()
                        resp = await client.get(
                            MANIFEST_URL, headers=headers
                        )
                        timings.append(
                            (time.perf_counter() - started) * 1000
                        )
                        assert resp.status_code == 200
                    p50 = statistics.median(timings)

                    print(
                        "\n[real-map] manifest: "
                        f"{manifest_plain} B plain / "
                        f"{manifest_gzip} B gzip; "
                        f"geometry: {geometry_plain} B plain / "
                        f"{geometry_gzip} B gzip; "
                        f"manifest p50 over 20: {p50:.1f} ms"
                    )
        finally:
            TickOrchestrator._handlers.clear()
            TickOrchestrator._handlers.update(saved_handlers)
            TickOrchestrator._finalize_callback = saved_finalize
            if core_db._engine is not None:
                await core_db.get_engine().dispose()
                core_db._engine = None
                core_db._async_session_maker = None
