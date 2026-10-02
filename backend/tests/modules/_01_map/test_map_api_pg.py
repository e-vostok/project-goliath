"""
/map API on real PostgreSQL — DATABASE_URL_TEST (Spec Part 5).

Boots the real ASGI lifespan on the wiped/rebuilt PG test database via
``pg_live_client`` (mini map, admin allowlist 424242) and replays the
core Issue-4 flows: manifest/ETag, geometry, current state after a real
registration, a past-turn snapshot with a deleted nation's ``id = null``,
and the starting-group check. Mirrors the SQLite suite — the goal here
is dialect parity (window functions, IN-batch nation lookup, gzip).
"""

from __future__ import annotations

import pytest

from tests.fixtures.postgres import (
    ADMIN_VK_ID,
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_live_client,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._01_map.test_map_api import (
    MANIFEST_URL,
    STATE_URL,
    _auth_headers,
)

pytestmark = pytest.mark.postgres


class TestMapApiOnPostgres:
    @pytest.mark.asyncio
    async def test_manifest_and_geometry(self, pg_live_client):
        headers = await _auth_headers(pg_live_client, 9101)
        manifest = await pg_live_client.get(MANIFEST_URL, headers=headers)
        assert manifest.status_code == 200
        body = manifest.json()
        assert len(body["nodes"]) == 10
        assert len(body["edges"]) == 10
        etag = manifest.headers["etag"]

        again = await pg_live_client.get(
            MANIFEST_URL,
            headers={**headers, "If-None-Match": etag},
        )
        assert again.status_code == 304

        geo = await pg_live_client.get(
            f"/api/v1/map/geometry/{body['geometry_version']}",
            headers=headers,
        )
        assert geo.status_code == 200
        assert geo.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )

        wrong = await pg_live_client.get(
            "/api/v1/map/geometry/000000000000", headers=headers
        )
        assert wrong.status_code == 404
        assert wrong.json()["code"] == "MAP_VERSION_UNKNOWN"

    @pytest.mark.asyncio
    async def test_state_and_starting_group(self, pg_live_client):
        headers = await _auth_headers(pg_live_client, 9102)

        check = await pg_live_client.post(
            "/api/v1/map/starting-group/check",
            headers=headers,
            json={"province_ids": [1005, 1006]},
        )
        assert check.status_code == 200
        assert check.json() == {"connected": True, "component_count": 1}

        created = await pg_live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "PG Alpha",
                "color_hex": "#AA1100",
                "province_ids": [1001, 1002],
                **VALID_PROFILE,
            },
        )
        assert created.status_code == 201, created.text

        state = await pg_live_client.get(STATE_URL, headers=headers)
        assert state.status_code == 200
        body = state.json()
        assert body["turn"] == 0
        assert body["owners"] == [[1001, 0], [1002, 0]]
        assert body["nations"][0]["id"] == created.json()["id"]

    @pytest.mark.asyncio
    async def test_past_turn_after_delete(self, pg_live_client):
        """Delete at turn 0 -> past snapshot keeps id=null owner."""
        admin = await _auth_headers(pg_live_client, ADMIN_VK_ID)
        headers = await _auth_headers(pg_live_client, 9103)
        created = await pg_live_client.post(
            "/api/v1/nations",
            headers=headers,
            json={
                "name": "PG Beta",
                "color_hex": "#3311CC",
                "province_ids": [1001],
                **VALID_PROFILE,
            },
        )
        assert created.status_code == 201, created.text

        tick = await pg_live_client.post(
            "/api/v1/admin/tick/run", headers=admin
        )
        assert tick.status_code == 200 and tick.json()["current_turn"] == 1
        deleted = await pg_live_client.request(
            "DELETE",
            "/api/v1/nations/me",
            headers=headers,
            json={"confirm": True},
        )
        assert deleted.status_code == 204

        past = await pg_live_client.get(
            STATE_URL, params={"turn": 0}, headers=admin
        )
        assert past.status_code == 200
        body = past.json()
        assert body["owners"] == [[1001, 0]]
        assert body["nations"] == [
            {"id": None, "name": "PG Beta", "color_hex": "#3311CC"}
        ]

        out_of_range = await pg_live_client.get(
            STATE_URL, params={"turn": 2}, headers=admin
        )
        assert out_of_range.status_code == 422
        assert out_of_range.json()["code"] == "TURN_OUT_OF_RANGE"
