"""
Catalog placeholder set over the real API (Spec 1.3 Part 1, Issue 11).

``GET /api/v1/nations/rules`` must expose the six placeholder flags and
portraits with URLs built by ``catalog.py`` (INV-16), every URL must
resolve to a real file under ``frontend/public`` (INV-15), and
registration must accept a catalog ``flag_id`` while rejecting an id
outside the list with FLAG_INVALID.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.db import get_session
from core.security.jwt import issue_token
from main import app
from modules._00_core.catalog import flag_url, portrait_url
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Player
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_starting_group

REPO_ROOT = Path(__file__).resolve().parents[4]

TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"  # noqa: S105

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide the JWT secret for token issuing."""
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


async def test_catalog_placeholder_set_end_to_end(client, test_db_session):
    player = Player(vk_user_id=4242)
    test_db_session.add(player)
    await test_db_session.flush()
    province_ids = await make_starting_group(test_db_session)
    headers = bearer_headers(player.id)

    # The rules endpoint lists the whole catalog, urls via catalog.py.
    rules = await client.get("/api/v1/nations/rules", headers=headers)
    assert rules.status_code == 200
    body = rules.json()
    assert [item["id"] for item in body["flags"]] == (CORE_CONFIG.catalog.flag_ids)
    assert [item["id"] for item in body["portraits"]] == (
        CORE_CONFIG.catalog.portrait_ids
    )
    assert len(body["flags"]) == 6
    assert len(body["portraits"]) == 6
    for item in body["flags"]:
        assert item["url"] == flag_url(item["id"])
    for item in body["portraits"]:
        assert item["url"] == portrait_url(item["id"])

    # Every advertised URL maps to a real file under frontend/public.
    public = REPO_ROOT / "frontend" / "public"
    for item in body["flags"] + body["portraits"]:
        assert (public / item["url"].lstrip("/")).is_file(), item["url"]

    # A flag id outside the catalog is rejected (INV-15) — first, while
    # the player still has no nation and nothing gets persisted.
    rejected = await client.post(
        "/api/v1/nations",
        headers=headers,
        json={
            **VALID_PROFILE,
            "name": "Catalog Nation",
            "color_hex": "#FF0000",
            "province_ids": province_ids,
            "flag_id": "flag_not_in_catalog",
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "FLAG_INVALID"

    # The same player can then register with catalog ids.
    created = await client.post(
        "/api/v1/nations",
        headers=headers,
        json={
            **VALID_PROFILE,
            "name": "Catalog Nation",
            "color_hex": "#FF0000",
            "province_ids": province_ids,
            "flag_id": "flag_placeholder_1",
            "portrait_id": "portrait_placeholder_1",
        },
    )
    assert created.status_code == 201
    nation = created.json()
    assert nation["flag_id"] == "flag_placeholder_1"
    assert nation["flag_url"] == flag_url("flag_placeholder_1")
    assert nation["portrait_id"] == "portrait_placeholder_1"
    assert nation["portrait_url"] == portrait_url("portrait_placeholder_1")
