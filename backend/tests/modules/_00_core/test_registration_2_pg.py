"""
Registration 2.0 tests on real PostgreSQL (Spec 1.3, Issue 10).

- ``test_two_concurrent_registrations_one_color`` — THE key INV-13
  race: two registrations with nearly identical colors arrive at the
  same time on the real app; the advisory lock serializes the
  check-then-write sequence so exactly one is accepted and the other
  gets COLOR_TOO_CLOSE (or COLOR_TAKEN).
- ``test_migration_0011_up_down_up_postgres`` — the same
  upgrade/seed/upgrade/downgrade/upgrade rehearsal as the SQLite
  variant, against the dedicated *_test database: named UNIQUE,
  named FK with ON DELETE SET NULL, all eleven columns NULLABLE,
  existing rows untouched.

Requires DATABASE_URL_TEST (pg_url fixture); skipped locally without it.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.fixtures.postgres import (
    _reset_public_schema,
    _sync_url,
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_schema,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import STARTING_GROUP
from tests.modules._00_core.test_postgres_e2e import _auth, _headers

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[3]

# Two colors ~0.006 apart in OKLab — far below min_distance_nations
# (0.08), distinct strings so the UNIQUE column itself cannot fire.
RACE_COLOR_WINNER = "#0C7CF4"
RACE_COLOR_LOSER = "#0C7DF5"

# The linked mini-map's second connected land component.
STARTING_GROUP_2 = (1009, 1010, 1011, 1012, 1013)


@pytest.mark.asyncio
async def test_two_concurrent_registrations_one_color(pg_live_client):
    """INV-13: two simultaneous registrations with nearly identical
    colors — the advisory lock lets exactly one through; the loser
    reads the winner's row and is refused."""
    client = pg_live_client
    token_a, _ = await _auth(client, vk_user_id=530001)
    token_b, _ = await _auth(client, vk_user_id=530002)

    body_a = {
        "name": "Race Realm A",
        "color_hex": RACE_COLOR_WINNER,
        "province_ids": list(STARTING_GROUP),
        **VALID_PROFILE,
        "short_name": "RaceA",
    }
    body_b = {
        "name": "Race Realm B",
        "color_hex": RACE_COLOR_LOSER,
        "province_ids": list(STARTING_GROUP_2),
        **VALID_PROFILE,
        "short_name": "RaceB",
    }

    resp_a, resp_b = await asyncio.gather(
        client.post("/api/v1/nations", headers=_headers(token_a), json=body_a),
        client.post("/api/v1/nations", headers=_headers(token_b), json=body_b),
    )

    statuses = sorted([resp_a.status_code, resp_b.status_code])
    assert statuses == [201, 409], (
        "expected exactly one accepted registration, got "
        f"{resp_a.status_code} / {resp_b.status_code} — "
        f"{resp_a.text} | {resp_b.text}"
    )
    loser = resp_a if resp_a.status_code == 409 else resp_b
    assert loser.json()["code"] in (
        "COLOR_TAKEN",
        "COLOR_TOO_CLOSE",
    )


# --- Migration 0011 on PostgreSQL ------------------------------------------

_NEW_COLUMNS = [
    "short_name",
    "gender",
    "succession_type",
    "motto",
    "description",
    "leader_bio",
    "flag_id",
    "portrait_id",
    "anthem_url",
    "capital_province_id",
    "capital_name",
]


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _upgrade(url: str, target: str, monkeypatch) -> None:
    # env.py resolves DATABASE_URL; hand it the psycopg2 sync URL.
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.downgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def test_migration_0011_up_down_up_postgres(wiped_pg, monkeypatch):
    """Clean upgrade and downgrade of 0011 on real PostgreSQL: columns
    NULLABLE, ``uq_nations_short_name`` and the named capital FK
    present at head, existing rows untouched, downgrade drops only the
    eleven columns."""
    url = wiped_pg
    _upgrade(url, "0010", monkeypatch)

    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            nation_id = str(uuid.uuid4())
            player_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES (:id, 42424302, now())"
                ),
                {"id": player_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations (id, owner_player_id, name, "
                    "color_hex, created_at, created_turn) "
                    "VALUES (:id, :owner, 'Old Realm', '#0C7CF4', "
                    "now(), 3)"
                ),
                {"id": nation_id, "owner": player_id},
            )
    finally:
        engine.dispose()

    _upgrade(url, "head", monkeypatch)

    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            columns = {c["name"]: c for c in insp.get_columns("nations")}
            assert set(_NEW_COLUMNS) <= set(columns)
            for name in _NEW_COLUMNS:
                assert columns[name]["nullable"] is True

            uniques = {u["name"] for u in insp.get_unique_constraints("nations")}
            assert "uq_nations_short_name" in uniques

            fks = insp.get_foreign_keys("nations")
            capital_fk = next(
                f for f in fks if f["name"] == "fk_nations_capital_province_id"
            )
            assert capital_fk["referred_table"] == "provinces"
            assert capital_fk["constrained_columns"] == ["capital_province_id"]
            assert capital_fk["options"].get("ondelete") == "SET NULL"

            row = (
                conn.execute(
                    sa.text(
                        "SELECT name, color_hex, created_turn, short_name, "
                        "capital_province_id FROM nations WHERE id = :id"
                    ),
                    {"id": nation_id},
                )
                .mappings()
                .one()
            )
            assert row["name"] == "Old Realm"
            assert row["color_hex"] == "#0C7CF4"
            assert row["created_turn"] == 3
            assert row["short_name"] is None
            assert row["capital_province_id"] is None
    finally:
        engine.dispose()

    _downgrade(url, "0010", monkeypatch)

    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            columns = {c["name"] for c in sa.inspect(conn).get_columns("nations")}
            assert set(_NEW_COLUMNS).isdisjoint(columns)
            name = conn.execute(
                sa.text("SELECT name FROM nations WHERE id = :id"),
                {"id": nation_id},
            ).scalar_one()
            assert name == "Old Realm"
    finally:
        engine.dispose()

    _upgrade(url, "head", monkeypatch)

    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            columns = {c["name"] for c in sa.inspect(conn).get_columns("nations")}
            assert set(_NEW_COLUMNS) <= columns
    finally:
        engine.dispose()
