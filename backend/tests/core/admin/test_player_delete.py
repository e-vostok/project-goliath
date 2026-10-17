"""
HTTP tests for the admin player-deletion endpoints (Issue 2 of the
admin panel — irreversible test-player cleanup).

Same pattern as test_router.py: the REAL app over its real ASGI
lifespan on a migrated temporary database, real JWTs through
/api/v1/auth/vk — no dependency overrides, no mocked DB state
(Anti-Mock Guard). Class-level hook registries are snapshotted and
restored around each test.
"""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Player, Province
from tests.fixtures.factories import (
    NationFactory,
    make_consent,
    make_order,
    make_outbox_row,
    make_vk_profile,
)
from tests.fixtures.provinces import MAP_MINI_DIR, map_mini_node_ids
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    USER_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    _async_url,
    _reset_pg_schema,
)

TARGET_VK_ID = 888111
OTHER_ADMIN_VK_ID = 555999


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    The real app over its real lifespan on a migrated temporary
    database (PostgreSQL test DB when reachable, else tmp SQLite) —
    the test_router.py live_client pattern, additionally snapshotting
    the player-preview hooks.
    """
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


async def _seed_target_world() -> None:
    """
    Give the TARGET_VK_ID player (created by its login) a nation with
    two provinces plus one row of every module type the deletion must
    remove — straight into the app's live database.
    """
    province_ids = map_mini_node_ids()[:2]
    async with get_session_context() as session:
        player = (
            await session.execute(
                select(Player).where(Player.vk_user_id == TARGET_VK_ID)
            )
        ).scalar_one()
        nation = NationFactory.build(
            owner=player,
            name="Цель",
            color_hex="#112233",
            provinces=[],
            scheduled_actions=[],
        )
        session.add(nation)
        await session.flush()
        for pid in province_ids:
            province = await session.get(Province, pid)
            province.nation_id = nation.id
        await make_consent(session, player)
        await make_outbox_row(session, player)
        await make_vk_profile(session, player)
        # One authored order and one undecided judged order.
        await make_order(session, player, nation=nation)
        author = (
            await session.execute(
                select(Player).where(Player.vk_user_id == ADMIN_VK_ID)
            )
        ).scalar_one()
        await make_order(session, author, judge=player)
        await session.commit()


def _preview_url(vk_user_id: int) -> str:
    return f"/api/v1/admin/players/{vk_user_id}/delete-preview"


def _delete_url(vk_user_id: int) -> str:
    return f"/api/v1/admin/players/{vk_user_id}/delete"


class TestPlayerDeleteAuthorization:
    """The two endpoints obey require_admin like every admin route."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_both_endpoints(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        preview = await live_client.get(_preview_url(TARGET_VK_ID), headers=headers)
        delete = await live_client.post(
            _delete_url(TARGET_VK_ID),
            json={"confirm_vk_user_id": TARGET_VK_ID},
            headers=headers,
        )

        for response in (preview, delete):
            assert response.status_code == 403
            assert response.json()["code"] == "ADMIN_REQUIRED"


class TestPlayerDeletePreview:
    """GET /api/v1/admin/players/{vk_user_id}/delete-preview."""

    @pytest.mark.asyncio
    async def test_unknown_player_404(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        response = await live_client.get(_preview_url(999999999), headers=headers)

        assert response.status_code == 404
        assert response.json()["code"] == "PLAYER_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_preview_counts_what_will_disappear(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        await _auth_headers(live_client, TARGET_VK_ID)
        await _seed_target_world()

        response = await live_client.get(_preview_url(TARGET_VK_ID), headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "vk_user_id": TARGET_VK_ID,
            "nation_name": "Цель",
            "provinces_released": 2,
            "orders_author": 1,
            "orders_judge_undecided": 1,
            "orders_judge_decided": 0,
            "outbox_rows": 1,
            "consent_rows": 1,
            "vk_profile_rows": 1,
        }


class TestPlayerDelete:
    """POST /api/v1/admin/players/{vk_user_id}/delete."""

    @pytest.mark.asyncio
    async def test_delete_returns_preview_and_removes_the_player(
        self, live_client, monkeypatch, caplog
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        await _auth_headers(live_client, TARGET_VK_ID)
        await _seed_target_world()

        preview = (
            await live_client.get(_preview_url(TARGET_VK_ID), headers=headers)
        ).json()

        with caplog.at_level(logging.WARNING, logger="core.admin.router"):
            response = await live_client.post(
                _delete_url(TARGET_VK_ID),
                json={"confirm_vk_user_id": str(TARGET_VK_ID)},
                headers=headers,
            )

        # The delete response reports the same counts the preview did.
        assert response.status_code == 200
        assert response.json() == preview

        # The player row is gone; a repeated preview is a 404.
        followup = await live_client.get(_preview_url(TARGET_VK_ID), headers=headers)
        assert followup.status_code == 404
        async with get_session_context() as session:
            gone = await session.execute(
                select(Player).where(Player.vk_user_id == TARGET_VK_ID)
            )
            assert gone.scalar_one_or_none() is None
            freed = await session.execute(
                select(Province).where(Province.id.in_(map_mini_node_ids()[:2]))
            )
            assert all(p.nation_id is None for p in freed.scalars().all())

        # One WARNING audit line naming the admin, the target and the
        # counts.
        audit = [r for r in caplog.records if "admin_player_delete" in r.getMessage()]
        assert len(audit) == 1
        assert audit[0].levelno == logging.WARNING
        message = audit[0].getMessage()
        assert str(ADMIN_VK_ID) in message
        assert str(TARGET_VK_ID) in message
        assert "provinces_released" in message

    @pytest.mark.asyncio
    async def test_confirmation_mismatch_422(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        await _auth_headers(live_client, TARGET_VK_ID)

        response = await live_client.post(
            _delete_url(TARGET_VK_ID),
            json={"confirm_vk_user_id": TARGET_VK_ID + 1},
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "CONFIRMATION_MISMATCH"

    @pytest.mark.asyncio
    async def test_cannot_delete_self_409(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        response = await live_client.post(
            _delete_url(ADMIN_VK_ID),
            json={"confirm_vk_user_id": ADMIN_VK_ID},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CANNOT_DELETE_SELF"

    @pytest.mark.asyncio
    async def test_cannot_delete_admin_409(self, live_client, monkeypatch):
        """A player whose VK id sits on the admin allowlist is never
        deletable — even when the caller is a different admin."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", f"{ADMIN_VK_ID},{OTHER_ADMIN_VK_ID}")
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        await _auth_headers(live_client, OTHER_ADMIN_VK_ID)

        response = await live_client.post(
            _delete_url(OTHER_ADMIN_VK_ID),
            json={"confirm_vk_user_id": OTHER_ADMIN_VK_ID},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CANNOT_DELETE_ADMIN"
