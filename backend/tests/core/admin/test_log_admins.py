"""
HTTP tests for the 0.11.0 unit-7 admin endpoints: the journal
(GET /api/v1/admin/audit-log and /audit-log/filters) and the admin
rights (GET/POST /api/v1/admin/admins, POST /admins/{vk}/revoke).

Same pattern as test_players_list.py: the REAL app over its real ASGI
lifespan on a migrated temporary database, real JWTs through
/api/v1/auth/vk — no dependency overrides, no mocked DB state
(Anti-Mock Guard). Class-level hook registries — including the new
_audit_action_hooks — are snapshotted and restored around each test.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import modules._01_map.service as map_service_module
from alembic import command
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import _ERROR_CODE_STATUS, app
from modules._00_core.admin_service import (
    AdminGrantService,
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
    USER_VK_ID,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.factories import (
    PlayerFactory,
    make_vk_profile,
)
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

AUDIT_URL = "/api/v1/admin/audit-log"
FILTERS_URL = "/api/v1/admin/audit-log/filters"
ADMINS_URL = "/api/v1/admin/admins"

GRANTED_VK_ID = 555777
GRANTEE_VK_ID = 555888
ENV_ADMIN_VK_ID = 555999


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """The real app over its real lifespan on a migrated temporary
    database — the test_players_list.py live_client pattern, plus a
    snapshot of the audit-action hooks."""
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
    saved_audit_actions = AdminRegistry.get_audit_action_hooks()
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
    AdminRegistry._audit_action_hooks.clear()
    AdminRegistry._audit_action_hooks.update(saved_audit_actions)
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
    vk_user_id: int, *, vk_name: tuple[str, str] | None = None
) -> Player:
    """A player row in the app's live database, optionally with a
    cached VK profile (drives display_name through the hooks)."""
    async with get_session_context() as session:
        player = PlayerFactory.build(vk_user_id=vk_user_id, nations=[])
        session.add(player)
        await session.flush()
        if vk_name is not None:
            await make_vk_profile(
                session, player, first_name=vk_name[0], last_name=vk_name[1]
            )
        await session.commit()
    return player


async def _seed_audit_row(
    actor_vk_user_id: int,
    action: str,
    *,
    created_at: datetime | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    summary: str = "Тестовая запись.",
) -> AdminAuditLog:
    """One journal row straight into the live database — an explicit
    ``created_at`` keeps the date-filter tests deterministic."""
    async with get_session_context() as session:
        row = AdminAuditLog(
            actor_vk_user_id=actor_vk_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
        )
        if created_at is not None:
            row.created_at = created_at
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _audit_actions() -> list[str]:
    async with get_session_context() as session:
        rows = (
            (await session.execute(select(AdminAuditLog).order_by(AdminAuditLog.id)))
            .scalars()
            .all()
        )
        return [row.action for row in rows]


async def _get(client: AsyncClient, headers: dict, url: str, **params) -> dict:
    response = await client.get(url, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestAuditLogAuthorization:
    """Every new endpoint obeys require_admin."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_all_new_endpoints(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _auth_headers(live_client, USER_VK_ID)

        for method, url in (
            ("GET", AUDIT_URL),
            ("GET", FILTERS_URL),
            ("GET", ADMINS_URL),
            ("POST", ADMINS_URL),
            ("POST", f"{ADMINS_URL}/777/revoke"),
        ):
            response = await live_client.request(
                method, url, json={"vk_user_id": 1}, headers=headers
            )
            assert response.status_code == 403, (method, url)
            assert response.json()["code"] == "ADMIN_REQUIRED"


