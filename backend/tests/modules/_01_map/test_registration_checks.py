"""
Registration checks registered by 01_map (Spec Part 5).

Mini-map topology used here: land chain 1001-1002-1003-1004, the
strait-linked group 1005-1006-1007, the coast-only node 1008, sea
zones 2001/2002. Service-level tests run on in-memory SQLite; the
HTTP layer is exercised once per code through the real app lifespan
to prove the error-code -> 422 mapping end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ProvinceTakenError,
)
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Player
from modules._00_core.service import NationService
from modules._01_map.errors import (
    ProvinceNotLandError,
    StartingGroupNotConnectedError,
)
from modules._01_map.hooks import register_map_hooks
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._01_map.conftest import map_config_disconnected
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


async def _player(session, vk_user_id: int) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


async def _create(session, player, province_ids, name="Realm", color="#101010"):
    return await NationService.create(
        session,
        owner_player_id=player.id,
        name=name,
        color_hex=color,
        province_ids=province_ids,
        config=CORE_CONFIG,
        **VALID_PROFILE,
    )


class TestRegistrationChecks:
    """Check behaviour and the Spec Part 5 order, at service level."""

    @pytest.mark.asyncio
    async def test_sea_id_rejected(self, map_db_session, map_hooks):
        player = await _player(map_db_session, 101)

        with pytest.raises(ProvinceNotLandError) as exc_info:
            await _create(map_db_session, player, [1001, 2001])

        assert exc_info.value.code == "PROVINCE_NOT_LAND"
        assert "2001" in exc_info.value.message

    def test_sea_listing_capped_at_five(self):
        """The message lists up to 5 ids; 6 sea ids show 'ещё 1'.
        The mini map has only two sea nodes, so the listing rule is
        exercised on the error type directly."""
        err = ProvinceNotLandError([2001, 2002, 2003, 2004, 2005, 2006])
        assert err.code == "PROVINCE_NOT_LAND"
        assert "2001" in err.message
        assert "2005" in err.message
        assert "2006" not in err.message
        assert "ещё 1" in err.message

    @pytest.mark.asyncio
    async def test_disconnected_group_rejected(
        self, map_db_session, map_hooks
    ):
        """1001 and 1005 join only via sea/coast — not connected."""
        player = await _player(map_db_session, 102)

        with pytest.raises(StartingGroupNotConnectedError) as exc_info:
            await _create(map_db_session, player, [1001, 1005])

        assert exc_info.value.code == "STARTING_GROUP_NOT_CONNECTED"
        assert exc_info.value.details == {"component_count": 2}

    @pytest.mark.asyncio
    async def test_strait_pair_accepted(self, map_db_session, map_hooks):
        """1005-1006 connect through a strait edge — accepted."""
        player = await _player(map_db_session, 103)

        nation = await _create(map_db_session, player, [1005, 1006])

        assert nation.id is not None

    @pytest.mark.asyncio
    async def test_single_province_accepted(
        self, map_db_session, map_hooks
    ):
        player = await _player(map_db_session, 104)

        nation = await _create(map_db_session, player, [1008])

        assert nation.id is not None

    @pytest.mark.asyncio
    async def test_require_connected_false_accepts_disconnected(
        self, map_db_session, flat_map_service, extension_snapshot
    ):
        config = map_config_disconnected()
        register_map_hooks(flat_map_service, config)
        player = await _player(map_db_session, 105)

        nation = await _create(map_db_session, player, [1001, 1005])

        assert nation.id is not None

    @pytest.mark.asyncio
    async def test_sea_error_beats_connectivity(
        self, map_db_session, map_hooks
    ):
        """2001 (sea) + 1005 (disconnected from 1001's group): the
        after_free check runs first — PROVINCE_NOT_LAND wins."""
        player = await _player(map_db_session, 106)

        with pytest.raises(ProvinceNotLandError):
            await _create(map_db_session, player, [1001, 2001, 1005])

    @pytest.mark.asyncio
    async def test_nonexistent_id_beats_map_checks(
        self, map_db_session, map_hooks
    ):
        player = await _player(map_db_session, 107)

        with pytest.raises(ProvinceNotFoundError):
            await _create(map_db_session, player, [9999, 2001])

    @pytest.mark.asyncio
    async def test_occupied_id_beats_map_checks(
        self, map_db_session, map_hooks
    ):
        player_a = await _player(map_db_session, 108)
        await _create(map_db_session, player_a, [1001, 1002])
        player_b = await _player(map_db_session, 109)

        # 1001 is taken AND 2001 is sea — freedom check comes first.
        with pytest.raises(ProvinceTakenError):
            await _create(
                map_db_session,
                player_b,
                [1001, 2001],
                name="Second",
                color="#202020",
            )

    @pytest.mark.asyncio
    async def test_count_beats_connectivity(
        self, map_db_session, map_hooks
    ):
        """Six provinces AND disconnected — the count check sits in
        core between the two stages, so it fires first."""
        player = await _player(map_db_session, 110)

        with pytest.raises(ProvinceCountOutOfRangeError):
            await _create(
                map_db_session,
                player,
                [1001, 1002, 1003, 1004, 1005, 1008],
            )


class TestApiStatus:
    """The error-code table maps both codes to HTTP 422 end to end."""

    @pytest_asyncio.fixture
    async def live_client(self, tmp_path, monkeypatch):
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'checks.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
        monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
        monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

        alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")

        saved_views = AdminRegistry.get_state_view_hooks()
        saved_resets = AdminRegistry.get_reset_hooks()
        saved_extensions = snapshot_extension_points()
        saved_service = map_service_module._instance

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
        restore_extension_points(saved_extensions)
        map_service_module._instance = saved_service

    async def _headers(self, client, vk_user_id: int) -> dict:
        resp = await client.post(
            "/api/v1/auth/vk",
            json={
                "launch_params": make_launch_params(
                    vk_user_id=vk_user_id, secret=TEST_VK_SECRET
                )
            },
        )
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    @pytest.mark.asyncio
    async def test_province_not_land_422(self, live_client):
        headers = await self._headers(live_client, 900001)

        resp = await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Coastal Dream",
                "color_hex": "#0F1E2D",
                "province_ids": [1001, 2001],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "PROVINCE_NOT_LAND"
        assert "2001" in body["detail"]

    @pytest.mark.asyncio
    async def test_not_connected_422_with_details(self, live_client):
        headers = await self._headers(live_client, 900002)

        resp = await live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "Split Realm",
                "color_hex": "#3C2B1A",
                "province_ids": [1001, 1005],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "STARTING_GROUP_NOT_CONNECTED"
        assert body["details"] == {"component_count": 2}
