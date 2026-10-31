"""
HTTP tests for the admin nation-image endpoints (0.12.0 unit 8):
GET /api/v1/admin/nations/{id} (the ``images`` block),
GET /api/v1/admin/nations/{id}/images/{kind}/delete-preview and
POST /api/v1/admin/nations/{id}/images/{kind}/delete.

Same live_client pattern as test_nation_delete.py: the REAL app over
its real ASGI lifespan on a migrated temporary database, real JWTs
through /api/v1/auth/vk, real uploads through the player's PUT
endpoint — no dependency overrides, no mocked DB state (Anti-Mock
Guard). Class-level hook registries are snapshotted and restored
around each test.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from PIL import Image
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
    NationImage,
    Player,
)
from modules._00_core.service import NationService
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.factories import make_vk_profile
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
    """The real app over its real lifespan on a migrated temporary
    database — the test_nation_delete.py live_client pattern."""
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


async def _seed_nation(vk_user_id: int) -> str:
    """A second nation straight into the app's database — the linked
    mini map cannot host a second 5-province group. Returns its id."""
    nation_id = str(uuid.uuid4())
    async with get_session_context() as session:
        owner = (
            await session.execute(select(Player).where(Player.vk_user_id == vk_user_id))
        ).scalar_one()
        session.add(
            Nation(
                id=nation_id,
                owner_player_id=owner.id,
                name="Второе Государство",
                color_hex="#445566",
                leader_name=VALID_PROFILE["leader_name"],
                leader_title=VALID_PROFILE["leader_title"],
                history_url=VALID_PROFILE["history_url"],
                short_name="Second",
                gender=VALID_PROFILE["gender"],
                succession_type=VALID_PROFILE["succession_type"],
                capital_name="Mini Beta",
                created_at=datetime.now(UTC),
                created_turn=0,
            )
        )
        await session.commit()
    return nation_id


def _png_bytes(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    """A real PNG the upload endpoint accepts (the test_nation_images.py
    generator — Pillow, no binary fixtures)."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


async def _upload(
    client: AsyncClient, headers: dict, kind: str, raw: bytes | None = None
) -> dict:
    """PUT a real picture through the player's own upload endpoint."""
    if raw is None:
        raw = _png_bytes((1200, 800) if kind == "flag" else (800, 1200))
    response = await client.put(
        f"/api/v1/nations/me/images/{kind}", headers=headers, content=raw
    )
    assert response.status_code == 200, response.text
    return response.json()


def _preview_url(nation_id: str, kind: str) -> str:
    return f"/api/v1/admin/nations/{nation_id}/images/{kind}/delete-preview"


def _delete_url(nation_id: str, kind: str) -> str:
    return f"/api/v1/admin/nations/{nation_id}/images/{kind}/delete"


