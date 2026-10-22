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
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.db import get_session
from core.security.jwt import issue_token
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock, Nation, Player, Province
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province

TEST_VK_SECRET = "test-vk-app-secret"  # noqa: S105
TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"  # noqa: S105

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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
    provinces = []
    for pid in ids:
        provinces.append(await make_land_province(session, id=pid))
    return provinces


async def seed_nation(
    session,
    player: Player,
    name: str = "Existing Nation",
    color_hex: str = "#112233",
    province_ids: list[int] | None = None,
    legacy: bool = False,
    short_name: str | None = None,
) -> Nation:
    nation = Nation(
        owner_player_id=player.id,
        name=name,
        color_hex=color_hex,
        # legacy=True simulates a pre-migration row (NULL profile —
        # ActiveIncomplete, Spec 1.3). short_name defaults to a unique
        # value derived from the nation's name: the column is UNIQUE
        # (INV-11), so seeding two nations with VALID_PROFILE's
        # constant would collide.
        **(
            {}
            if legacy
            else {
                **VALID_PROFILE,
                "short_name": short_name or name[:16],
            }
        ),
        created_at=datetime.now(UTC),
        created_turn=0,
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
        assert body["token_type"] == "bearer"  # noqa: S105
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
                    vk_user_id=555,
                    secret="wrong-secret",  # noqa: S106
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

        resp = await client.get("/api/v1/players/me", headers=bearer_headers(player.id))

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == player.id
        assert body["vk_user_id"] == player.vk_user_id


class TestNationEndpoints:
    """Tests for the nation lifecycle endpoints."""

    async def test_create_nation_happy_path(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002, 1003, 1004, 1005])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [1001, 1002, 1003, 1004, 1005],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Nation"
        assert body["color_hex"] == "#FF0000"
        assert body["owner_player_id"] == player.id
        assert body["province_ids"] == [1001, 1002, 1003, 1004, 1005]
        assert body["leader_name"] == VALID_PROFILE["leader_name"]
        assert body["leader_title"] == VALID_PROFILE["leader_title"]
        assert body["history_url"] == VALID_PROFILE["history_url"]
        assert body["short_name"] == VALID_PROFILE["short_name"]
        assert body["gender"] == VALID_PROFILE["gender"]
        assert body["succession_type"] == VALID_PROFILE["succession_type"]
        # INV-14: the capital defaults to the first province as sent.
        assert body["capital_province_id"] == 1001
        assert body["capital_name"] == VALID_PROFILE["capital_name"]
        # The owner's stats ride the response since 0.9.0 (unit 14).
        assert body["level"] == player.level
        assert body["judge_rating"] == player.judge_rating

    async def test_get_nations_me(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002])
        nation = await seed_nation(test_db_session, player, province_ids=[1001, 1002])

        resp = await client.get("/api/v1/nations/me", headers=bearer_headers(player.id))

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == nation.id
        assert body["province_ids"] == [1001, 1002]

    async def test_get_nations_me_not_found(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.get("/api/v1/nations/me", headers=bearer_headers(player.id))

        assert resp.status_code == 404
        assert resp.json()["code"] == "NATION_NOT_FOUND"

    async def test_create_nation_name_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001, 1002])
        await seed_nation(test_db_session, owner, name="Taken", province_ids=[1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Taken",
                "color_hex": "#00FF00",
                "province_ids": [1002],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "NAME_TAKEN"

    async def test_create_nation_color_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001, 1002])
        await seed_nation(
            test_db_session, owner, color_hex="#AABBCC", province_ids=[1001]
        )

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Other Nation",
                "color_hex": "#AABBCC",
                "province_ids": [1002],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "COLOR_TAKEN"

    async def test_create_nation_province_taken(self, client, test_db_session):
        owner = await seed_player(test_db_session, vk_user_id=111)
        player = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001, 1002])
        await seed_nation(test_db_session, owner, province_ids=[1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [1001, 1002],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "PROVINCE_TAKEN"

    async def test_create_nation_already_exists(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002])
        await seed_nation(test_db_session, player, province_ids=[1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Second Nation",
                "color_hex": "#00FF00",
                "province_ids": [1002],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "NATION_ALREADY_EXISTS"

    async def test_create_nation_province_not_found(self, client, test_db_session):
        player = await seed_player(test_db_session)

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": [999],
                **VALID_PROFILE,
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
            list(range(1001, 1002 + CORE_CONFIG.nation.max_provinces_per_nation)),
        )

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "#FF0000",
                "province_ids": list(
                    range(
                        1001,
                        1002 + CORE_CONFIG.nation.max_provinces_per_nation,
                    )
                ),
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422
        assert resp.json()["code"] == "PROVINCE_COUNT_OUT_OF_RANGE"

    async def test_create_nation_name_too_short(self, client, test_db_session):
        """Nation name length is enforced at the DTO layer."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "ab",
                "color_hex": "#FF0000",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422

    async def test_create_nation_name_too_long(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "x" * (CORE_CONFIG.nation.nation_name_max_length + 1),
                "color_hex": "#FF0000",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422

    async def test_create_nation_name_at_max_length(self, client, test_db_session):
        """The boundary is inclusive: exactly nation_name_max_length is fine."""
        player = await seed_player(test_db_session)
        province_ids = list(
            range(1001, 1001 + CORE_CONFIG.nation.min_provinces_per_nation)
        )
        await seed_provinces(test_db_session, province_ids)
        name = "x" * CORE_CONFIG.nation.nation_name_max_length

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": name,
                "color_hex": "#FF0000",
                "province_ids": province_ids,
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 201
        assert resp.json()["name"] == name

    async def test_create_nation_bad_color_format(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json={
                "name": "Test Nation",
                "color_hex": "red",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )

        assert resp.status_code == 422

    async def test_update_nation_happy_path(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])
        nation = await seed_nation(test_db_session, player, province_ids=[1001])

        resp = await client.patch(
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={
                "name": "Renamed Nation",
                "color_hex": "#00FF00",
                "leader_title": "Tsar of All Rus",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == nation.id
        assert body["name"] == "Renamed Nation"
        assert body["color_hex"] == "#00FF00"
        assert body["leader_title"] == "Tsar of All Rus"
        assert body["level"] == player.level
        assert body["judge_rating"] == player.judge_rating
        # Untouched fields keep their seeded values.
        assert body["leader_name"] == VALID_PROFILE["leader_name"]
        assert body["history_url"] == VALID_PROFILE["history_url"]

    async def test_update_nation_name_taken(self, client, test_db_session):
        player = await seed_player(test_db_session, vk_user_id=111)
        other = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001, 1002])
        await seed_nation(test_db_session, player, name="Mine", province_ids=[1001])
        await seed_nation(
            test_db_session,
            other,
            name="Theirs",
            color_hex="#445566",
            province_ids=[1002],
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

    async def test_delete_nations_me_route_gone(self, client, test_db_session):
        """The player DELETE route was removed in 0.9.0: the server
        answers 405 and the nation survives the call untouched."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002])
        nation = await seed_nation(test_db_session, player, province_ids=[1001, 1002])

        resp = await client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=bearer_headers(player.id),
            json={"confirm": True},
        )

        assert resp.status_code == 405
        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation.id)
        )
        assert result.scalar_one_or_none() is not None


