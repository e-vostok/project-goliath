"""
Tests for the 0.11.0 unit-4 panel entry: one-time links and sessions.

POST /api/v1/admin/panel-link (require_admin) issues a link token;
POST /api/v1/admin/session (no Bearer) exchanges it for a short Bearer
JWT. Anti-Mock Guard: everything runs through the real app over its real
ASGI lifespan on a migrated database (PostgreSQL test DB when reachable,
else tmp SQLite) — the live_client pattern of test_grants_audit.py. The
only substituted piece is the process-wide PanelLinkStore: each test
gets a fresh instance (or a fake-clock one) via monkeypatch.
"""

from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import modules._01_map.service as map_service_module
from alembic import command
from core.admin import panel_access
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.admin_service import AdminGrantService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import AdminAuditLog, Player
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.provinces import MAP_MINI_LINKED_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
USER_VK_ID = 777001


@pytest.fixture(autouse=True)
def fresh_panel_store(monkeypatch):
    """Isolated link store per test — the module singleton is process-wide."""
    monkeypatch.setattr(panel_access, "store", panel_access.PanelLinkStore())


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """The real app over its real lifespan on a migrated temporary
    database — the test_router.py live_client pattern."""
    if PG_TEST_URL is not None:
        _reset_pg_schema(PG_TEST_URL)
        db_url = _async_url(PG_TEST_URL)
    else:
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_LINKED_DIR))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()
    saved_overviews = AdminRegistry.get_overview_hooks()
    saved_player_infos = AdminRegistry.get_player_info_hooks()
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


async def _issue_link(client: AsyncClient, headers: dict) -> str:
    """POST /panel-link for an admin; returns the raw link token."""
    response = await client.post("/api/v1/admin/panel-link", headers=headers)
    assert response.status_code == 200
    return response.json()["token"]


async def _player_id_of(vk_user_id: int) -> str:
    async with get_session_context() as session:
        result = await session.execute(
            select(Player).where(Player.vk_user_id == vk_user_id)
        )
        return result.scalar_one().id


