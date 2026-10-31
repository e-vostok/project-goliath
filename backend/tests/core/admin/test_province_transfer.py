"""
HTTP tests for the admin province-transfer endpoints (0.11.0 unit 9a):
GET /api/v1/admin/provinces/{id}/transfer-preview and
POST /api/v1/admin/provinces/{id}/transfer.

Same pattern as test_nation_delete.py: the REAL app over its real
ASGI lifespan on a migrated temporary database, real JWTs through
/api/v1/auth/vk — no dependency overrides, no mocked DB state
(Anti-Mock Guard). The linked mini map fixture hosts a real
5-province nation created through the ordinary player path; the
01_map province-info hook supplies the display names.
"""

from __future__ import annotations

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
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import (
    AdminAuditLog,
    Nation,
    Player,
    Province,
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


async def _seed_nation(
    vk_user_id: int,
    province_ids: list[int],
    *,
    name: str,
    color_hex: str,
    short_name: str,
    capital_province_id: int | None = None,
) -> str:
    """Seed a bare nation owning provinces, straight into the app's
    database — returns the nation id."""
    nation_id = str(uuid.uuid4())
    async with get_session_context() as session:
        owner = (
            await session.execute(select(Player).where(Player.vk_user_id == vk_user_id))
        ).scalar_one()
        session.add(
            Nation(
                id=nation_id,
                owner_player_id=owner.id,
                name=name,
                color_hex=color_hex,
                leader_name=VALID_PROFILE["leader_name"],
                leader_title=VALID_PROFILE["leader_title"],
                history_url=VALID_PROFILE["history_url"],
                short_name=short_name,
                gender=VALID_PROFILE["gender"],
                succession_type=VALID_PROFILE["succession_type"],
                capital_province_id=capital_province_id,
                capital_name=(
                    VALID_PROFILE["capital_name"]
                    if capital_province_id is not None
                    else None
                ),
                created_at=datetime.now(UTC),
                created_turn=0,
            )
        )
        for pid in province_ids:
            (await session.get(Province, pid)).nation_id = nation_id
        await session.commit()
    return nation_id


async def _audit_rows(action: str | None = None) -> list[AdminAuditLog]:
    async with get_session_context() as session:
        query = select(AdminAuditLog).order_by(AdminAuditLog.id)
        if action is not None:
            query = query.where(AdminAuditLog.action == action)
        return list((await session.execute(query)).scalars().all())


def _preview_url(province_id: int, to_nation_id: str | None = None) -> str:
    url = f"/api/v1/admin/provinces/{province_id}/transfer-preview"
    if to_nation_id is not None:
        url += f"?to_nation_id={to_nation_id}"
    return url


def _transfer_url(province_id: int) -> str:
    return f"/api/v1/admin/provinces/{province_id}/transfer"


class TestTransferAuthorization:
    """Both endpoints obey require_admin like every admin route."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_both_endpoints(self, live_client, monkeypatch):
        await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        user_headers = await _auth_headers(live_client, SECOND_VK_ID)

        preview = await live_client.get(
            _preview_url(1006, nation["id"]), headers=user_headers
        )
        transfer = await live_client.post(
            _transfer_url(1006),
            json={"to_nation_id": nation["id"]},
            headers=user_headers,
        )

        for response in (preview, transfer):
            assert response.status_code == 403
            assert response.json()["code"] == "ADMIN_REQUIRED"


class TestTransferPreview:
    """GET /api/v1/admin/provinces/{id}/transfer-preview."""

    @pytest.mark.asyncio
    async def test_free_province_to_nation_shape(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        response = await live_client.get(
            _preview_url(1006, nation["id"]), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["province"] == {"id": 1006, "name": "Mini Zeta"}
        assert body["from_nation"] is None
        assert body["to_nation"] == {
            "id": nation["id"],
            "short_name": nation["short_name"],
            "provinces_count": 5,
        }
        assert body["seizes"] is False
        assert body["capital_choice_needed"] is False
        assert body["capital_candidates"] == []
        assert body["donor_after"] is None
        assert body["receiver_after"] == 6
        assert body["blocker"] is None

    @pytest.mark.asyncio
    async def test_seize_preview_shape(self, live_client, monkeypatch):
        await _auth_headers(live_client, SECOND_VK_ID)
        receiver_id = await _seed_nation(
            SECOND_VK_ID,
            [1006, 1007],
            name="Receiver Realm",
            color_hex="#445566",
            short_name="BeR",
        )
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get(
            _preview_url(1002, receiver_id), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["province"] == {"id": 1002, "name": "Mini Beta"}
        assert body["from_nation"]["id"] == nation["id"]
        assert body["from_nation"]["short_name"] == nation["short_name"]
        assert body["from_nation"]["provinces_count"] == 5
        assert body["from_nation"]["capital_province_id"] == 1001
        assert body["to_nation"]["id"] == receiver_id
        assert body["to_nation"]["provinces_count"] == 2
        assert body["seizes"] is True
        assert body["capital_choice_needed"] is False
        assert body["donor_after"] == 4
        assert body["receiver_after"] == 3
        assert body["blocker"] is None

    @pytest.mark.asyncio
    async def test_capital_preview_offers_remaining(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        await _create_nation_as_player(live_client, OWNER_VK_ID)

        # 1001 is the nation's capital (first of province_ids, INV-14).
        response = await live_client.get(_preview_url(1001), headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["capital_choice_needed"] is True
        # The donor's remaining provinces, ordered by display name.
        assert body["capital_candidates"] == [
            {"id": 1002, "name": "Mini Beta"},
            {"id": 1004, "name": "Mini Delta"},
            {"id": 1005, "name": "Mini Epsilon"},
            {"id": 1003, "name": "Mini Gamma"},
        ]
        assert body["blocker"] is None

    @pytest.mark.asyncio
    async def test_last_province_blocker(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)
        await _seed_nation(
            OWNER_VK_ID,
            [1001],
            name="Solo Realm",
            color_hex="#334455",
            short_name="Solo",
        )
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get(_preview_url(1001), headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["blocker"] == "LAST_PROVINCE"
        assert body["donor_after"] == 0

    @pytest.mark.asyncio
    async def test_already_owner_blocker(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        # Transferring to the current owner.
        owned = await live_client.get(_preview_url(1001, nation["id"]), headers=headers)
        assert owned.status_code == 200
        assert owned.json()["blocker"] == "ALREADY_OWNER"

        # Releasing a province that is already free.
        free = await live_client.get(_preview_url(1006), headers=headers)
        assert free.status_code == 200
        assert free.json()["blocker"] == "ALREADY_OWNER"
        assert free.json()["from_nation"] is None

    @pytest.mark.asyncio
    async def test_preview_404s_and_sea(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)

        unknown = await live_client.get(_preview_url(9999), headers=headers)
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "PROVINCE_NOT_FOUND"

        sea = await live_client.get(_preview_url(2001), headers=headers)
        assert sea.status_code == 422
        assert sea.json()["code"] == "PROVINCE_NOT_LAND"

        missing_nation = await live_client.get(
            _preview_url(1006, "nation-missing"), headers=headers
        )
        assert missing_nation.status_code == 404
        assert missing_nation.json()["code"] == "NATION_NOT_FOUND"


class TestTransfer:
    """POST /api/v1/admin/provinces/{id}/transfer."""

    @pytest.mark.asyncio
    async def test_free_to_nation_writes_one_audit_row(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        response = await live_client.post(
            _transfer_url(1006),
            json={"to_nation_id": nation["id"]},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {
            "province_id": 1006,
            "previous_nation_id": None,
            "new_nation_id": nation["id"],
            "new_capital_province_id": None,
        }

        async with get_session_context() as session:
            assert (await session.get(Province, 1006)).nation_id == nation["id"]
            # The map's own listener wrote the journal entry.
            journal = list(
                (
                    await session.execute(
                        select(MapOwnershipLog).where(
                            MapOwnershipLog.province_id == 1006
                        )
                    )
                ).scalars()
            )
            assert len(journal) == 1
            assert journal[0].prev_nation_id is None
            assert journal[0].new_nation_id == nation["id"]
            assert journal[0].new_nation_short_name == "Testland"

        rows = await _audit_rows(action="province.transfer")
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_vk_user_id == ADMIN_VK_ID
        assert row.target_type == "province"
        assert row.target_id == "1006"
        assert row.summary == (
            "Свободная провинция «Mini Zeta» передана государству «Testland»."
        )
        assert row.details == {
            "province_id": 1006,
            "previous_nation_id": None,
            "new_nation_id": nation["id"],
            "new_capital_province_id": None,
            "seized": False,
        }

    @pytest.mark.asyncio
    async def test_seize_between_nations(self, live_client, monkeypatch):
        await _auth_headers(live_client, SECOND_VK_ID)
        receiver_id = await _seed_nation(
            SECOND_VK_ID,
            [1006, 1007],
            name="Receiver Realm",
            color_hex="#445566",
            short_name="BeR",
        )
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        # Without confirm_seize -> 409 SEIZE_NOT_CONFIRMED, no audit row.
        refused = await live_client.post(
            _transfer_url(1002),
            json={"to_nation_id": receiver_id},
            headers=headers,
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "SEIZE_NOT_CONFIRMED"
        assert await _audit_rows(action="province.transfer") == []

        response = await live_client.post(
            _transfer_url(1002),
            json={"to_nation_id": receiver_id, "confirm_seize": True},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["previous_nation_id"] == nation["id"]
        assert response.json()["new_nation_id"] == receiver_id

        rows = await _audit_rows(action="province.transfer")
        assert len(rows) == 1
        assert rows[0].summary == (
            "Провинция «Mini Beta» передана: «Testland» → «BeR»."
        )
        assert rows[0].details["seized"] is True

    @pytest.mark.asyncio
    async def test_release_writes_one_audit_row(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        response = await live_client.post(
            _transfer_url(1002), json={"to_nation_id": None}, headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["new_nation_id"] is None
        assert response.json()["previous_nation_id"] == nation["id"]

        async with get_session_context() as session:
            assert (await session.get(Province, 1002)).nation_id is None

        rows = await _audit_rows(action="province.transfer")
        assert len(rows) == 1
        assert rows[0].summary == (
            "Провинция «Mini Beta» выведена из-под государства «Testland»."
        )
        assert rows[0].details["seized"] is False

    @pytest.mark.asyncio
    async def test_capital_move_requires_and_updates(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        await _create_nation_as_player(live_client, OWNER_VK_ID)

        # 1001 is the nation's capital — moving it without a
        # replacement is refused.
        refused = await live_client.post(
            _transfer_url(1001), json={"to_nation_id": None}, headers=headers
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "CAPITAL_REQUIRED"

        # A replacement outside the donor's remaining provinces is
        # refused too.
        refused = await live_client.post(
            _transfer_url(1001),
            json={"to_nation_id": None, "new_capital_province_id": 1006},
            headers=headers,
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "CAPITAL_NOT_IN_PROVINCES"

        response = await live_client.post(
            _transfer_url(1001),
            json={"to_nation_id": None, "new_capital_province_id": 1002},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["new_capital_province_id"] == 1002

        async with get_session_context() as session:
            nation = (
                await session.execute(
                    select(Nation).where(Nation.short_name == "Testland")
                )
            ).scalar_one()
            assert nation.capital_province_id == 1002
            assert nation.capital_name == "Mini Beta"

        rows = await _audit_rows(action="province.transfer")
        assert len(rows) == 1
        assert rows[0].summary == (
            "Провинция «Mini Alpha» выведена из-под "
            "государства «Testland». Новая столица — «Mini Beta»."
        )
        assert rows[0].details["new_capital_province_id"] == 1002

    @pytest.mark.asyncio
    async def test_capital_name_unknown_hook_422(self, live_client, monkeypatch):
        """A replacement capital whose name no province-info hook knows
        is refused 422 PROVINCE_NAME_UNKNOWN."""
        headers = await _admin_headers(live_client, monkeypatch)
        await _create_nation_as_player(live_client, OWNER_VK_ID)

        # A replacement id no province-info hook knows a name for.
        response = await live_client.post(
            _transfer_url(1001),
            json={"to_nation_id": None, "new_capital_province_id": 5002},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "PROVINCE_NAME_UNKNOWN"

    @pytest.mark.asyncio
    async def test_last_province_refused_writes_nothing(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)
        nation_id = await _seed_nation(
            OWNER_VK_ID,
            [1001],
            name="Solo Realm",
            color_hex="#334455",
            short_name="Solo",
        )
        headers = await _admin_headers(live_client, monkeypatch)
        audit_before = len(await _audit_rows())

        response = await live_client.post(
            _transfer_url(1001), json={"to_nation_id": None}, headers=headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "LAST_PROVINCE"

        async with get_session_context() as session:
            assert (await session.get(Province, 1001)).nation_id == nation_id
            journal_count = (
                await session.execute(select(func.count()).select_from(MapOwnershipLog))
            ).scalar_one()
            assert journal_count == 0
        assert len(await _audit_rows()) == audit_before

    @pytest.mark.asyncio
    async def test_unknown_and_sea_refusals_write_nothing(
        self, live_client, monkeypatch
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        audit_before = len(await _audit_rows())

        unknown = await live_client.post(
            _transfer_url(9999), json={"to_nation_id": None}, headers=headers
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "PROVINCE_NOT_FOUND"

        sea = await live_client.post(
            _transfer_url(2001), json={"to_nation_id": None}, headers=headers
        )
        assert sea.status_code == 422
        assert sea.json()["code"] == "PROVINCE_NOT_LAND"

        missing_nation = await live_client.post(
            _transfer_url(1006),
            json={"to_nation_id": "nation-missing"},
            headers=headers,
        )
        assert missing_nation.status_code == 404
        assert missing_nation.json()["code"] == "NATION_NOT_FOUND"

        assert len(await _audit_rows()) == audit_before
