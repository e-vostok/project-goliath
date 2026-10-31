"""
Tests for the 0.11.0 unit-3 admin base: admin_grants + admin_audit_log.

Anti-Mock Guard: the service tests run on the real in-memory test DB
(test_db_session) and the require_admin probe reuses the minimal FastAPI
app pattern from test_security.py — the real dependency chain, no
mocked sessions. The journal-survival test boots the real app over its
real ASGI lifespan on a migrated database (PostgreSQL test DB when
reachable, else tmp SQLite), exactly like test_router.py's live_client.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import modules._01_map.service as map_service_module
from alembic import command
from core.admin.registry import AdminRegistry
from core.admin.security import require_admin
from core.db import get_session, get_session_context
from core.security import SecurityError
from core.security.jwt import issue_token
from core.tick.orchestrator import TickOrchestrator
from main import app, domain_error_handler
from modules._00_core.admin_service import (
    AdminAuditService,
    AdminGrantService,
    LastAdminError,
    RootAdminProtectedError,
)
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

GRANTED_VK_ID = 999888


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    """JWT secret for token issuing; empty admin allowlist by default."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.delenv("ADMIN_VK_USER_IDS", raising=False)


@pytest_asyncio.fixture
async def admin_client(test_db_session):
    """
    HTTP client over a minimal app exposing a require_admin-protected
    route — the test_security.py pattern: the real dependency chain
    (require_admin -> get_current_player -> JWT decode -> Player lookup)
    against the shared in-memory test DB.
    """
    test_app = FastAPI()
    test_app.add_exception_handler(SecurityError, domain_error_handler)

    @test_app.get("/admin-probe")
    async def admin_probe(player: Player = Depends(require_admin)):
        return {"vk_user_id": player.vk_user_id}

    async def _override_get_session():
        yield test_db_session

    test_app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    The real app over its real lifespan on a migrated temporary
    database (PostgreSQL test DB when reachable, else tmp SQLite) —
    the test_router.py live_client pattern, additionally enabling the
    world-reset gate.
    """
    if PG_TEST_URL is not None:
        _reset_pg_schema(PG_TEST_URL)
        db_url = _async_url(PG_TEST_URL)
    else:
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_ALLOW_RESET", "true")
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_LINKED_DIR))

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


def bearer_headers(player_id: str) -> dict[str, str]:
    """Authorization header with a real issued JWT."""
    token = issue_token(player_id, ttl_minutes=60)
    return {"Authorization": f"Bearer {token}"}


async def seed_player(session, vk_user_id: int) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


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


class TestAdminGrants:
    """admin_grants rights through require_admin and the revoke guards."""

    @pytest.mark.asyncio
    async def test_granted_player_passes_and_revoke_loses_access(
        self, admin_client, test_db_session, monkeypatch
    ):
        """A granted player passes require_admin and loses access the
        moment the grant is revoked — the check reads the table on
        every request, nothing is cached."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        player = await seed_player(test_db_session, vk_user_id=GRANTED_VK_ID)

        # Before the grant: a plain player is rejected.
        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

        await AdminGrantService.grant(
            test_db_session, player.id, by_vk_user_id=ADMIN_VK_ID
        )
        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )
        assert response.status_code == 200
        assert response.json() == {"vk_user_id": GRANTED_VK_ID}

        # The env root admin still holds rights, so the revoke stands.
        await AdminGrantService.revoke(test_db_session, player.id)
        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_revoke_refuses_root_admin(self, test_db_session, monkeypatch):
        """A player whose vk id sits in ADMIN_VK_USER_IDS is refused —
        env admins can only be removed by editing the environment."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(GRANTED_VK_ID))
        player = await seed_player(test_db_session, vk_user_id=GRANTED_VK_ID)
        await AdminGrantService.grant(
            test_db_session, player.id, by_vk_user_id=ADMIN_VK_ID
        )

        with pytest.raises(RootAdminProtectedError) as exc_info:
            await AdminGrantService.revoke(test_db_session, player.id)

        assert exc_info.value.code == "ROOT_ADMIN_PROTECTED"
        assert await AdminGrantService.is_granted(test_db_session, GRANTED_VK_ID)

    @pytest.mark.asyncio
    async def test_revoke_refuses_last_admin(self, test_db_session):
        """With an empty env allowlist the single remaining grant is
        unrevokable; a non-last grant revokes normally."""
        player_a = await seed_player(test_db_session, vk_user_id=1001)
        player_b = await seed_player(test_db_session, vk_user_id=1002)
        await AdminGrantService.grant(test_db_session, player_a.id, by_vk_user_id=1)
        await AdminGrantService.grant(test_db_session, player_b.id, by_vk_user_id=1)

        # player_b still holds a grant — the world keeps an admin.
        await AdminGrantService.revoke(test_db_session, player_a.id)
        assert not await AdminGrantService.is_granted(test_db_session, 1001)

        with pytest.raises(LastAdminError) as exc_info:
            await AdminGrantService.revoke(test_db_session, player_b.id)
        assert exc_info.value.code == "LAST_ADMIN"


class TestAdminAuditLog:
    """admin_audit_log journal writes, ordering and reset survival."""

    @pytest.mark.asyncio
    async def test_record_and_list_recent(self, test_db_session):
        """record() lands rows inside the caller's transaction;
        list_recent returns newest first and honours the before_id
        cursor."""
        first = await AdminAuditService.record(
            test_db_session,
            actor_vk_user_id=ADMIN_VK_ID,
            action="tick.run",
            summary="Запущен ход вручную.",
        )
        second = await AdminAuditService.record(
            test_db_session,
            actor_vk_user_id=ADMIN_VK_ID,
            action="player.delete",
            target_type="player",
            target_id="777001",
            summary="Удалён игрок 777001.",
            details={"provinces_released": 2},
        )

        rows = await AdminAuditService.list_recent(test_db_session, limit=10)
        assert [row.id for row in rows] == [second.id, first.id]
        assert rows[0].details == {"provinces_released": 2}

        older = await AdminAuditService.list_recent(
            test_db_session, limit=10, before_id=second.id
        )
        assert [row.id for row in older] == [first.id]

    @pytest.mark.asyncio
    async def test_tick_run_audit_survives_state_reset(self, live_client, monkeypatch):
        """POST /tick/run writes a journal row; POST /state/reset does
        not wipe admin_audit_log — the tick entry survives and the
        reset records its own row."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        tick = await live_client.post("/api/v1/admin/tick/run", headers=headers)
        assert tick.status_code == 200

        async with get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminAuditLog).order_by(AdminAuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.action for row in rows] == ["tick.run"]
            assert rows[0].actor_vk_user_id == ADMIN_VK_ID

        reset = await live_client.post(
            "/api/v1/admin/state/reset", json={"confirm": True}, headers=headers
        )
        assert reset.status_code == 200

        async with get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminAuditLog).order_by(AdminAuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.action for row in rows] == ["tick.run", "world.reset"]
            assert all(row.actor_vk_user_id == ADMIN_VK_ID for row in rows)


