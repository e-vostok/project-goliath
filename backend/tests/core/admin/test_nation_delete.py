"""
HTTP tests for the admin nation-deletion endpoints (0.11.0 unit 8c):
GET /api/v1/admin/nations/{id}/delete-preview and
POST /api/v1/admin/nations/{id}/delete.

Same pattern as test_player_delete.py: the REAL app over its real
ASGI lifespan on a migrated temporary database, real JWTs through
/api/v1/auth/vk — no dependency overrides, no mocked DB state
(Anti-Mock Guard). Class-level hook registries (including the new
nation-preview hooks) are snapshotted and restored around each test.
The linked mini map fixture hosts a real 5-province nation created
through the ordinary player path.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

import modules._01_map.service as map_service_module
from alembic import command
from core.admin.registry import AdminRegistry
from core.db import get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.hooks import (
    register_ownership_listener,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import (
    AdminAuditLog,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
)
from modules._01_map.models import MapOwnershipLog
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import MAP_MINI_LINKED_DIR, STARTING_GROUP
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

OWNER_VK_ID = 777001
SECOND_VK_ID = 777002


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    The real app over its real lifespan on a migrated temporary
    database — the test_nations_provinces.py live_client pattern,
    additionally snapshotting the nation-preview hook registry.
    """
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
    saved_nation_previews = AdminRegistry.get_nation_preview_hooks()
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
    AdminRegistry._nation_preview_hooks.clear()
    AdminRegistry._nation_preview_hooks.update(saved_nation_previews)
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


async def _admin_headers(client: AsyncClient, monkeypatch) -> dict:
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
    return await _auth_headers(client, ADMIN_VK_ID)


