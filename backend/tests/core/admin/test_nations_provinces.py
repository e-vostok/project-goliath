"""
Integration tests for the admin «Государства» endpoints (0.11.0 unit 8a):
GET /api/v1/admin/provinces, GET /api/v1/admin/nations and
POST /api/v1/admin/nations.

The live_client pattern of test_router.py: the REAL app over its real
ASGI lifespan (LifespanManager), a real Alembic-migrated temporary
database, real JWTs — no dependency overrides and no mocked DB state
(Anti-Mock Guard). The lifespan registers the 01_map province-info
hook, so the pickers see the linked mini map's display names.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

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
from modules._00_core.models import AdminAuditLog, Nation, Player, Province
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import MAP_MINI_LINKED_DIR, STARTING_GROUP
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]

ADMIN_VK_ID = 424242
OWNER_VK_ID = 777001
SECOND_VK_ID = 777002


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    The real app over its real lifespan on a migrated temporary SQLite
    file — the test_router.py live_client pattern, additionally
    snapshotting the province-info hook registry.
    """
    from tests.core.admin.test_router import PG_TEST_URL, _async_url, _reset_pg_schema

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


async def _auth_headers(client: AsyncClient, vk_user_id: int) -> dict:
    """Real login through /api/v1/auth/vk (creates the player row)."""
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


def _create_body(owner_vk_user_id: int, **overrides) -> dict:
    """A valid POST /admin/nations body over the linked mini map."""
    body = {
        "owner_vk_user_id": owner_vk_user_id,
        "name": "Admin-Made Nation",
        "color_hex": "#6A3446",
        "province_ids": list(STARTING_GROUP),
        "leader_name": VALID_PROFILE["leader_name"],
        "leader_title": VALID_PROFILE["leader_title"],
        "history_url": VALID_PROFILE["history_url"],
        "short_name": "Adminland",
        "gender": VALID_PROFILE["gender"],
        "succession_type": VALID_PROFILE["succession_type"],
    }
    body.update(overrides)
    return body


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


async def _audit_rows(action: str | None = None) -> list[AdminAuditLog]:
    """All admin_audit_log rows (optionally one action), oldest first."""
    async with get_session_context() as session:
        query = select(AdminAuditLog).order_by(AdminAuditLog.id)
        if action is not None:
            query = query.where(AdminAuditLog.action == action)
        return list((await session.execute(query)).scalars().all())


async def _nations_count() -> int:
    async with get_session_context() as session:
        return (
            await session.execute(select(func.count()).select_from(Nation))
        ).scalar_one()


async def _free_provinces_count() -> int:
    async with get_session_context() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(Province)
                .where(Province.nation_id.is_(None))
            )
        ).scalar_one()