class TestAdminAuditRetention:
    """The journal keeps only the newest audit_log_max_rows rows."""

    @staticmethod
    def _patch_limit(monkeypatch, limit: int) -> None:
        """Point CoreConfig at the real config with the retention cap
        replaced by ``limit`` — the mini_map_config pattern: from_yaml
        answers a ready model, no YAML rewriting."""
        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        config.admin_panel.audit_log_max_rows = limit
        monkeypatch.setattr(
            CoreConfig, "from_yaml", classmethod(lambda cls, path: config)
        )

    @pytest.mark.asyncio
    async def test_record_trims_to_newest_n(self, test_db_session, monkeypatch):
        """With the cap patched to 5, writing 8 rows leaves exactly the
        newest 5: the 3 oldest ids are gone and the row just written is
        always kept."""
        self._patch_limit(monkeypatch, 5)
        rows = []
        for i in range(8):
            rows.append(
                await AdminAuditService.record(
                    test_db_session,
                    actor_vk_user_id=ADMIN_VK_ID,
                    action="tick.run",
                    summary=f"Запись {i}.",
                )
            )

        kept = await AdminAuditService.list_recent(test_db_session, limit=50)
        assert [row.id for row in kept] == [row.id for row in reversed(rows[3:])]
        assert kept[0].id == rows[-1].id

    @pytest.mark.asyncio
    async def test_trim_rolls_back_with_the_caller(self, test_db_session, monkeypatch):
        """The trim lands in the CALLER's transaction: the rows it
        deleted come back on rollback, together with the new row
        itself."""
        self._patch_limit(monkeypatch, 5)
        seeded = []
        for i in range(8):
            row = AdminAuditLog(
                actor_vk_user_id=ADMIN_VK_ID,
                action="tick.run",
                summary=f"Запись {i}.",
            )
            test_db_session.add(row)
            seeded.append(row)
        await test_db_session.flush()
        seeded_ids = [row.id for row in seeded]
        await test_db_session.commit()

        new_row = await AdminAuditService.record(
            test_db_session,
            actor_vk_user_id=ADMIN_VK_ID,
            action="world.reset",
            summary="Выполнен сброс состояния мира.",
        )
        kept = await AdminAuditService.list_recent(test_db_session, limit=50)
        assert [row.id for row in kept] == [
            new_row.id,
            *reversed(seeded_ids[4:]),
        ]

        await test_db_session.rollback()
        restored = await AdminAuditService.list_recent(test_db_session, limit=50)
        assert [row.id for row in restored] == list(reversed(seeded_ids))

    @pytest.mark.asyncio
    async def test_reset_and_player_delete_never_wipe_journal(
        self, live_client, monkeypatch
    ):
        """Even with the cap patched to 3, the world reset and the
        player deletion only trim down to the newest 3 rows — the
        destructive paths themselves never empty the journal, and the
        deleted player's own rows survive within the window."""
        self._patch_limit(monkeypatch, 3)
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, ADMIN_VK_ID)

        # Five rows authored by the soon-deleted player, written
        # directly — no record(), so no trimming yet.
        async with get_session_context() as session:
            session.add(Player(vk_user_id=777001))
            for i in range(5):
                session.add(
                    AdminAuditLog(
                        actor_vk_user_id=777001,
                        action="tick.run",
                        summary=f"Запись {i}.",
                    )
                )
            await session.commit()

        delete = await live_client.post(
            "/api/v1/admin/players/777001/delete",
            json={"confirm_vk_user_id": 777001},
            headers=headers,
        )
        assert delete.status_code == 200, delete.text
        async with get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminAuditLog).order_by(AdminAuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.action for row in rows] == [
                "tick.run",
                "tick.run",
                "player.delete",
            ]
            assert any(row.actor_vk_user_id == 777001 for row in rows)

        reset = await live_client.post(
            "/api/v1/admin/state/reset",
            json={"confirm": True},
            headers=headers,
        )
        assert reset.status_code == 200, reset.text
        async with get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminAuditLog).order_by(AdminAuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.action for row in rows] == [
                "tick.run",
                "player.delete",
                "world.reset",
            ]