class TestAuditLogEndpoint:
    """Paging, filters, labels and actor names of GET /audit-log."""

    @pytest.mark.asyncio
    async def test_pages_with_before_id_and_filters(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        rows = []
        for i, (actor, action) in enumerate(
            [
                (ADMIN_VK_ID, "tick.run"),
                (GRANTED_VK_ID, "world.reset"),
                (ADMIN_VK_ID, "player.delete"),
            ]
        ):
            rows.append(
                await _seed_audit_row(
                    actor,
                    action,
                    created_at=datetime(2026, 10, 20, 12, i, tzinfo=UTC),
                    target_type="player",
                    target_id="777001",
                    summary=f"Запись {i}.",
                )
            )

        # Newest first; the cursor walks back through the journal.
        first = await _get(live_client, headers, AUDIT_URL, limit=2)
        assert [item["id"] for item in first["items"]] == [
            rows[2].id,
            rows[1].id,
        ]
        assert first["next_before_id"] == rows[1].id
        second = await _get(
            live_client,
            headers,
            AUDIT_URL,
            limit=2,
            before_id=first["next_before_id"],
        )
        assert [item["id"] for item in second["items"]] == [rows[0].id]
        assert second["next_before_id"] is None

        # Exact-match filters compose with the cursor contract.
        by_actor = await _get(
            live_client, headers, AUDIT_URL, actor_vk_user_id=GRANTED_VK_ID
        )
        assert [item["action"] for item in by_actor["items"]] == ["world.reset"]
        by_action = await _get(live_client, headers, AUDIT_URL, action="player.delete")
        assert [item["id"] for item in by_action["items"]] == [rows[2].id]
        item = by_action["items"][0]
        assert item["target_type"] == "player"
        assert item["target_id"] == "777001"
        assert item["summary"] == "Запись 2."

    @pytest.mark.asyncio
    async def test_date_filters_use_tick_timezone(self, live_client, monkeypatch):
        """date_from/date_to are local calendar dates in the tick
        timezone (Europe/Moscow), not UTC dates."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        # 21:30 UTC on the 20th is already 00:30 on the 21st in Moscow.
        await _seed_audit_row(
            ADMIN_VK_ID,
            "tick.run",
            created_at=datetime(2026, 10, 20, 21, 30, tzinfo=UTC),
        )
        await _seed_audit_row(
            ADMIN_VK_ID,
            "world.reset",
            created_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        )
        await _seed_audit_row(
            ADMIN_VK_ID,
            "player.delete",
            created_at=datetime(2026, 10, 19, 10, 0, tzinfo=UTC),
        )

        only_21st = await _get(
            live_client,
            headers,
            AUDIT_URL,
            date_from="2026-10-21",
            date_to="2026-10-21",
        )
        assert {item["action"] for item in only_21st["items"]} == {
            "tick.run",
            "world.reset",
        }
        until_20th = await _get(live_client, headers, AUDIT_URL, date_to="2026-10-20")
        assert {item["action"] for item in until_20th["items"]} == {"player.delete"}
        from_21st = await _get(live_client, headers, AUDIT_URL, date_from="2026-10-21")
        assert "player.delete" not in {item["action"] for item in from_21st["items"]}

    @pytest.mark.asyncio
    async def test_action_label_from_hook_and_unknown_stays_raw(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        AdminRegistry.register_audit_actions(
            "test_mod", {"test.act": "Тестовое действие"}
        )
        await _seed_audit_row(ADMIN_VK_ID, "test.act")
        await _seed_audit_row(ADMIN_VK_ID, "unknown.code")

        body = await _get(live_client, headers, AUDIT_URL)

        labels = {item["action"]: item["action_label"] for item in body["items"]}
        assert labels["test.act"] == "Тестовое действие"
        assert labels["unknown.code"] == "unknown.code"
        # And the codes 00_core owns arrive translated as well.
        assert AdminRegistry.get_audit_action_labels()["tick.run"] == "Запуск хода"
        assert AdminRegistry.get_audit_action_labels()["admin.grant"] == "Выдача прав"
        assert AdminRegistry.get_audit_action_labels()["admin.revoke"] == "Снятие прав"

    @pytest.mark.asyncio
    async def test_actor_name_only_while_player_exists(self, live_client, monkeypatch):
        """actor_name is the hook-provided display name; a vk id with no
        living player (journal survives deletion) answers null."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(GRANTED_VK_ID, vk_name=("Ольга", "Ветрова"))
        await _seed_audit_row(GRANTED_VK_ID, "panel.login")
        await _seed_audit_row(999000, "tick.run")

        body = await _get(live_client, headers, AUDIT_URL)

        names = {item["actor_vk_user_id"]: item["actor_name"] for item in body["items"]}
        assert names[GRANTED_VK_ID] == "Ольга Ветрова"
        assert names[999000] is None

    @pytest.mark.asyncio
    async def test_filters_endpoint_distinct_values(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(GRANTED_VK_ID, vk_name=("Ольга", "Ветрова"))
        await _seed_audit_row(GRANTED_VK_ID, "admin.grant")
        await _seed_audit_row(999000, "admin.revoke")
        await _seed_audit_row(GRANTED_VK_ID, "admin.revoke")

        body = await _get(live_client, headers, FILTERS_URL)

        actors = {a["vk_user_id"]: a["display_name"] for a in body["actors"]}
        assert actors[GRANTED_VK_ID] == "Ольга Ветрова"
        assert actors[999000] is None
        actions = {a["action"]: a["action_label"] for a in body["actions"]}
        assert actions == {
            "admin.grant": "Выдача прав",
            "admin.revoke": "Снятие прав",
        }

    @pytest.mark.asyncio
    async def test_retention_limit_in_answer(self, live_client, monkeypatch):
        """The answer carries the current ``audit_log_max_rows`` next
        to ``items``/``next_before_id`` — the «Журнал» caption under
        the table prints it."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        config.admin_panel.audit_log_max_rows = 700
        monkeypatch.setattr(
            CoreConfig, "from_yaml", classmethod(lambda cls, path: config)
        )

        body = await _get(live_client, headers, AUDIT_URL)
        assert body["retention_limit"] == 700


class TestAdminsEndpoint:
    """GET /admins and the grant/revoke endpoints."""

    @pytest.mark.asyncio
    async def test_lists_env_and_granted_admins(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", f"{ADMIN_VK_ID},{ENV_ADMIN_VK_ID}")
        headers = await _admin_headers(live_client)
        # The caller is the env admin ADMIN_VK_ID (a player, no profile);
        # the granted player gets a VK profile for display_name.
        granted = await _seed_player(GRANTED_VK_ID, vk_name=("Ольга", "Ветрова"))
        async with get_session_context() as session:
            await AdminGrantService.grant(
                session, granted.id, by_vk_user_id=ADMIN_VK_ID
            )
            await session.commit()

        body = await _get(live_client, headers, ADMINS_URL)

        by_vk = {item["vk_user_id"]: item for item in body}
        # env admins first, sorted; ENV_ADMIN_VK_ID is env but no player.
        assert body[0]["vk_user_id"] == ADMIN_VK_ID
        assert by_vk[ADMIN_VK_ID]["source"] == "env"
        assert by_vk[ADMIN_VK_ID]["granted_by_vk_user_id"] is None
        assert by_vk[ADMIN_VK_ID]["granted_at"] is None
        assert by_vk[ADMIN_VK_ID]["is_self"] is True
        env_row = by_vk[ENV_ADMIN_VK_ID]
        assert env_row["source"] == "env"
        assert env_row["display_name"] is None
        assert env_row["is_self"] is False
        grant_row = by_vk[GRANTED_VK_ID]
        assert grant_row["source"] == "grant"
        assert grant_row["display_name"] == "Ольга Ветрова"
        assert grant_row["granted_by_vk_user_id"] == ADMIN_VK_ID
        # The granter is a player without a cached profile -> null.
        assert grant_row["granted_by_name"] is None
        assert grant_row["granted_at"] is not None
        datetime.strptime(grant_row["granted_at"], "%Y-%m-%d %H:%M:%S")

    @pytest.mark.asyncio
    async def test_grant_then_revoke_controls_access(self, live_client, monkeypatch):
        """POST /admins makes a plain player pass require_admin;
        /revoke removes the access at once (the DB is re-read)."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(GRANTEE_VK_ID)
        grantee_headers = await _auth_headers(live_client, GRANTEE_VK_ID)

        probe = await live_client.get("/api/v1/admin/me", headers=grantee_headers)
        assert probe.status_code == 403

        grant = await live_client.post(
            ADMINS_URL, json={"vk_user_id": GRANTEE_VK_ID}, headers=headers
        )
        assert grant.status_code == 200, grant.text
        assert grant.json() == {"granted": GRANTEE_VK_ID}

        probe = await live_client.get("/api/v1/admin/me", headers=grantee_headers)
        assert probe.status_code == 200

        revoke = await live_client.post(
            f"{ADMINS_URL}/{GRANTEE_VK_ID}/revoke", headers=headers
        )
        assert revoke.status_code == 200, revoke.text
        probe = await live_client.get("/api/v1/admin/me", headers=grantee_headers)
        assert probe.status_code == 403

    @pytest.mark.asyncio
    async def test_grant_idempotent_and_404_for_unknown(self, live_client, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(GRANTEE_VK_ID)

        for _ in range(2):
            response = await live_client.post(
                ADMINS_URL, json={"vk_user_id": GRANTEE_VK_ID}, headers=headers
            )
            assert response.status_code == 200

        async with get_session_context() as session:
            assert await AdminGrantService.is_granted(session, GRANTEE_VK_ID)

        missing = await live_client.post(
            ADMINS_URL, json={"vk_user_id": 424000001}, headers=headers
        )
        assert missing.status_code == 404
        assert missing.json()["code"] == "PLAYER_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_revoke_refusals_map_to_409(self, live_client, monkeypatch):
        """env admin -> ROOT_ADMIN_PROTECTED; the caller themselves ->
        CANNOT_REVOKE_SELF; LAST_ADMIN maps to 409 like the others."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", f"{ADMIN_VK_ID},{ENV_ADMIN_VK_ID}")
        headers = await _admin_headers(live_client)
        await _seed_player(ENV_ADMIN_VK_ID)

        env_revoke = await live_client.post(
            f"{ADMINS_URL}/{ENV_ADMIN_VK_ID}/revoke", headers=headers
        )
        assert env_revoke.status_code == 409
        assert env_revoke.json()["code"] == "ROOT_ADMIN_PROTECTED"

        self_revoke = await live_client.post(
            f"{ADMINS_URL}/{ADMIN_VK_ID}/revoke", headers=headers
        )
        assert self_revoke.status_code == 409
        assert self_revoke.json()["code"] == "CANNOT_REVOKE_SELF"

        # The endpoint itself can never reach LAST_ADMIN — the caller is
        # always an admin that remains — but the code maps to 409 the
        # same way (the service-level refusal is covered by
        # test_grants_audit.py).
        assert _ERROR_CODE_STATUS["LAST_ADMIN"] == 409

    @pytest.mark.asyncio
    async def test_each_grant_and_revoke_writes_one_audit_row(
        self, live_client, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
        headers = await _admin_headers(live_client)
        await _seed_player(GRANTEE_VK_ID, vk_name=("Ольга", "Ветрова"))

        grant = await live_client.post(
            ADMINS_URL, json={"vk_user_id": GRANTEE_VK_ID}, headers=headers
        )
        assert grant.status_code == 200
        revoke = await live_client.post(
            f"{ADMINS_URL}/{GRANTEE_VK_ID}/revoke", headers=headers
        )
        assert revoke.status_code == 200

        assert await _audit_actions() == ["admin.grant", "admin.revoke"]

        body = await _get(live_client, headers, AUDIT_URL)
        rows = {item["action"]: item for item in body["items"]}
        grant_row = rows["admin.grant"]
        assert grant_row["actor_vk_user_id"] == ADMIN_VK_ID
        assert grant_row["target_type"] == "player"
        assert grant_row["target_id"] == str(GRANTEE_VK_ID)
        assert grant_row["action_label"] == "Выдача прав"
        assert "Ольга Ветрова" in grant_row["summary"]
        assert rows["admin.revoke"]["action_label"] == "Снятие прав"
