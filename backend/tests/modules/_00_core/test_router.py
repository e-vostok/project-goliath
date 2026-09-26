"""
Integration tests for the 00_core HTTP API.

Runs httpx.AsyncClient against the real FastAPI app with get_session
overridden to the shared in-memory test DB fixture. No mocking of the
DB session, JWT, or signature logic (Anti-Mock Guard).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.db import get_session
from core.security.jwt import issue_token
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock, Nation, Player, Province

TEST_VK_SECRET = "test-vk-app-secret"
TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


def make_launch_params(
    vk_user_id: int = 12345,
    secret: str = TEST_VK_SECRET,
    vk_ts: int | None = None,
) -> str:
    """Build a signed launch-params query string, as the VK client would."""
    params = {
        "vk_user_id": str(vk_user_id),
        "vk_app_id": "777",
        "vk_platform": "desktop_web",
        "vk_ts": str(vk_ts if vk_ts is not None else int(time.time())),
    }
    vk_params = sorted(
        (key, value) for key, value in params.items() if key.startswith("vk_")
    )
    base_string = urllib.parse.urlencode(vk_params)
    digest = hmac.new(
        secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256
    ).digest()
    sign = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return urllib.parse.urlencode(params) + "&sign=" + sign


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide VK/JWT secrets for every test."""
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test DB session."""
    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


def bearer_headers(player_id: str) -> dict[str, str]:
    """Build an Authorization header with a real issued JWT."""
    token = issue_token(player_id, CORE_CONFIG.auth.jwt_ttl_minutes)
    return {"Authorization": f"Bearer {token}"}


async def seed_player(session, vk_user_id: int = 12345) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


async def seed_provinces(session, ids: list[int]) -> list[Province]:
    provinces = [Province(id=pid, nation_id=None) for pid in ids]
    for p in provinces:
        session.add(p)
    await session.flush()
    return provinces


async def seed_nation(
    session, player: Player, name: str = "Existing Nation",
    color_hex: str = "#112233", province_ids: list[int] | None = None,
) -> Nation:
    nation = Nation(
        owner_player_id=player.id,
        name=name,
        color_hex=color_hex,
        created_at=datetime.now(timezone.utc),
    )
    session.add(nation)
    await session.flush()
    for pid in province_ids or []:
        result = await session.execute(select(Province).where(Province.id == pid))
        province = result.scalar_one()
        province.nation_id = nation.id
    await session.flush()
    return nation


class TestAuthVk:
    """Tests for POST /api/v1/auth/vk."""

    async def test_auth_new_player(self, client, test_db_session):
        """Happy path: a new player is created and a JWT is issued."""
        resp = await client.post(
            "/api/v1/auth/vk",
            json={"launch_params": make_launch_params(vk_user_id=555)},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == CORE_CONFIG.auth.jwt_ttl_minutes * 60
        assert body["player"]["vk_user_id"] == 555
        assert body["access_token"]

        # The issued token works against protected endpoints
        me = await client.get(
            "/api/v1/players/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["id"] == body["player"]["id"]

    async def test_auth_existing_player(self, client, test_db_session):
        """Happy path: an existing player gets a token, not a duplicate row."""
        existing = await seed_player(test_db_session, vk_user_id=777)

        resp = await client.post(
            "/api/v1/auth/vk",
            json={"launch_params": make_launch_params(vk_user_id=777)},
        )

        assert resp.status_code == 200
        assert resp.json()["player"]["id"] == existing.id

    async def test_auth_invalid_signature(self, client):
        """A bad signature returns 401 INVALID_SIGNATURE."""
        resp = await client.post(
            "/api/v1/auth/vk",
            json={
                "launch_params": make_launch_params(
                    vk_user_id=555, secret="wrong-secret"
                )
            },
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "INVALID_SIGNATURE"

    async def test_auth_expired_timestamp(self, client):
        """A stale vk_ts returns 401 TIMESTAMP_EXPIRED."""
        resp = await client.post(
            "/api/v1/auth/vk",
            json={
                "launch_params": make_launch_params(
                    vk_user_id=555, vk_ts=int(time.time()) - 3600
                )
            },
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "TIMESTAMP_EXPIRED"


class TestPlayersMe:
    """Tests for GET /api/v1/players/me."""

    async def test_returns_current_player(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.get(
            "/api/v1/players/me", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == player.id
        assert body["vk_user_id"] == player.vk_user_id


class TestNationEndpoints:
    """Tests for the nation lifecycle endpoints."""

    async def test_create_nation_happy_path(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2, 3])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [1, 2],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Nation"
        assert body["color_hex"] == "#FF0000"
        assert body["owner_player_id"] == player.id
        assert body["province_ids"] == [1, 2]

    async def test_get_nations_me(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2])
        nation = await seed_nation(
            test_db_session, player, province_ids=[1, 2]
        )

        resp = await client.get(
            "/api/v1/nations/me", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == nation.id
        assert body["province_ids"] == [1, 2]

    async def test_get_nations_me_not_found(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.get(
            "/api/v1/nations/me", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "NATION_NOT_FOUND"

    async def test_create_nation_name_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1, 2])
        await seed_nation(test_db_session, owner, name="Taken", province_ids=[1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Taken",
                "color_hex": "#00FF00",
                "province_ids": [2],
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "NAME_TAKEN"

    async def test_create_nation_color_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1, 2])
        await seed_nation(
            test_db_session, owner, color_hex="#AABBCC", province_ids=[1]
        )

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Other Nation",
                "color_hex": "#AABBCC",
                "province_ids": [2],
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "COLOR_TAKEN"

    async def test_create_nation_province_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1, 2])
        await seed_nation(test_db_session, owner, province_ids=[1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [1, 2],
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "PROVINCE_TAKEN"

    async def test_create_nation_already_exists(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2])
        await seed_nation(test_db_session, player, province_ids=[1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Second Nation",
                "color_hex": "#00FF00",
                "province_ids": [2],
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "NATION_ALREADY_EXISTS"

    async def test_create_nation_province_not_found(
        self, client, test_db_session
    ):
        player = await seed_player(test_db_session)

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [999],
            },
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "PROVINCE_NOT_FOUND"

    async def test_create_nation_province_count_out_of_range(
        self, client, test_db_session
    ):
        player = await seed_player(test_db_session)
        await seed_provinces(
            test_db_session,
            list(range(1, CORE_CONFIG.nation.max_provinces_per_nation + 2)),
        )

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": list(
                    range(1, CORE_CONFIG.nation.max_provinces_per_nation + 2)
                ),
            },
        )

        assert resp.status_code == 422
        assert resp.json()["code"] == "PROVINCE_COUNT_OUT_OF_RANGE"

    async def test_create_nation_name_too_short(self, client, test_db_session):
        """Nation name length is enforced at the DTO layer."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "ab",
                "color_hex": "#FF0000",
                "province_ids": [1],
            },
        )

        assert resp.status_code == 422

    async def test_create_nation_name_too_long(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "x" * (CORE_CONFIG.nation.nation_name_max_length + 1),
                "color_hex": "#FF0000",
                "province_ids": [1],
            },
        )

        assert resp.status_code == 422

    async def test_create_nation_bad_color_format(
        self, client, test_db_session
    ):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "red",
                "province_ids": [1],
            },
        )

        assert resp.status_code == 422

    async def test_update_nation_happy_path(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1])
        nation = await seed_nation(test_db_session, player, province_ids=[1])

        resp = await client.patch(
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"name": "Renamed Nation", "color_hex": "#00FF00"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == nation.id
        assert body["name"] == "Renamed Nation"
        assert body["color_hex"] == "#00FF00"

    async def test_update_nation_name_taken(self, client, test_db_session):
        player = await seed_player(test_db_session, vk_user_id=111)
        other = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1, 2])
        await seed_nation(test_db_session, player, name="Mine", province_ids=[1])
        await seed_nation(
            test_db_session, other, name="Theirs",
            color_hex="#445566", province_ids=[2],
        )

        resp = await client.patch(
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"name": "Theirs"},
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "NAME_TAKEN"

    async def test_update_nation_not_found(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.patch(
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"name": "Renamed"},
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "NATION_NOT_FOUND"

    async def test_delete_nation_happy_path(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2])
        nation = await seed_nation(
            test_db_session, player, province_ids=[1, 2]
        )

        resp = await client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"confirm": True},
        )

        assert resp.status_code == 204

        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation.id)
        )
        assert result.scalar_one_or_none() is None

        # Provinces were freed, not deleted (INV-6)
        result = await test_db_session.execute(
            select(Province).where(Province.id.in_([1, 2]))
        )
        assert all(p.nation_id is None for p in result.scalars().all())

    async def test_delete_nation_requires_confirm(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1])
        await seed_nation(test_db_session, player, province_ids=[1])

        resp = await client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"confirm": False},
        )

        assert resp.status_code == 422

    async def test_delete_nation_not_found(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"confirm": True},
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "NATION_NOT_FOUND"


