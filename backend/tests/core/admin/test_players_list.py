"""
HTTP tests for GET /api/v1/admin/players — the panel's «Игроки» list
(0.11.0 unit 6b).

Same pattern as test_router.py / test_player_delete.py: the REAL app
over its real ASGI lifespan on a migrated temporary database, real
JWTs through /api/v1/auth/vk — no dependency overrides, no mocked DB
state (Anti-Mock Guard). Class-level hook registries are snapshotted
and restored around each test.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import modules._01_map.service as map_service_module
from alembic import command
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.admin_service import AdminGrantService
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Player
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    USER_VK_ID,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_vk_profile,
)
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

PLAYERS_URL = "/api/v1/admin/players"


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """The real app over its real lifespan on a migrated temporary
    database — the test_player_delete.py live_client pattern."""
    if PG_TEST_URL is not None:
        _reset_pg_schema(PG_TEST_URL)
        db_url = _async_url(PG_TEST_URL)
    else:
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()
    saved_overviews = AdminRegistry.get_overview_hooks()
    saved_player_infos = AdminRegistry.get_player_info_hooks()
    saved_province_infos = AdminRegistry.get_province_info_hooks()
    saved_handlers = {
        phase: list(handlers) for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback
    saved_extensions = snapshot_extension_points()
    saved_map_service = map_service_module._instance

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    AdminRegistry._player_preview_hooks.clear()
    AdminRegistry._player_preview_hooks.update(saved_previews)
    AdminRegistry._overview_hooks.clear()
    AdminRegistry._overview_hooks.update(saved_overviews)
    AdminRegistry._player_info_hooks.clear()
    AdminRegistry._player_info_hooks.update(saved_player_infos)
    AdminRegistry._province_info_hooks.clear()
    AdminRegistry._province_info_hooks.update(saved_province_infos)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize
    restore_extension_points(saved_extensions)
    map_service_module._instance = saved_map_service


async def _auth_headers(client: AsyncClient, vk_user_id: int) -> dict:
    """Real login through /api/v1/auth/vk -> Authorization header
    (creates the player row as a side effect)."""
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


async def _seed_player(
    vk_user_id: int,
    *,
    created_at: datetime,
    nation: dict | None = None,
    vk_name: tuple[str, str] | None = None,
) -> Player:
    """
    A player row straight into the app's live database — controlled
    ``created_at`` so the ordering tests are deterministic — with an
    optional nation (``{"name", "short_name"}``) and an optional cached
    VK profile (``(first, last)`` → the display_name column).
    """
    async with get_session_context() as session:
        player = PlayerFactory.build(
            vk_user_id=vk_user_id, created_at=created_at, nations=[]
        )
        session.add(player)
        await session.flush()
        if nation is not None:
            session.add(
                NationFactory.build(
                    owner=player,
                    name=nation["name"],
                    short_name=nation["short_name"],
                    color_hex=nation.get("color_hex", "#112233"),
                    provinces=[],
                    scheduled_actions=[],
                )
            )
        if vk_name is not None:
            await make_vk_profile(
                session, player, first_name=vk_name[0], last_name=vk_name[1]
            )
        await session.commit()
    return player


async def _items(client: AsyncClient, headers: dict, **params) -> dict:
    response = await client.get(PLAYERS_URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestPlayersAuthorization:
    """The list obeys require_admin like every admin route."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        response = await live_client.get(PLAYERS_URL, headers=headers)

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_limit_bounds(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)

        for bad in ("0", "101"):
            response = await live_client.get(
                PLAYERS_URL, params={"limit": bad}, headers=headers
            )
            assert response.status_code == 422