class TestNationImageEditBlock:
    """The ``images`` block of GET/PATCH /admin/nations/{id}."""

    @pytest.mark.asyncio
    async def test_edit_data_shows_nulls_then_entries(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)

        # No uploads yet — both kinds are null.
        response = await live_client.get(
            f"/api/v1/admin/nations/{nation['id']}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["images"] == {"flag": None, "portrait": None}

        # The uploader's name resolves through the display-name hooks.
        async with get_session_context() as session:
            owner = (
                await session.execute(
                    select(Player).where(Player.vk_user_id == OWNER_VK_ID)
                )
            ).scalar_one()
            await make_vk_profile(session, owner, first_name="Иван", last_name="Петров")
            await session.commit()
        flag = await _upload(live_client, owner_headers, "flag")

        response = await live_client.get(
            f"/api/v1/admin/nations/{nation['id']}", headers=headers
        )
        images = response.json()["images"]
        entry = images["flag"]
        assert images["portrait"] is None
        assert entry["url"] == flag["url"]
        assert entry["thumb_url"] == flag["thumb_url"]
        assert entry["uploaded_at"].endswith("+00:00")
        assert entry["uploaded_by"] == {
            "vk_user_id": OWNER_VK_ID,
            "name": "Иван Петров",
        }

        # The PATCH answer carries the same block.
        patched = await live_client.patch(
            f"/api/v1/admin/nations/{nation['id']}",
            headers=headers,
            json={"motto": "Still standing"},
        )
        assert patched.status_code == 200
        assert patched.json()["images"] == images


class TestNationImageDeletePreview:
    """GET /nations/{id}/images/{kind}/delete-preview — read-only."""

    @pytest.mark.asyncio
    async def test_preview_returns_sentences_and_changes_nothing(
        self, live_client, monkeypatch
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        flag = await _upload(live_client, owner_headers, "flag")

        response = await live_client.get(
            _preview_url(nation["id"], "flag"), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["nation_id"] == nation["id"]
        assert body["short_name"] == nation["short_name"]
        assert body["kind"] == "flag"
        assert body["uploaded_at"].endswith("+00:00")
        assert body["uploaded_by"] == {
            "vk_user_id": OWNER_VK_ID,
            "name": None,
        }
        # The «Что будет» sentences of mockup 18b.
        assert body["consequences"] == [
            {
                "code": "image_deleted",
                "text": (
                    "картинка удаляется с сервера насовсем; в приказах, "
                    "где показан этот флаг, тоже появится заглушка"
                ),
            },
            {
                "code": "audit_journal",
                "text": ("в журнал попадёт запись «Удаление картинки государства»"),
            },
        ]

        # Read-only: the row and its URL survive, no journal row.
        async with get_session_context() as session:
            rows = (
                await session.execute(
                    select(func.count())
                    .select_from(NationImage)
                    .where(NationImage.nation_id == nation["id"])
                )
            ).scalar_one()
            assert rows == 1
            audit = (
                await session.execute(
                    select(func.count())
                    .select_from(AdminAuditLog)
                    .where(AdminAuditLog.action == "nation_image_delete")
                )
            ).scalar_one()
            assert audit == 0
        assert (await live_client.get(flag["url"])).status_code == 200


class TestNationImageDelete:
    """POST /nations/{id}/images/{kind}/delete."""

    @pytest.mark.asyncio
    async def test_delete_removes_only_that_kind_and_audits(
        self, live_client, monkeypatch, caplog
    ):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        flag = await _upload(live_client, owner_headers, "flag")
        portrait = await _upload(live_client, owner_headers, "portrait")
        preview = (
            await live_client.get(_preview_url(nation["id"], "flag"), headers=headers)
        ).json()

        with caplog.at_level(logging.WARNING, logger="core.admin.router"):
            response = await live_client.post(
                _delete_url(nation["id"], "flag"), json={}, headers=headers
            )

        # The answer is the preview that was true at deletion time.
        assert response.status_code == 200
        assert response.json() == preview

        # Only the flag row is gone; the old URL 404s with no-store,
        # the portrait's row and URL live on.
        async with get_session_context() as session:
            rows = list(
                (
                    await session.execute(
                        select(NationImage.kind).where(
                            NationImage.nation_id == nation["id"]
                        )
                    )
                ).scalars()
            )
            assert rows == ["portrait"]

        dead = await live_client.get(flag["url"])
        assert dead.status_code == 404
        assert dead.headers["cache-control"] == "no-store"
        assert (await live_client.get(portrait["url"])).status_code == 200

        # Exactly one journal row: ids and the 12-character sha prefix,
        # never the image bytes.
        async with get_session_context() as session:
            audit_rows = list(
                (
                    await session.execute(
                        select(AdminAuditLog).where(
                            AdminAuditLog.action == "nation_image_delete"
                        )
                    )
                ).scalars()
            )
            assert len(audit_rows) == 1
            row = audit_rows[0]
            assert row.actor_vk_user_id == ADMIN_VK_ID
            assert row.target_type == "nation"
            assert row.target_id == nation["id"]
            assert row.summary == (f"Удалён флаг государства «{nation['short_name']}».")
            sha256 = flag["url"].split("/")[-2]
            assert row.details == {
                "nation_id": nation["id"],
                "kind": "flag",
                "sha256_prefix": sha256[:12],
            }
            assert "full-" not in str(row.details)

        # One WARNING audit line naming the admin, the nation, the kind.
        audit = [
            r for r in caplog.records if "admin_nation_image_delete" in r.getMessage()
        ]
        assert len(audit) == 1
        assert audit[0].levelno == logging.WARNING
        assert str(ADMIN_VK_ID) in audit[0].getMessage()
        assert nation["id"] in audit[0].getMessage()

        # A second delete is a 404 IMAGE_NOT_FOUND — no second journal row.
        again = await live_client.post(
            _delete_url(nation["id"], "flag"), json={}, headers=headers
        )
        assert again.status_code == 404
        assert again.json()["code"] == "IMAGE_NOT_FOUND"
        async with get_session_context() as session:
            audit_count = (
                await session.execute(
                    select(func.count())
                    .select_from(AdminAuditLog)
                    .where(AdminAuditLog.action == "nation_image_delete")
                )
            ).scalar_one()
            assert audit_count == 1

    @pytest.mark.asyncio
    async def test_delete_leaves_identical_other_nation_alive(
        self, live_client, monkeypatch
    ):
        """Two nations uploaded the byte-identical file (one sha256):
        deleting the first nation's flag leaves the second row and its
        URL answering 200."""
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        second_headers = await _auth_headers(live_client, SECOND_VK_ID)
        await _seed_nation(SECOND_VK_ID)

        same_file = _png_bytes((1200, 800))
        up_first = await _upload(live_client, owner_headers, "flag", same_file)
        up_second = await _upload(live_client, second_headers, "flag", same_file)
        assert up_first["url"] == up_second["url"]

        response = await live_client.post(
            _delete_url(nation["id"], "flag"), json={}, headers=headers
        )
        assert response.status_code == 200

        # The shared hash keeps answering through the survivor row.
        assert (await live_client.get(up_second["url"])).status_code == 200
        async with get_session_context() as session:
            survivors = (
                await session.execute(
                    select(func.count())
                    .select_from(NationImage)
                    .where(NationImage.sha256 == up_second["url"].split("/")[-2])
                )
            ).scalar_one()
            assert survivors == 1


class TestNationImageDeleteGuards:
    """Auth and 404 cases of both new endpoints."""

    @pytest.mark.asyncio
    async def test_non_admin_gets_403_on_both_endpoints(self, live_client, monkeypatch):
        await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        user_headers = await _auth_headers(live_client, SECOND_VK_ID)

        preview = await live_client.get(
            _preview_url(nation["id"], "flag"), headers=user_headers
        )
        delete = await live_client.post(
            _delete_url(nation["id"], "flag"), json={}, headers=user_headers
        )

        for response in (preview, delete):
            assert response.status_code == 403
            assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_unknown_nation_wrong_kind_no_picture(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)

        for response in (
            await live_client.get(
                _preview_url("nation-missing", "flag"), headers=headers
            ),
            await live_client.post(
                _delete_url("nation-missing", "flag"), json={}, headers=headers
            ),
        ):
            assert response.status_code == 404
            assert response.json()["code"] == "NATION_NOT_FOUND"

        # A kind outside flag/portrait is a bare 404 — before the
        # nation lookup, same style as the player's upload endpoint.
        for response in (
            await live_client.get(
                _preview_url(nation["id"], "banner"), headers=headers
            ),
            await live_client.post(
                _delete_url(nation["id"], "banner"), json={}, headers=headers
            ),
        ):
            assert response.status_code == 404

        # The nation exists but has no such picture -> IMAGE_NOT_FOUND.
        for response in (
            await live_client.get(
                _preview_url(nation["id"], "portrait"), headers=headers
            ),
            await live_client.post(
                _delete_url(nation["id"], "portrait"), json={}, headers=headers
            ),
        ):
            assert response.status_code == 404
            assert response.json()["code"] == "IMAGE_NOT_FOUND"


class TestNationDeletePreviewImagesLine:
    """The nation delete-preview gains the pictures line (0.12.0 unit 8)."""

    @pytest.mark.asyncio
    async def test_line_only_when_pictures_exist(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        url = f"/api/v1/admin/nations/{nation['id']}/delete-preview"

        # No pictures — no nation_images consequence.
        response = await live_client.get(url, headers=headers)
        assert response.status_code == 200
        assert [c["code"] for c in response.json()["consequences"]] == [
            "ownership_journal"
        ]

        # One picture — the line names just that kind.
        await _upload(live_client, owner_headers, "flag")
        response = await live_client.get(url, headers=headers)
        assert response.json()["consequences"][-1] == {
            "code": "nation_images",
            "text": "удалятся загруженные картинки: флаг",
        }

        # Both kinds — the line lists them in flag-then-portrait order.
        await _upload(live_client, owner_headers, "portrait")
        response = await live_client.get(url, headers=headers)
        assert response.json()["consequences"][-1] == {
            "code": "nation_images",
            "text": "удалятся загруженные картинки: флаг, портрет",
        }


class TestAdminListFlagThumbs:
    """``flag_thumb_url`` on the admin lists (0.12.0 unit 9): the
    address is the CURRENT flag's ``/api/v1/images/<sha>/thumb`` —
    one ``image_refs`` call per page, never per row."""

    @pytest.mark.asyncio
    async def test_nations_list_and_create_answer(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        flag = await _upload(live_client, owner_headers, "flag")
        thumb = flag["thumb_url"]
        await _auth_headers(live_client, SECOND_VK_ID)
        await _seed_nation(SECOND_VK_ID)  # a nation without a flag

        calls = []
        original = NationService.image_refs

        async def counting(session, nation_ids):
            calls.append(list(nation_ids))
            return await original(session, nation_ids)

        monkeypatch.setattr(NationService, "image_refs", counting)
        response = await live_client.get("/api/v1/admin/nations", headers=headers)
        assert response.status_code == 200
        assert len(calls) == 1  # one image_refs for the whole page

        items = {item["id"]: item for item in response.json()["items"]}
        assert items[nation["id"]]["flag_thumb_url"] == thumb
        assert (
            items[next(i for i in items if i != nation["id"])]["flag_thumb_url"] is None
        )

        # POST /admin/nations answers the same item shape — a brand-new
        # nation has no pictures, so the field is null.
        await _auth_headers(live_client, 100000003)
        created = await live_client.post(
            "/api/v1/admin/nations",
            headers=headers,
            json={
                "owner_vk_user_id": 100000003,
                "name": "Третья Держава",
                "short_name": "Третья",
                "color_hex": "#226644",
                "leader_name": VALID_PROFILE["leader_name"],
                "leader_title": VALID_PROFILE["leader_title"],
                "gender": VALID_PROFILE["gender"],
                "succession_type": VALID_PROFILE["succession_type"],
                "history_url": VALID_PROFILE["history_url"],
                "motto": None,
                "province_ids": [1009, 1010, 1011, 1012, 1013],
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["flag_thumb_url"] is None

    @pytest.mark.asyncio
    async def test_provinces_list_carries_owner_flag(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        flag = await _upload(live_client, owner_headers, "flag")

        calls = []
        original = NationService.image_refs

        async def counting(session, nation_ids):
            calls.append(list(nation_ids))
            return await original(session, nation_ids)

        monkeypatch.setattr(NationService, "image_refs", counting)
        response = await live_client.get("/api/v1/admin/provinces", headers=headers)
        assert response.status_code == 200
        assert len(calls) == 1

        items = response.json()["items"]
        owned = [i for i in items if i["nation_id"] == nation["id"]]
        free = [i for i in items if i["nation_id"] is None]
        assert owned and free
        assert all(i["flag_thumb_url"] == flag["thumb_url"] for i in owned)
        assert all(i["flag_thumb_url"] is None for i in free)

    @pytest.mark.asyncio
    async def test_thumb_follows_replace_and_delete(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        first = await _upload(live_client, owner_headers, "flag")

        async def current_thumb() -> str | None:
            response = await live_client.get("/api/v1/admin/nations", headers=headers)
            return next(
                i["flag_thumb_url"]
                for i in response.json()["items"]
                if i["id"] == nation["id"]
            )

        assert await current_thumb() == first["thumb_url"]

        # A replacement upload moves the address to the new sha256.
        second = await _upload(
            live_client,
            owner_headers,
            "flag",
            _png_bytes((1200, 800), color=(200, 30, 30)),
        )
        assert second["thumb_url"] != first["thumb_url"]
        assert await current_thumb() == second["thumb_url"]

        # The unit-8 deletion drops the field back to null.
        deleted = await live_client.post(
            _delete_url(nation["id"], "flag"), json={}, headers=headers
        )
        assert deleted.status_code == 200
        assert await current_thumb() is None

    @pytest.mark.asyncio
    async def test_edit_entry_size_and_dimensions(self, live_client, monkeypatch):
        headers = await _admin_headers(live_client, monkeypatch)
        nation = await _create_nation_as_player(live_client, OWNER_VK_ID)
        owner_headers = await _auth_headers(live_client, OWNER_VK_ID)
        await _upload(live_client, owner_headers, "flag")
        await _upload(live_client, owner_headers, "portrait")

        response = await live_client.get(
            f"/api/v1/admin/nations/{nation['id']}", headers=headers
        )
        entry = response.json()["images"]["flag"]
        assert set(entry) == {
            "url",
            "thumb_url",
            "uploaded_at",
            "uploaded_by",
            "size_bytes",
            "width",
            "height",
        }
        async with get_session_context() as session:
            full_len = (
                await session.execute(
                    select(func.length(NationImage.full_bytes)).where(
                        NationImage.nation_id == nation["id"],
                        NationImage.kind == "flag",
                    )
                )
            ).scalar_one()
        # The real length of the stored full variant — no bytes loaded.
        assert entry["size_bytes"] == full_len
        # The pipeline's target sizes from the images config section.
        assert (entry["width"], entry["height"]) == (600, 400)
        portrait = response.json()["images"]["portrait"]
        assert (portrait["width"], portrait["height"]) == (600, 800)