# The exact response contract of GET /nations/{nation_id} (Spec Part 5):
# 20 keys, nothing more — a new key fails the key-set test.
NATION_PUBLIC_KEYS = {
    "id",
    "created_at",
    "name",
    "short_name",
    "color_hex",
    "motto",
    "description",
    "flag_id",
    "flag_url",
    "province_ids",
    "capital_province_id",
    "capital_name",
    "leader_name",
    "leader_title",
    "leader_bio",
    "portrait_id",
    "portrait_url",
    "history_url",
    "level",
    "judge_rating",
}


class TestNationPublic:
    """GET /api/v1/nations/{nation_id} — the public view of another
    player's nation (Bible §7, Spec Part 5, version 0.9.0 unit 14)."""

    async def test_returns_exact_public_key_set(self, client, test_db_session):
        """200 with exactly the 20 Spec keys — the service fields
        (owner_player_id, gender, succession_type, anthem_url) and any
        VK identifier can never leak through this route."""
        owner = await seed_player(test_db_session, vk_user_id=111)
        viewer = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001])
        nation = await seed_nation(test_db_session, owner, province_ids=[1001])

        resp = await client.get(
            f"/api/v1/nations/{nation.id}",
            headers=bearer_headers(viewer.id),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == NATION_PUBLIC_KEYS
        assert body["id"] == nation.id
        assert body["name"] == nation.name
        for key in (
            "owner_player_id",
            "gender",
            "succession_type",
            "anthem_url",
        ):
            assert key not in body

    async def test_unknown_and_malformed_id_are_404(
        self, client, test_db_session
    ):
        """An unknown UUID and a non-UUID string answer the same
        404 NATION_NOT_FOUND — a malformed id is never a 422."""
        viewer = await seed_player(test_db_session)

        for nation_id in (str(uuid.uuid4()), "abc"):
            resp = await client.get(
                f"/api/v1/nations/{nation_id}",
                headers=bearer_headers(viewer.id),
            )
            assert resp.status_code == 404
            assert resp.json()["code"] == "NATION_NOT_FOUND"

    async def test_own_and_public_routes_carry_owner_stats(
        self, client, test_db_session
    ):
        """level/judge_rating are the owner Player's columns: /nations/me
        and /nations/{id} both serve them, and a change in the players
        row shows on both routes."""
        owner = await seed_player(test_db_session, vk_user_id=111)
        viewer = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001])
        nation = await seed_nation(test_db_session, owner, province_ids=[1001])

        me = await client.get(
            "/api/v1/nations/me", headers=bearer_headers(owner.id)
        )
        assert me.status_code == 200
        assert me.json()["level"] == owner.level
        assert me.json()["judge_rating"] == owner.judge_rating

        # Change the owner's row in the real DB — both routes reflect it.
        owner.level = 7
        owner.judge_rating = 42
        await test_db_session.flush()

        me = await client.get(
            "/api/v1/nations/me", headers=bearer_headers(owner.id)
        )
        assert me.json()["level"] == 7
        assert me.json()["judge_rating"] == 42

        public = await client.get(
            f"/api/v1/nations/{nation.id}",
            headers=bearer_headers(viewer.id),
        )
        assert public.status_code == 200
        assert public.json()["level"] == 7
        assert public.json()["judge_rating"] == 42

    async def test_fixed_nation_paths_still_win(self, client, test_db_session):
        """The {nation_id} route is declared after /me, /rules and
        /color-check — all three fixed paths answer as before."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])
        nation = await seed_nation(test_db_session, player, province_ids=[1001])
        headers = bearer_headers(player.id)

        me = await client.get("/api/v1/nations/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["id"] == nation.id

        rules = await client.get("/api/v1/nations/rules", headers=headers)
        assert rules.status_code == 200
        assert (
            rules.json()["max_provinces"]
            == CORE_CONFIG.nation.max_provinces_per_nation
        )

        color = await client.post(
            "/api/v1/nations/color-check",
            headers=headers,
            json={"color_hex": "#FF0000"},
        )
        assert color.status_code == 200
        assert color.json()["status"] == "OK"

    async def test_public_province_ids_sorted_match_provinces_endpoint(
        self, client, test_db_session
    ):
        """province_ids is the sorted ownership list — the same ids
        GET /provinces reports for this nation."""
        owner = await seed_player(test_db_session, vk_user_id=111)
        viewer = await seed_player(test_db_session, vk_user_id=222)
        await seed_provinces(test_db_session, [1001, 1002, 1003, 1004])
        nation = await seed_nation(
            test_db_session, owner, province_ids=[1003, 1001, 1002]
        )

        resp = await client.get(
            f"/api/v1/nations/{nation.id}",
            headers=bearer_headers(viewer.id),
        )
        assert resp.status_code == 200
        assert resp.json()["province_ids"] == [1001, 1002, 1003]

        provinces = await client.get(
            "/api/v1/provinces", headers=bearer_headers(viewer.id)
        )
        owned = sorted(
            p["id"] for p in provinces.json() if p["nation_id"] == nation.id
        )
        assert resp.json()["province_ids"] == owned


class TestNationProfileEndpoints:
    """Profile fields over HTTP (Spec 1.1 Part 5)."""

    async def test_create_nation_missing_profile_field(self, client, test_db_session):
        """The three profile fields are required: FastAPI returns 422."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])

        body = {
            "name": "Test Nation",
            "color_hex": "#FF0000",
            "province_ids": [1001],
            **VALID_PROFILE,
        }
        del body["history_url"]

        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json=body,
        )

        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "field,value,code",
        [
            ("leader_name", "x", "LEADER_NAME_INVALID"),
            ("leader_title", "", "LEADER_TITLE_INVALID"),
            ("history_url", "https://evil.com/@x", "HISTORY_URL_INVALID"),
            ("flag_id", None, "FLAG_INVALID"),
            ("portrait_id", None, "PORTRAIT_INVALID"),
        ],
    )
    async def test_create_nation_profile_error_maps_to_422(
        self, client, test_db_session, field, value, code
    ):
        """Each domain error lands as HTTP 422 in the {detail, code} shape."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])

        body = {
            "name": "Test Nation",
            "color_hex": "#FF0000",
            "province_ids": [1001],
            **VALID_PROFILE,
            field: value,
        }
        resp = await client.post(
            "/api/v1/nations",
            headers=bearer_headers(player.id),
            json=body,
        )

        assert resp.status_code == 422
        payload = resp.json()
        assert payload["code"] == code
        assert payload["detail"]

    async def test_get_nations_me_legacy_null_profile(self, client, test_db_session):
        """A pre-migration nation returns null profile fields."""
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001])
        await seed_nation(test_db_session, player, province_ids=[1001], legacy=True)

        resp = await client.get("/api/v1/nations/me", headers=bearer_headers(player.id))

        assert resp.status_code == 200
        body = resp.json()
        assert body["leader_name"] is None
        assert body["leader_title"] is None
        assert body["history_url"] is None
        # Registration-2.0 fields are NULL too (ActiveIncomplete).
        assert body["short_name"] is None
        assert body["gender"] is None
        assert body["succession_type"] is None
        assert body["capital_province_id"] is None
        assert body["capital_name"] is None
        assert body["motto"] is None
        assert body["flag_id"] is None
        assert body["flag_url"] is None
        assert body["portrait_id"] is None
        assert body["portrait_url"] is None

    async def test_nations_rules_returns_config_values(self, client, test_db_session):
        """GET /nations/rules mirrors the loaded CoreConfig."""
        player = await seed_player(test_db_session)

        resp = await client.get(
            "/api/v1/nations/rules", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        body = resp.json()
        nation = CORE_CONFIG.nation
        assert body == {
            "name_min_length": nation.nation_name_min_length,
            "name_max_length": nation.nation_name_max_length,
            "short_name_min_length": nation.short_name_min_length,
            "short_name_max_length": nation.short_name_max_length,
            "motto_max_length": nation.motto_max_length,
            "description_max_length": nation.description_max_length,
            "leader_name_min_length": nation.leader_name_min_length,
            "leader_name_max_length": nation.leader_name_max_length,
            "leader_title_min_length": nation.leader_title_min_length,
            "leader_title_max_length": nation.leader_title_max_length,
            "leader_bio_max_length": nation.leader_bio_max_length,
            "capital_name_min_length": nation.capital_name_min_length,
            "capital_name_max_length": nation.capital_name_max_length,
            "history_url_max_length": nation.history_url_max_length,
            "history_url_allowed_hosts": nation.history_url_allowed_hosts,
            "anthem_url_max_length": nation.anthem_url_max_length,
            "anthem_url_allowed_hosts": nation.anthem_url_allowed_hosts,
            "min_provinces": nation.min_provinces_per_nation,
            "max_provinces": nation.max_provinces_per_nation,
            "palette": CORE_CONFIG.color.palette,
            "flags": [
                {"id": i, "url": f"/assets/nations/flags/{i}.png"}
                for i in CORE_CONFIG.catalog.flag_ids
            ],
            "portraits": [
                {"id": i, "url": f"/assets/nations/portraits/{i}.png"}
                for i in CORE_CONFIG.catalog.portrait_ids
            ],
            "genders": ["male", "female"],
            "succession_types": [
                "elections",
                "appointment",
                "criteria",
                "inheritance",
            ],
        }


class TestProvincesEndpoint:
    """Tests for GET /api/v1/provinces."""

    async def test_list_all_provinces(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002, 1003])

        resp = await client.get("/api/v1/provinces", headers=bearer_headers(player.id))

        assert resp.status_code == 200
        assert [p["id"] for p in resp.json()] == [1001, 1002, 1003]

    async def test_filter_by_ids(self, client, test_db_session):
        player = await seed_player(test_db_session)
        await seed_provinces(test_db_session, [1001, 1002, 1003])

        resp = await client.get(
            "/api/v1/provinces",
            headers=bearer_headers(player.id),
            params=[("ids", 1001), ("ids", 1003)],
        )

        assert resp.status_code == 200
        assert [p["id"] for p in resp.json()] == [1001, 1003]

    async def test_filter_free_only(self, client, test_db_session):
        player = await seed_player(test_db_session)
        other = await seed_player(test_db_session, vk_user_id=999)
        await seed_provinces(test_db_session, [1001, 1002, 1003])
        await seed_nation(test_db_session, other, province_ids=[1002])

        resp = await client.get(
            "/api/v1/provinces",
            headers=bearer_headers(player.id),
            params={"free_only": True},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [p["id"] for p in body] == [1001, 1003]
        assert all(p["nation_id"] is None for p in body)


class TestGameClockEndpoint:
    """Tests for GET /api/v1/game-clock."""

    async def test_game_clock_returns_derived_date(self, client, test_db_session):
        """game_date at turn 0 is the calendar epoch — January 2040."""
        player = await seed_player(test_db_session)
        next_tick = datetime.now(UTC) + timedelta(hours=24)
        test_db_session.add(GameClock(id=1, current_turn=0, next_tick_at=next_tick))
        await test_db_session.flush()

        resp = await client.get("/api/v1/game-clock", headers=bearer_headers(player.id))

        assert resp.status_code == 200
        body = resp.json()
        assert body["current_turn"] == 0
        assert body["game_date"] == "2040-01-01"
        assert body["game_date_text"] == "Январь 2040"


class TestAuthRequired:
    """Every protected endpoint rejects missing/bad Bearer tokens."""

    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("GET", "/api/v1/players/me", None),
            ("GET", "/api/v1/nations/me", None),
            ("GET", "/api/v1/nations/rules", None),
            (
                "GET",
                "/api/v1/nations/00000000-0000-0000-0000-000000000000",
                None,
            ),
            (
                "POST",
                "/api/v1/nations",
                {
                    "name": "Valid Name",
                    "color_hex": "#FF0000",
                    "province_ids": [1001],
                    **VALID_PROFILE,
                },
            ),
            ("PATCH", "/api/v1/nations/me", {"name": "Valid Name"}),
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
            ("GET", "/api/v1/nations/rules", None),
            (
                "GET",
                "/api/v1/nations/00000000-0000-0000-0000-000000000000",
                None,
            ),
            (
                "POST",
                "/api/v1/nations",
                {
                    "name": "Valid Name",
                    "color_hex": "#FF0000",
                    "province_ids": [1001],
                    **VALID_PROFILE,
                },
            ),
            ("PATCH", "/api/v1/nations/me", {"name": "Valid Name"}),
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
