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