class TestProvincesEndpoint:
    """Tests for GET /api/v1/provinces."""

    async def test_list_all_provinces(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2, 3])

        resp = await client.get(
            "/api/v1/provinces", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        assert [p["id"] for p in resp.json()] == [1, 2, 3]

    async def test_filter_by_ids(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1, 2, 3])

        resp = await client.get(
            "/api/v1/provinces",
            headers=bearer_headers(player.id),
            params=[("ids", 1), ("ids", 3)],
        )

        assert resp.status_code == 200
        assert [p["id"] for p in resp.json()] == [1, 3]

    async def test_filter_free_only(self, client, test_db_session):
        player = await seed_player(test_db_session)
        other = await seed_player(test_db_session, vk_user_id=999)
        await seed_provinces(test_db_session, [1, 2, 3])
        await seed_nation(test_db_session, other, province_ids=[2])

        resp = await client.get(
            "/api/v1/provinces",
            headers=bearer_headers(player.id),
            params={"free_only": True},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [p["id"] for p in body] == [1, 3]
        assert all(p["nation_id"] is None for p in body)


class TestGameClockEndpoint:
    """Tests for GET /api/v1/game-clock."""

    async def test_game_clock_returns_derived_date(
        self, client, test_db_session
    ):
        """game_date must match the Part 3 formula for a known turn."""
        player = await seed_player(test_db_session)
        current_turn = 10
        next_tick = datetime.now(timezone.utc) + timedelta(hours=24)
        test_db_session.add(
            GameClock(id=1, current_turn=current_turn, next_tick_at=next_tick)
        )
        await test_db_session.flush()

        resp = await client.get(
            "/api/v1/game-clock", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["current_turn"] == current_turn
        expected_date = CORE_CONFIG.calendar.epoch_start_date + timedelta(
            days=current_turn * CORE_CONFIG.calendar.days_per_turn
        )
        assert body["game_date"] == expected_date.isoformat()


class TestAuthRequired:
    """Every protected endpoint rejects missing/bad Bearer tokens."""

    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("GET", "/api/v1/players/me", None),
            ("GET", "/api/v1/nations/me", None),
            (
                "POST",
                "/api/v1/nations",
                {
                    "name": "Valid Name",
                    "color_hex": "#FF0000",
                    "province_ids": [1],
                },
            ),
            ("PATCH", "/api/v1/nations/me", {"name": "Valid Name"}),
            ("DELETE", "/api/v1/nations/me", {"confirm": True}),
            ("GET", "/api/v1/provinces", None),
            ("GET", "/api/v1/game-clock", None),
        ],
    )
    async def test_missing_token_rejected(self, client, method, url, body):
        resp = await client.request(method, url, json=body)

        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"

    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("GET", "/api/v1/players/me", None),
            ("GET", "/api/v1/nations/me", None),
            (
                "POST",
                "/api/v1/nations",
                {
                    "name": "Valid Name",
                    "color_hex": "#FF0000",
                    "province_ids": [1],
                },
            ),
            ("PATCH", "/api/v1/nations/me", {"name": "Valid Name"}),
            ("DELETE", "/api/v1/nations/me", {"confirm": True}),
            ("GET", "/api/v1/provinces", None),
            ("GET", "/api/v1/game-clock", None),
        ],
    )
    async def test_bad_token_rejected(self, client, method, url, body):
        resp = await client.request(
            method,
            url,
            json=body,
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"