class TestPlayersList:
    """Paging, ordering and the item shape."""

    @pytest.mark.asyncio
    async def test_pages_in_registration_order(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        # Oldest first; the admin's own login row is stamped "now" —
        # always after the 2020-seeded rows, so it sorts last.
        base = datetime(2020, 1, 1, tzinfo=UTC)
        for i, vk in enumerate((770001, 770002, 770003)):
            await _seed_player(vk, created_at=base.replace(hour=i))

        first = await _items(live_client, headers, limit=2)
        second = await _items(live_client, headers, limit=2, offset=2)

        assert first["total"] == 4
        assert [item["vk_user_id"] for item in first["items"]] == [
            770001,
            770002,
        ]
        assert [item["vk_user_id"] for item in second["items"]] == [
            770003,
            ADMIN_VK_ID,
        ]

    @pytest.mark.asyncio
    async def test_item_shape(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(
            770010,
            created_at=datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC),
            nation={"name": "Новгород", "short_name": "НВГ"},
            vk_name=("Борис", "Иванов"),
        )
        await _seed_player(770011, created_at=datetime(2026, 3, 2, tzinfo=UTC))

        body = await _items(live_client, headers)

        by_vk = {item["vk_user_id"]: item for item in body["items"]}
        full = by_vk[770010]
        assert full["display_name"] == "Борис Иванов"
        assert full["nation_short_name"] == "НВГ"
        assert full["is_admin"] is False
        # 'YYYY-MM-DD HH:MM:SS' in the tick timezone, like every admin
        # answer — the exact wall clock depends on the zone, the shape
        # never does.
        assert full["created_at"] is not None
        datetime.strptime(full["created_at"], "%Y-%m-%d %H:%M:%S")
        # No profile cache, no nation -> both columns null.
        bare = by_vk[770011]
        assert bare["display_name"] is None
        assert bare["nation_short_name"] is None
        assert by_vk[ADMIN_VK_ID]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_is_admin_marks_env_and_granted_players(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        granted = await _seed_player(
            770020, created_at=datetime(2026, 3, 1, tzinfo=UTC)
        )
        await _seed_player(770021, created_at=datetime(2026, 3, 2, tzinfo=UTC))
        async with get_session_context() as session:
            await AdminGrantService.grant(
                session, granted.id, by_vk_user_id=ADMIN_VK_ID
            )
            await session.commit()

        body = await _items(live_client, headers)

        flags = {item["vk_user_id"]: item["is_admin"] for item in body["items"]}
        assert flags[ADMIN_VK_ID] is True  # env allowlist
        assert flags[770020] is True  # admin_grants row
        assert flags[770021] is False


class TestPlayersSearch:
    """`search` is an OR over VK id, nation names and hook searches."""

    @pytest.mark.asyncio
    async def test_search_exact_vk_id(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(770030, created_at=datetime(2026, 1, 1, tzinfo=UTC))
        await _seed_player(770031, created_at=datetime(2026, 1, 2, tzinfo=UTC))

        body = await _items(live_client, headers, search="770030")

        assert [item["vk_user_id"] for item in body["items"]] == [770030]
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_search_by_nation_names(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(
            770040,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            nation={"name": "Великий Новгород", "short_name": "НВГ"},
        )
        await _seed_player(770041, created_at=datetime(2026, 1, 2, tzinfo=UTC))

        # Case-insensitive substring of the full name...
        by_full = await _items(live_client, headers, search="новгород")
        # ...and of the short name.
        by_short = await _items(live_client, headers, search="нвг")

        for body in (by_full, by_short):
            assert [item["vk_user_id"] for item in body["items"]] == [770040]

    @pytest.mark.asyncio
    async def test_search_by_vk_profile_name(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(
            770050,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            vk_name=("Зигфрид", "Мюллер"),
        )
        await _seed_player(770051, created_at=datetime(2026, 1, 2, tzinfo=UTC))

        body = await _items(live_client, headers, search="зигфрид")

        assert [item["vk_user_id"] for item in body["items"]] == [770050]

    @pytest.mark.asyncio
    async def test_failing_info_hook_is_skipped(self, live_client, monkeypatch, caplog):
        """A broken player-info hook is logged and dropped — the list
        still answers with the surviving modules' columns."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(
            770060,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            vk_name=("Борис", "Иванов"),
        )

        async def broken_info(session, player_ids):
            raise RuntimeError("boom")

        AdminRegistry.register_player_info("zz_broken", broken_info)

        with caplog.at_level("ERROR"):
            body = await _items(live_client, headers)

        by_vk = {item["vk_user_id"]: item for item in body["items"]}
        assert by_vk[770060]["display_name"] == "Борис Иванов"
        assert "zz_broken" in caplog.text