class TestPanelEntry:
    """The one-time link -> short session exchange, end to end."""

    @pytest.mark.asyncio
    async def test_admin_exchanges_link_and_session_opens_admin_api(
        self, live_client, monkeypatch
    ):
        """An admin gets a token, exchanges it once, and the issued
        Bearer opens an existing admin GET endpoint."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        # reset_allowed answers the request-time flag — pin it down.
        monkeypatch.delenv("ADMIN_ALLOW_RESET", raising=False)
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        link = await live_client.post("/api/v1/admin/panel-link", headers=headers)
        assert link.status_code == 200
        assert set(link.json()) == {"token", "expires_in_seconds"}
        assert link.json()["expires_in_seconds"] == (
            CORE_CONFIG.admin_panel.link_ttl_seconds
        )
        token = link.json()["token"]

        exchange = await live_client.post(
            "/api/v1/admin/session", json={"token": token}
        )

        assert exchange.status_code == 200
        body = exchange.json()
        assert body["expires_in_seconds"] == (
            CORE_CONFIG.admin_panel.session_ttl_minutes * 60
        )
        probe = await live_client.get(
            "/api/v1/admin/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert probe.status_code == 200
        assert probe.json() == {"is_admin": True, "reset_allowed": False}

    @pytest.mark.asyncio
    async def test_second_exchange_of_same_token_refused(
        self, live_client, monkeypatch
    ):
        """A spent link cannot be redeemed twice."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        token = await _issue_link(live_client, headers)
        first = await live_client.post("/api/v1/admin/session", json={"token": token})
        assert first.status_code == 200

        second = await live_client.post(
            "/api/v1/admin/session", json={"token": token}
        )

        assert second.status_code == 401
        assert second.json()["code"] == "PANEL_LINK_INVALID"

    @pytest.mark.asyncio
    async def test_expired_token_refused(self, live_client, monkeypatch):
        """With the injected clock moved past link_ttl the redeem fails."""
        now = [1000.0]
        monkeypatch.setattr(
            panel_access,
            "store",
            panel_access.PanelLinkStore(clock=lambda: now[0]),
        )
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        token = await _issue_link(live_client, headers)

        now[0] += CORE_CONFIG.admin_panel.link_ttl_seconds + 1
        exchange = await live_client.post(
            "/api/v1/admin/session", json={"token": token}
        )

        assert exchange.status_code == 401
        assert exchange.json()["code"] == "PANEL_LINK_INVALID"

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_panel_link(
        self, live_client, monkeypatch
    ):
        """panel-link is gated by require_admin like every admin route."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        response = await live_client.post("/api/v1/admin/panel-link", headers=headers)

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_revoked_admin_gets_403_and_token_stays_spent(
        self, live_client, monkeypatch
    ):
        """Rights are re-read at exchange: a grant revoked between
        issue and redeem answers 403, and the token remains spent."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)
        player_id = await _player_id_of(USER_VK_ID)
        async with get_session_context() as session:
            await AdminGrantService.grant(
                session, player_id, by_vk_user_id=ADMIN_VK_ID
            )
            await session.commit()

        token = await _issue_link(live_client, headers)

        async with get_session_context() as session:
            await AdminGrantService.revoke(session, player_id)
            await session.commit()

        exchange = await live_client.post(
            "/api/v1/admin/session", json={"token": token}
        )
        assert exchange.status_code == 403
        assert exchange.json()["code"] == "ADMIN_REQUIRED"

        retry = await live_client.post(
            "/api/v1/admin/session", json={"token": token}
        )
        assert retry.status_code == 401
        assert retry.json()["code"] == "PANEL_LINK_INVALID"

    @pytest.mark.asyncio
    async def test_store_holds_only_hashes(self, live_client, monkeypatch):
        """The raw token is neither a store key nor a stored value."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        token = await _issue_link(live_client, headers)

        store = panel_access.store
        assert token not in store._entries
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        entry = store._entries[digest]
        assert entry.player_id == await _player_id_of(ADMIN_VK_ID)
        assert token not in (entry.player_id, entry.expires_at, entry.used)

    @pytest.mark.asyncio
    async def test_per_player_cap_drops_oldest_link(
        self, live_client, monkeypatch
    ):
        """Issuing above max_pending_links_per_player kills the oldest
        pending link; the newest still redeems."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)
        cap = CORE_CONFIG.admin_panel.max_pending_links_per_player
        tokens = [await _issue_link(live_client, headers) for _ in range(cap + 1)]

        oldest = await live_client.post(
            "/api/v1/admin/session", json={"token": tokens[0]}
        )
        assert oldest.status_code == 401
        assert oldest.json()["code"] == "PANEL_LINK_INVALID"

        newest = await live_client.post(
            "/api/v1/admin/session", json={"token": tokens[-1]}
        )
        assert newest.status_code == 200

    @pytest.mark.asyncio
    async def test_panel_login_audit_row_only_after_good_exchange(
        self, live_client, monkeypatch
    ):
        """A failed exchange writes no journal row; a good one writes
        exactly one panel.login row carrying no token."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        bad = await live_client.post(
            "/api/v1/admin/session", json={"token": "not-a-real-token"}
        )
        assert bad.status_code == 401
        async with get_session_context() as session:
            rows = (
                await session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "panel.login"
                    )
                )
            ).scalars().all()
        assert rows == []

        token = await _issue_link(live_client, headers)
        good = await live_client.post("/api/v1/admin/session", json={"token": token})
        assert good.status_code == 200

        async with get_session_context() as session:
            rows = (
                await session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "panel.login"
                    )
                )
            ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_vk_user_id == ADMIN_VK_ID
        assert row.summary == "Вход в панель администратора."
        assert token not in str(row.details or {})

    @pytest.mark.asyncio
    async def test_both_responses_carry_no_store(
        self, live_client, monkeypatch
    ):
        """panel-link and session answers must never be cached."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        link = await live_client.post("/api/v1/admin/panel-link", headers=headers)
        exchange = await live_client.post(
            "/api/v1/admin/session", json={"token": link.json()["token"]}
        )
        rejected = await live_client.post(
            "/api/v1/admin/session", json={"token": "not-a-real-token"}
        )

        for response in (link, exchange, rejected):
            assert response.headers["Cache-Control"] == "no-store"
