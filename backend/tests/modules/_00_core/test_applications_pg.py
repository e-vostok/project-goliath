"""
Application («анкета») race tests on real PostgreSQL (0.13.0 unit 4).

``test_two_concurrent_submits_one_name`` — the APP-1/APP-2 race: two
drafts carrying the same nation name submit at the same time; the
nations advisory lock serializes them so exactly one goes PENDING and
the loser gets NAME_TAKEN — never two rows, never an IntegrityError
surfacing as a 500.

Requires DATABASE_URL_TEST (pg_url fixture); skipped locally without it.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset,
    pg_live_client,  # noqa: F401 — resolved through the fixture chain
    pg_schema,  # noqa: F401 — resolved through the fixture chain,
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import STARTING_GROUP
from tests.modules._00_core.test_postgres_e2e import _auth, _headers

pytestmark = pytest.mark.postgres

# The linked mini-map's second connected land component — same set the
# concurrent-registration race uses.
STARTING_GROUP_2 = (1009, 1010, 1011, 1012, 1013)


def _body(province_ids: list[int], name: str, short_name: str, color: str) -> dict:
    return {
        "name": name,
        "short_name": short_name,
        "color_hex": color,
        "province_ids": province_ids,
        **{k: v for k, v in VALID_PROFILE.items() if k != "short_name"},
    }


@pytest.mark.asyncio
async def test_two_concurrent_submits_one_name(pg_live_client):
    """APP-1/APP-2: two simultaneous submits with the same nation name —
    the advisory lock lets exactly one through; the loser reads the
    winner's PENDING row and is refused with NAME_TAKEN."""
    client = pg_live_client
    token_a, _ = await _auth(client, vk_user_id=540001)
    token_b, _ = await _auth(client, vk_user_id=540002)

    body_a = _body(list(STARTING_GROUP), "Race Name", "RaceA", "#0C7CF4")
    body_b = _body(list(STARTING_GROUP_2), "Race Name", "RaceB", "#2B2DB0")

    for token, body in ((token_a, body_a), (token_b, body_b)):
        resp = await client.put(
            "/api/v1/applications/me", headers=_headers(token), json=body
        )
        assert resp.status_code == 200, resp.text

    resp_a, resp_b = await asyncio.gather(
        client.post(
            "/api/v1/applications/me/submit", headers=_headers(token_a)
        ),
        client.post(
            "/api/v1/applications/me/submit", headers=_headers(token_b)
        ),
    )

    statuses = sorted([resp_a.status_code, resp_b.status_code])
    assert statuses == [200, 409], (
        "expected exactly one accepted submit, got "
        f"{resp_a.status_code} / {resp_b.status_code} — "
        f"{resp_a.text} | {resp_b.text}"
    )
    loser = resp_a if resp_a.status_code == 409 else resp_b
    assert loser.json()["code"] == "NAME_TAKEN"


async def _admin_token(client) -> str:
    """A Bearer token for the env-allowlisted admin (ADMIN_VK_ID)."""
    from tests.fixtures.postgres import ADMIN_VK_ID

    token, _ = await _auth(client, vk_user_id=ADMIN_VK_ID)
    return token


@pytest.mark.asyncio
async def test_accept_vs_cancel_race(pg_live_client):
    """APP-3: a racing player cancel and admin accept — exactly one
    wins the row; the loser gets 409."""
    client = pg_live_client
    admin_token = await _admin_token(client)
    token, _ = await _auth(client, vk_user_id=541001)

    resp = await client.put(
        "/api/v1/applications/me",
        headers=_headers(token),
        json=_body(list(STARTING_GROUP), "Race Accept", "RaceAcc", "#0C7CF4"),
    )
    assert resp.status_code == 200, resp.text
    submitted = await client.post(
        "/api/v1/applications/me/submit", headers=_headers(token)
    )
    assert submitted.status_code == 200, submitted.text

    listing = await client.get(
        "/api/v1/admin/applications", headers=_headers(admin_token)
    )
    assert listing.status_code == 200, listing.text
    application_id = listing.json()["items"][0]["id"]

    resp_cancel, resp_accept = await asyncio.gather(
        client.post(
            "/api/v1/applications/me/cancel", headers=_headers(token)
        ),
        client.post(
            f"/api/v1/admin/applications/{application_id}/accept",
            headers=_headers(admin_token),
        ),
    )
    statuses = sorted([resp_cancel.status_code, resp_accept.status_code])
    assert statuses == [200, 409], (
        f"expected exactly one winner, got {statuses} — "
        f"{resp_cancel.text} | {resp_accept.text}"
    )
    loser = resp_cancel if resp_cancel.status_code == 409 else resp_accept
    assert loser.json()["code"] == "APPLICATION_NOT_PENDING"


@pytest.mark.asyncio
async def test_accept_vs_panel_nation_same_province(pg_live_client):
    """APP-2/INV-13: the accept's nation creation races a panel
    creation on the same province — the nations lock serializes them
    so exactly one wins."""
    client = pg_live_client
    admin_token = await _admin_token(client)
    token, _ = await _auth(client, vk_user_id=541002)
    owner_token, _ = await _auth(client, vk_user_id=541003)

    resp = await client.put(
        "/api/v1/applications/me",
        headers=_headers(token),
        json=_body(list(STARTING_GROUP), "Race Nation", "RaceNat", "#0C7CF4"),
    )
    assert resp.status_code == 200, resp.text
    submitted = await client.post(
        "/api/v1/applications/me/submit", headers=_headers(token)
    )
    assert submitted.status_code == 200, submitted.text

    listing = await client.get(
        "/api/v1/admin/applications", headers=_headers(admin_token)
    )
    application_id = listing.json()["items"][0]["id"]

    me = await client.get("/api/v1/players/me", headers=_headers(owner_token))
    owner_vk = me.json()["vk_user_id"]

    nation_body = {
        "owner_vk_user_id": owner_vk,
        "name": "Panel Nation",
        "short_name": "PanelNat",
        "color_hex": "#2B2DB0",
        "leader_name": "Ivan Grozny",
        "leader_title": "Supreme Ruler",
        "gender": "male",
        "succession_type": "elections",
        "history_url": "https://vk.com/@goliath-history",
        "province_ids": list(STARTING_GROUP),
    }
    resp_panel, resp_accept = await asyncio.gather(
        client.post(
            "/api/v1/admin/nations",
            headers=_headers(admin_token),
            json=nation_body,
        ),
        client.post(
            f"/api/v1/admin/applications/{application_id}/accept",
            headers=_headers(admin_token),
        ),
    )
    statuses = sorted([resp_panel.status_code, resp_accept.status_code])
    assert statuses in ([200, 409], [200, 422], [201, 409]), (
        f"expected exactly one winner, got {statuses} — "
        f"{resp_panel.text} | {resp_accept.text}"
    )
    loser = resp_panel if resp_panel.status_code != 200 else resp_accept
    assert loser.json()["code"] in {
        "PROVINCE_TAKEN",
        "PROVINCE_RESERVED",
        "APPLICATION_NOT_PENDING",
    }