async def _create_nation_as_player(
    client: AsyncClient, vk_user_id: int, **overrides
) -> dict:
    """Create a nation through the real player path (POST /nations)."""
    headers = await _auth_headers(client, vk_user_id)
    body = {
        "name": "Player Nation",
        "color_hex": "#123456",
        "province_ids": list(STARTING_GROUP),
        **VALID_PROFILE,
    }
    body.update(overrides)
    response = await client.post("/api/v1/nations", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_scheduled_actions(nation_id: str, count: int) -> None:
    """Pending scheduled actions owned by the nation, straight into
    the app's live database."""
    async with get_session_context() as session:
        for _ in range(count):
            session.add(
                ScheduledAction(
                    id=str(uuid.uuid4()),
                    nation_id=nation_id,
                    module_slug="test_module",
                    action_type="test_action",
                    payload={},
                    turn_number=1,
                    status=ScheduledActionStatus.PENDING,
                    created_at=datetime.now(UTC),
                )
            )
        await session.commit()


def _preview_url(nation_id: str) -> str:
    return f"/api/v1/admin/nations/{nation_id}/delete-preview"


def _delete_url(nation_id: str) -> str:
    return f"/api/v1/admin/nations/{nation_id}/delete"


class TestNationDeleteAuthorization:
    """The two endpoints obey require_admin like every admin route."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_both_endpoints(self, live_client, monkeypatch):
        await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        user_headers = await _auth_headers(live_client, SECOND_VK_ID)

        preview = await live_client.get(
            _preview_url(nation["id"]), headers=user_headers
        )
        delete = await live_client.post(
            _delete_url(nation["id"]),
            json={"confirm_short_name": nation["short_name"]},
            headers=user_headers,
        )

        for response in (preview, delete):
            assert response.status_code == 403
            assert response.json()["code"] == "ADMIN_REQUIRED"


class TestNationDeletePreview:
    """GET /api/v1/admin/nations/{nation_id}/delete-preview."""

    @pytest.mark.asyncio
    async def test_unknown_nation_404(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)

        preview = await live_client.get(_preview_url("nation-missing"), headers=headers)
        delete = await live_client.post(
            _delete_url("nation-missing"),
            json={"confirm_short_name": "Testland"},
            headers=headers,
        )

        for response in (preview, delete):
            assert response.status_code == 404
            assert response.json()["code"] == "NATION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_preview_lists_provinces_and_core_consequences(
        self, live_client, monkeypatch
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _seed_scheduled_actions(nation["id"], 2)

        response = await live_client.get(_preview_url(nation["id"]), headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["nation_id"] == nation["id"]
        assert body["short_name"] == nation["short_name"]
        assert body["name"] == nation["name"]
        assert body["owner_vk_user_id"] == OWNER_VK_ID
        # A bare VK-login player has no profile row — no display name.
        assert body["owner_name"] is None
        # Ordered by display name, not id.
        assert body["provinces"] == [
            {"id": 1001, "name": "Mini Alpha"},
            {"id": 1002, "name": "Mini Beta"},
            {"id": 1004, "name": "Mini Delta"},
            {"id": 1005, "name": "Mini Epsilon"},
            {"id": 1003, "name": "Mini Gamma"},
        ]
        assert body["consequences"] == [
            {
                "code": "scheduled_actions",
                "text": (
                    "запланированных действий государства: 2 — "
                    "они останутся без государства"
                ),
            },
            {
                "code": "ownership_journal",
                "text": ("в журнал владения карты запишутся 5 освобождений провинций"),
            },
        ]

    @pytest.mark.asyncio
    async def test_preview_pluralizes_one_release(self, live_client, monkeypatch):
        """Correct Russian singular in the journal line for a
        one-province nation."""
        headers = await _admin_headers(live_client, monkeypatch)
        await _auth_headers(live_client, OWNER_VK_ID)
        nation_id = str(uuid.uuid4())
        async with get_session_context() as session:
            owner = (
                await session.execute(
                    select(Player).where(Player.vk_user_id == OWNER_VK_ID)
                )
            ).scalar_one()
            session.add(
                Nation(
                    id=nation_id,
                    owner_player_id=owner.id,
                    name="Одна Провинция",
                    color_hex="#223344",
                    leader_name=VALID_PROFILE["leader_name"],
                    leader_title=VALID_PROFILE["leader_title"],
                    history_url=VALID_PROFILE["history_url"],
                    short_name="OneP",
                    gender=VALID_PROFILE["gender"],
                    succession_type=VALID_PROFILE["succession_type"],
                    capital_name="Mini Alpha",
                    flag_id=VALID_PROFILE["flag_id"],
                    portrait_id=VALID_PROFILE["portrait_id"],
                    created_at=datetime.now(UTC),
                    created_turn=0,
                )
            )
            (await session.get(Province, 1001)).nation_id = nation_id
            await session.commit()

        response = await live_client.get(_preview_url(nation_id), headers=headers)

        assert response.status_code == 200
        assert response.json()["consequences"] == [
            {
                "code": "ownership_journal",
                "text": ("в журнал владения карты запишется 1 освобождение провинций"),
            }
        ]

    @pytest.mark.asyncio
    async def test_failing_preview_hook_breaks_the_preview(
        self, live_client, monkeypatch
    ):
        """A failing consequence hook propagates — the preview fails
        instead of silently skipping a module's line."""
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        async def broken_hook(_session, _nation_id):
            raise RuntimeError("preview broke")

        AdminRegistry.register_nation_preview("broken", broken_hook)

        with pytest.raises(RuntimeError, match="preview broke"):
            await live_client.get(_preview_url(nation["id"]), headers=headers)


class TestNationDelete:
    """POST /api/v1/admin/nations/{nation_id}/delete."""

    @pytest.mark.asyncio
    async def test_delete_returns_preview_and_keeps_the_player(
        self, live_client, monkeypatch, caplog
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _seed_scheduled_actions(nation["id"], 2)

        preview = (
            await live_client.get(_preview_url(nation["id"]), headers=headers)
        ).json()

        with caplog.at_level(logging.WARNING, logger="core.admin.router"):
            response = await live_client.post(
                _delete_url(nation["id"]),
                json={"confirm_short_name": nation["short_name"]},
                headers=headers,
            )

        # The delete response is the preview that was true at deletion
        # time.
        assert response.status_code == 200
        assert response.json() == preview

        # The nation is gone — a repeated preview is a 404.
        followup = await live_client.get(_preview_url(nation["id"]), headers=headers)
        assert followup.status_code == 404

        async with get_session_context() as session:
            # Every province freed.
            owned = (
                await session.execute(
                    select(func.count())
                    .select_from(Province)
                    .where(Province.nation_id == nation["id"])
                )
            ).scalar_one()
            assert owned == 0
            # One release entry per freed province in the ownership
            # journal; the historical nation id is preserved.
            journal = list(
                (
                    await session.execute(
                        select(MapOwnershipLog).where(
                            MapOwnershipLog.prev_nation_id == nation["id"]
                        )
                    )
                ).scalars()
            )
            assert len(journal) == len(STARTING_GROUP)
            assert {entry.new_nation_id for entry in journal} == {None}
            assert {entry.province_id for entry in journal} == set(STARTING_GROUP)
            # The scheduled actions stay, orphaned to NULL nation_id.
            actions = list(
                (
                    await session.execute(
                        select(ScheduledAction).where(
                            ScheduledAction.module_slug == "test_module"
                        )
                    )
                ).scalars()
            )
            assert len(actions) == 2
            assert {action.nation_id for action in actions} == {None}
            # The owner row survives — a player without a nation.
            owner = (
                await session.execute(
                    select(Player).where(Player.vk_user_id == OWNER_VK_ID)
                )
            ).scalar_one()
            nation_row = await session.get(Nation, nation["id"])
            assert nation_row is None
            # Exactly one nation.delete audit row; details carry ids,
            # never the consequence texts.
            audit_rows = list(
                (
                    await session.execute(
                        select(AdminAuditLog).where(
                            AdminAuditLog.action == "nation.delete"
                        )
                    )
                ).scalars()
            )
            assert len(audit_rows) == 1
            row = audit_rows[0]
            assert row.actor_vk_user_id == ADMIN_VK_ID
            assert row.target_type == "nation"
            assert row.target_id == nation["id"]
            assert row.summary == (
                f"Удалено государство «{nation['short_name']}» игрока "
                f"{OWNER_VK_ID}; провинций освобождено: 5."
            )
            assert row.details == {
                "nation_id": nation["id"],
                "owner_player_id": owner.id,
                "owner_vk_user_id": OWNER_VK_ID,
                "province_ids": list(STARTING_GROUP),
            }

        # One WARNING audit line naming the admin, the nation and the
        # released-province count.
        audit = [r for r in caplog.records if "admin_nation_delete" in r.getMessage()]
        assert len(audit) == 1
        assert audit[0].levelno == logging.WARNING
        message = audit[0].getMessage()
        assert str(ADMIN_VK_ID) in message
        assert nation["id"] in message
        assert "provinces_released" in message

    @pytest.mark.asyncio
    async def test_freed_owner_registers_a_new_nation(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        response = await live_client.post(
            _delete_url(nation["id"]),
            json={"confirm_short_name": nation["short_name"]},
            headers=headers,
        )
        assert response.status_code == 200

        # The owner is a player without a nation again — the ordinary
        # registration path accepts the same freed provinces.
        created = await _create_nation_as_player(
            live_client, OWNER_VK_ID, name="New Realm", short_name="NewR"
        )
        assert created["short_name"] == "NewR"
        assert created["id"] != nation["id"]

    @pytest.mark.asyncio
    async def test_confirmation_mismatch_422_changes_nothing(
        self, live_client, monkeypatch
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _seed_scheduled_actions(nation["id"], 1)

        for body in (
            {"confirm_short_name": nation["short_name"].lower()},
            {"confirm_short_name": ""},
            {},
        ):
            response = await live_client.post(
                _delete_url(nation["id"]), json=body, headers=headers
            )
            assert response.status_code == 422
            assert response.json()["code"] == "CONFIRMATION_MISMATCH"

        async with get_session_context() as session:
            assert await session.get(Nation, nation["id"]) is not None
            owned = (
                await session.execute(
                    select(func.count())
                    .select_from(Province)
                    .where(Province.nation_id == nation["id"])
                )
            ).scalar_one()
            assert owned == len(STARTING_GROUP)
            attached = (
                await session.execute(
                    select(func.count())
                    .select_from(ScheduledAction)
                    .where(ScheduledAction.nation_id == nation["id"])
                )
            ).scalar_one()
            assert attached == 1
            audit_count = (
                await session.execute(
                    select(func.count())
                    .select_from(AdminAuditLog)
                    .where(AdminAuditLog.action == "nation.delete")
                )
            ).scalar_one()
            assert audit_count == 0

    @pytest.mark.asyncio
    async def test_failed_delete_rolls_everything_back(self, live_client, monkeypatch):
        """A raising ownership listener makes the transaction fail —
        nation, provinces and scheduled actions stay untouched, no
        audit row, and the answer is 500 NATION_DELETE_FAILED."""
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _seed_scheduled_actions(nation["id"], 1)

        async def exploding_listener(_session, _changes):
            raise RuntimeError("simulated listener failure")

        register_ownership_listener("test_boom", exploding_listener)

        response = await live_client.post(
            _delete_url(nation["id"]),
            json={"confirm_short_name": nation["short_name"]},
            headers=headers,
        )

        assert response.status_code == 500
        assert response.json()["code"] == "NATION_DELETE_FAILED"

        async with get_session_context() as session:
            assert await session.get(Nation, nation["id"]) is not None
            owned = (
                await session.execute(
                    select(func.count())
                    .select_from(Province)
                    .where(Province.nation_id == nation["id"])
                )
            ).scalar_one()
            assert owned == len(STARTING_GROUP)
            attached = (
                await session.execute(
                    select(func.count())
                    .select_from(ScheduledAction)
                    .where(ScheduledAction.nation_id == nation["id"])
                )
            ).scalar_one()
            assert attached == 1
            audit_count = (
                await session.execute(
                    select(func.count())
                    .select_from(AdminAuditLog)
                    .where(AdminAuditLog.action == "nation.delete")
                )
            ).scalar_one()
            assert audit_count == 0