class TestAdminProvinces:
    """GET /api/v1/admin/provinces — the unit-8a picker."""

    @pytest.mark.asyncio
    async def test_lists_land_with_names_sorted(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get("/api/v1/admin/provinces", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 13  # the linked mini map's 13 land nodes
        names = [item["name"] for item in data["items"]]
        assert names == sorted(names, key=str.casefold)
        assert "Mini Alpha" in names
        # Sea zones never appear; items carry the owner columns.
        assert all(item["nation_id"] is None for item in data["items"])
        assert all(item["nation_short_name"] is None for item in data["items"])

    @pytest.mark.asyncio
    async def test_free_only_hides_owned(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get(
            "/api/v1/admin/provinces?free_only=true", headers=headers
        )

        data = response.json()
        assert response.status_code == 200
        assert data["total"] == 8
        assert {item["id"] for item in data["items"]} == {
            1006,
            1007,
            1008,
            1009,
            1010,
            1011,
            1012,
            1013,
        }
        # Without the filter the owned rows expose their owner.
        full = await live_client.get("/api/v1/admin/provinces", headers=headers)
        owned = [item for item in full.json()["items"] if item["nation_id"] is not None]
        assert len(owned) == 5
        assert all(item["nation_short_name"] == "Testland" for item in owned)

    @pytest.mark.asyncio
    async def test_search_by_name_through_hook(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get(
            "/api/v1/admin/provinces?search=alpha", headers=headers
        )

        data = response.json()
        assert response.status_code == 200
        assert data["total"] == 1
        assert data["items"][0]["id"] == 1001
        assert data["items"][0]["name"] == "Mini Alpha"

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.get("/api/v1/admin/provinces", headers=headers)
        assert response.status_code == 403


class TestAdminNationsList:
    """GET /api/v1/admin/nations — the «Государства» list."""

    @pytest.mark.asyncio
    async def test_list_shape_and_order(self, live_client, monkeypatch):
        await _create_nation_as_player(
            live_client, OWNER_VK_ID, name="First Realm", short_name="FirstR"
        )
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get("/api/v1/admin/nations", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["name"] == "First Realm"
        assert item["short_name"] == "FirstR"
        assert item["owner_vk_user_id"] == OWNER_VK_ID
        assert item["provinces_count"] == 5
        assert item["capital_name"] == VALID_PROFILE["capital_name"]

    @pytest.mark.asyncio
    async def test_pagination_and_search(self, live_client, monkeypatch):
        await _create_nation_as_player(
            live_client, OWNER_VK_ID, name="Alpha Realm", short_name="AlR"
        )
        # A second nation seeded straight into the app's database (the
        # linked mini map cannot host a second 5-province group).
        await _auth_headers(live_client, SECOND_VK_ID)
        async with get_session_context() as session:
            owner = (
                await session.execute(
                    select(Player).where(Player.vk_user_id == SECOND_VK_ID)
                )
            ).scalar_one()
            session.add(
                Nation(
                    id=str(uuid.uuid4()),
                    owner_player_id=owner.id,
                    name="Beta Realm",
                    color_hex="#445566",
                    leader_name=VALID_PROFILE["leader_name"],
                    leader_title=VALID_PROFILE["leader_title"],
                    history_url=VALID_PROFILE["history_url"],
                    short_name="BeR",
                    gender=VALID_PROFILE["gender"],
                    succession_type=VALID_PROFILE["succession_type"],
                    capital_name=VALID_PROFILE["capital_name"],
                    created_at=datetime.now(UTC),
                    created_turn=0,
                )
            )
            await session.commit()
        headers = await _admin_headers(live_client, monkeypatch)

        page = await live_client.get(
            "/api/v1/admin/nations?limit=1&offset=0", headers=headers
        )
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert len(page.json()["items"]) == 1
        page2 = await live_client.get(
            "/api/v1/admin/nations?limit=1&offset=1", headers=headers
        )
        assert len(page2.json()["items"]) == 1
        assert page.json()["items"][0]["id"] != page2.json()["items"][0]["id"]

        hit = await live_client.get(
            "/api/v1/admin/nations?search=alpha", headers=headers
        )
        assert [i["name"] for i in hit.json()["items"]] == ["Alpha Realm"]
        miss = await live_client.get(
            "/api/v1/admin/nations?search=zzz", headers=headers
        )
        assert miss.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.get("/api/v1/admin/nations", headers=headers)
        assert response.status_code == 403


class TestAdminNationCreate:
    """POST /api/v1/admin/nations — NationService.create, unchanged."""

    @pytest.mark.asyncio
    async def test_creates_nation_and_audit_row(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)  # the owner exists
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID),
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["short_name"] == "Adminland"
        assert data["owner_vk_user_id"] == OWNER_VK_ID
        # No pictures (0.12.0 unit 4) and the map's capital name.
        assert "flag_id" not in data
        assert data["capital_name"] == "Mini Alpha"
        assert data["provinces_count"] == 5

        async with get_session_context() as session:
            nation = (
                await session.execute(select(Nation).where(Nation.id == data["id"]))
            ).scalar_one()
            assert nation.capital_province_id == STARTING_GROUP[0]
            assert nation.capital_name == "Mini Alpha"
            owned = (
                (
                    await session.execute(
                        select(Province.id).where(Province.nation_id == nation.id)
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(owned) == sorted(STARTING_GROUP)

        rows = await _audit_rows(action="nation.create")
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_vk_user_id == ADMIN_VK_ID
        assert row.target_type == "nation"
        assert row.target_id == data["id"]
        assert row.summary == (
            f"Создано государство «Adminland» для игрока {OWNER_VK_ID}."
        )
        assert row.details["nation_id"] == data["id"]
        assert row.details["province_ids"] == list(STARTING_GROUP)

    @pytest.mark.asyncio
    async def test_explicit_capital_uses_its_name(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID, capital_province_id=1003),
        )

        assert response.status_code == 200, response.text
        assert response.json()["capital_name"] == "Mini Gamma"
        async with get_session_context() as session:
            nation = (
                await session.execute(
                    select(Nation).where(Nation.id == response.json()["id"])
                )
            ).scalar_one()
            assert nation.capital_province_id == 1003

    @pytest.mark.asyncio
    async def test_owner_already_has_nation(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        nations_before = await _nations_count()
        audit_before = len(await _audit_rows())

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "NATION_ALREADY_EXISTS"
        assert await _nations_count() == nations_before
        assert len(await _audit_rows()) == audit_before

    @pytest.mark.asyncio
    async def test_name_taken(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID, name="Occupied Land")
        await _auth_headers(live_client, SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        nations_before = await _nations_count()

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(SECOND_VK_ID, name="Occupied Land"),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "NAME_TAKEN"
        assert await _nations_count() == nations_before
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_short_name_taken(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID, short_name="TakenSN")
        await _auth_headers(live_client, SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        nations_before = await _nations_count()

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(SECOND_VK_ID, short_name="TakenSN"),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "SHORT_NAME_TAKEN"
        assert await _nations_count() == nations_before
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_color_too_close(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _auth_headers(live_client, SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        nations_before = await _nations_count()

        # One channel step away from the existing nation's #123456.
        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(SECOND_VK_ID, color_hex="#123457"),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "COLOR_TOO_CLOSE"
        assert await _nations_count() == nations_before
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_province_taken(self, live_client, monkeypatch):
        await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _auth_headers(live_client, SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        free_before = await _free_provinces_count()

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(SECOND_VK_ID, color_hex="#8800CC"),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "PROVINCE_TAKEN"
        assert await _free_provinces_count() == free_before
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_no_provinces(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID, province_ids=[]),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "PROVINCE_COUNT_OUT_OF_RANGE"
        assert await _nations_count() == 0
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_capital_not_among_provinces(self, live_client, monkeypatch):
        await _auth_headers(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID, capital_province_id=1007),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "CAPITAL_NOT_IN_PROVINCES"
        assert await _nations_count() == 0
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_unknown_owner(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(999999999),
        )

        assert response.status_code == 404
        assert response.json()["code"] == "PLAYER_NOT_FOUND"
        assert await _audit_rows(action="nation.create") == []

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID),
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_province_ids_rejected(self, live_client, monkeypatch):
        """Unit-8b fix to 8a: a repeated id must not pass the count
        check — the request model answers 422 before the service."""
        await _auth_headers(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json=_create_body(OWNER_VK_ID, province_ids=[1001, 1002, 1003, 1004, 1004]),
        )

        assert response.status_code == 422
        assert await _nations_count() == 0
        assert await _audit_rows(action="nation.create") == []


async def _seed_nation(vk_user_id: int, **overrides) -> str:
    """A second nation straight into the app's database (the linked
    mini map cannot host a second 5-province group). Returns its id."""
    async with get_session_context() as session:
        owner = (
            await session.execute(select(Player).where(Player.vk_user_id == vk_user_id))
        ).scalar_one()
        nation = Nation(
            id=str(uuid.uuid4()),
            owner_player_id=owner.id,
            name="Beta Realm",
            color_hex="#445566",
            leader_name=VALID_PROFILE["leader_name"],
            leader_title=VALID_PROFILE["leader_title"],
            history_url=VALID_PROFILE["history_url"],
            short_name="BeR",
            gender=VALID_PROFILE["gender"],
            succession_type=VALID_PROFILE["succession_type"],
            capital_name=VALID_PROFILE["capital_name"],
            created_at=datetime.now(UTC),
            created_turn=0,
        )
        for key, value in overrides.items():
            setattr(nation, key, value)
        session.add(nation)
        await session.commit()
        return nation.id


async def _nation_row(nation_id: str) -> dict:
    """The nation's stored columns — the before/after snapshot for the
    'a refusal changes nothing' assertions."""
    async with get_session_context() as session:
        nation = (
            await session.execute(select(Nation).where(Nation.id == nation_id))
        ).scalar_one()
        return {
            column.name: getattr(nation, column.name)
            for column in Nation.__table__.columns
        }


class TestAdminNationGet:
    """GET /api/v1/admin/nations/{id} — the edit page's data."""

    @pytest.mark.asyncio
    async def test_returns_editable_fields(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.get(
            f"/api/v1/admin/nations/{created['id']}", headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["owner_vk_user_id"] == OWNER_VK_ID
        assert data["owner_name"] is None  # no display-name hook answer
        assert data["capital_province_id"] == STARTING_GROUP[0]
        assert data["provinces_count"] == 5
        assert data["name"] == "Player Nation"
        assert data["short_name"] == "Testland"
        assert data["color_hex"] == "#123456"
        assert data["leader_name"] == VALID_PROFILE["leader_name"]
        assert data["gender"] == VALID_PROFILE["gender"]
        assert data["succession_type"] == VALID_PROFILE["succession_type"]
        assert data["history_url"] == VALID_PROFILE["history_url"]
        assert data["capital_name"] == VALID_PROFILE["capital_name"]
        assert data["motto"] is None
        assert data["description"] is None
        assert data["leader_bio"] is None
        # Never editable here — not even returned as editable fields.
        assert "flag_id" not in data
        assert "portrait_id" not in data

    @pytest.mark.asyncio
    async def test_unknown_id_404(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        response = await live_client.get(
            f"/api/v1/admin/nations/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["code"] == "NATION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.get(
            f"/api/v1/admin/nations/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == 403


class TestAdminNationUpdate:
    """PATCH /api/v1/admin/nations/{id} — NationService.update + audit."""

    @pytest.mark.asyncio
    async def test_updates_only_sent_fields_and_audits(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={
                "name": "Renamed Realm",
                "motto": "All roads",
                "description": "A longer story.",
                "leader_bio": "Once a dockmaster.",
                "capital_name": "Newport",
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        after = await _nation_row(created["id"])
        assert after["name"] == "Renamed Realm"
        assert after["motto"] == "All roads"
        assert after["description"] == "A longer story."
        assert after["leader_bio"] == "Once a dockmaster."
        assert after["capital_name"] == "Newport"
        # Everything unsent stays — capital province,
        # colour, names and provinces above all.
        for key in (
            "short_name",
            "color_hex",
            "leader_name",
            "leader_title",
            "gender",
            "succession_type",
            "history_url",
            "capital_province_id",
            "owner_player_id",
        ):
            assert after[key] == before[key], key
        assert data["provinces_count"] == 5

        rows = await _audit_rows(action="nation.update")
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_vk_user_id == ADMIN_VK_ID
        assert row.target_type == "nation"
        assert row.target_id == created["id"]
        assert row.summary == (
            "Изменены данные государства «Testland»: полное название, "
            "девиз, описание, биография лидера, столица."
        )
        # Field codes only — never the sent texts.
        assert row.details["nation_id"] == created["id"]
        assert sorted(row.details["fields"]) == sorted(
            ["name", "motto", "description", "leader_bio", "capital_name"]
        )
        assert "Renamed Realm" not in str(row.details)

    @pytest.mark.asyncio
    async def test_clearing_optional_field(self, live_client, monkeypatch):
        """An empty string clears an optional field to NULL (INV-8) —
        and the journal still names the field."""
        created = await _create_nation_as_player(
            live_client, OWNER_VK_ID, motto="Old motto"
        )
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"motto": ""},
        )

        assert response.status_code == 200, response.text
        assert (await _nation_row(created["id"]))["motto"] is None
        rows = await _audit_rows(action="nation.update")
        assert len(rows) == 1
        assert rows[0].details["fields"] == ["motto"]

    @pytest.mark.asyncio
    async def test_name_taken_refusal(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _auth_headers(live_client, SECOND_VK_ID)
        await _seed_nation(SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"name": "Beta Realm"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "NAME_TAKEN"
        assert await _nation_row(created["id"]) == before
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_short_name_taken_refusal(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _auth_headers(live_client, SECOND_VK_ID)
        await _seed_nation(SECOND_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"short_name": "BeR"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "SHORT_NAME_TAKEN"
        assert await _nation_row(created["id"]) == before
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_color_too_close_refusal(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        await _auth_headers(live_client, SECOND_VK_ID)
        await _seed_nation(SECOND_VK_ID)  # colour #445566
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"color_hex": "#445567"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "COLOR_TOO_CLOSE"
        assert await _nation_row(created["id"]) == before
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_bad_field_format_refusal(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"leader_name": ""},  # mandatory — "" is not a clear
        )

        assert response.status_code == 422
        assert response.json()["code"] == "LEADER_NAME_INVALID"
        assert await _nation_row(created["id"]) == before
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_forbidden_field_422(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)
        before = await _nation_row(created["id"])

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={"flag_id": "flag_placeholder_2"},
        )

        assert response.status_code == 422
        assert await _nation_row(created["id"]) == before
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_empty_body_nothing_to_change(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        response = await live_client.patch(
            f"/api/v1/admin/nations/{created['id']}",
            headers=headers,
            json={},
        )

        assert response.status_code == 400
        assert response.json()["code"] == "NOTHING_TO_CHANGE"
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_unknown_id_404(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        response = await live_client.patch(
            f"/api/v1/admin/nations/{uuid.uuid4()}",
            headers=headers,
            json={"name": "No such nation"},
        )
        assert response.status_code == 404
        assert response.json()["code"] == "NATION_NOT_FOUND"
        assert await _audit_rows(action="nation.update") == []

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.patch(
            f"/api/v1/admin/nations/{uuid.uuid4()}",
            headers=headers,
            json={"name": "No such nation"},
        )
        assert response.status_code == 403


class TestAdminNationColorCheck:
    """POST /api/v1/admin/nations/color-check — the panel's own probe."""

    @pytest.mark.asyncio
    async def test_own_colour_ok_with_nation_id(self, live_client, monkeypatch):
        created = await _create_nation_as_player(live_client, OWNER_VK_ID)
        headers = await _admin_headers(live_client, monkeypatch)

        own = await live_client.post(
            "/api/v1/admin/nations/color-check",
            headers=headers,
            json={
                "color_hex": "#123456",
                "nation_id": created["id"],
            },
        )
        assert own.status_code == 200
        assert own.json() == {"status": "OK"}

        # Without the exclusion the very same colour is taken.
        clash = await live_client.post(
            "/api/v1/admin/nations/color-check",
            headers=headers,
            json={"color_hex": "#123456"},
        )
        assert clash.status_code == 200
        assert clash.json() == {"status": "TAKEN"}

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, live_client):
        headers = await _auth_headers(live_client, OWNER_VK_ID)
        response = await live_client.post(
            "/api/v1/admin/nations/color-check",
            headers=headers,
            json={"color_hex": "#123456"},
        )
        assert response.status_code == 403
