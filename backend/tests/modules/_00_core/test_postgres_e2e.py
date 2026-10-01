"""
End-to-end verification on real PostgreSQL (module 00_core, Issue 9).

Every scenario drives the app through its real ASGI lifespan and the
production engine path (init_engine in lifespan) against a migrated,
wiped, dedicated *_test PostgreSQL database — the deployment shape.
HTTP exercises the API surface; pg_db gives DB-direct assertions on a
second connection, so only truly committed state can satisfy a check.

Anti-Mock Guard: no get_session override, no mocked DB/HTTP/orchestrator.
Limits come from GET /nations/rules / CoreConfig — never hardcoded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from core.tick.orchestrator import TickOrchestrator, TickPhase
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
    TickLog,
    TickLogStatus,
)
from tests.fixtures.postgres import (
    ADMIN_VK_ID,
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_live_client,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._00_core.test_router import (
    TEST_VK_SECRET,
    make_launch_params,
)

pytestmark = pytest.mark.postgres

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _auth(client, vk_user_id: int) -> tuple[str, str]:
    """POST /auth/vk with signed params; return (token, player_id)."""
    resp = await client.post(
        "/api/v1/auth/vk",
        json={
            "launch_params": make_launch_params(
                vk_user_id=vk_user_id, secret=TEST_VK_SECRET
            )
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["access_token"], body["player"]["id"]


def _nation_snapshot(nation: Nation) -> dict:
    """Every column of a nation row, as a plain dict."""
    return {
        column.name: getattr(nation, column.name)
        for column in Nation.__table__.columns
    }


async def _fetch_nation(pg_db, nation_id: str) -> Nation | None:
    async with pg_db() as session:
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        return result.scalar_one_or_none()


async def _province_owners(pg_db, ids: list[int]) -> dict[int, str | None]:
    async with pg_db() as session:
        result = await session.execute(
            select(Province).where(Province.id.in_(ids))
        )
        return {p.id: p.nation_id for p in result.scalars().all()}


async def _assert_world_clean(pg_db, province_ids: list[int]) -> None:
    """No nation rows exist and the given provinces are free."""
    async with pg_db() as session:
        nations = await session.execute(
            select(func.count()).select_from(Nation)
        )
        assert nations.scalar_one() == 0
        owners = await session.execute(
            select(Province.nation_id).where(Province.id.in_(province_ids))
        )
        owner_ids = owners.scalars().all()
    assert len(owner_ids) == len(province_ids)
    assert all(owner is None for owner in owner_ids)


async def test_nation_lifecycle_on_postgres(pg_live_client, pg_db):
    """auth -> rules -> create -> read -> patch -> reject -> delete."""
    client = pg_live_client
    token, player_id = await _auth(client, vk_user_id=910001)

    rules = await client.get("/api/v1/nations/rules", headers=_headers(token))
    assert rules.status_code == 200
    nation_cfg = CORE_CONFIG.nation
    assert rules.json() == {
        "name_min_length": nation_cfg.nation_name_min_length,
        "name_max_length": nation_cfg.nation_name_max_length,
        "leader_name_min_length": nation_cfg.leader_name_min_length,
        "leader_name_max_length": nation_cfg.leader_name_max_length,
        "leader_title_min_length": nation_cfg.leader_title_min_length,
        "leader_title_max_length": nation_cfg.leader_title_max_length,
        "history_url_max_length": nation_cfg.history_url_max_length,
        "history_url_allowed_hosts": nation_cfg.history_url_allowed_hosts,
        "min_provinces": nation_cfg.min_provinces_per_nation,
        "max_provinces": nation_cfg.max_provinces_per_nation,
    }

    # Profile values padded with whitespace: stored normalized (strip).
    create = await client.post(
        "/api/v1/nations",
        headers=_headers(token),
        json={
            "name": "Northern Reach",
            "color_hex": "#1A2B3C",
            "province_ids": [1, 2],
            "leader_name": f"  {VALID_PROFILE['leader_name']}  ",
            "leader_title": f"  {VALID_PROFILE['leader_title']}  ",
            "history_url": f"  {VALID_PROFILE['history_url']}  ",
        },
    )
    assert create.status_code == 201, create.text
    nation_id = create.json()["id"]

    nation = await _fetch_nation(pg_db, nation_id)
    assert nation.owner_player_id == player_id
    assert nation.name == "Northern Reach"
    assert nation.leader_name == VALID_PROFILE["leader_name"]
    assert nation.leader_title == VALID_PROFILE["leader_title"]
    assert nation.history_url == VALID_PROFILE["history_url"]
    assert await _province_owners(pg_db, [1, 2, 3]) == {
        1: nation_id,
        2: nation_id,
        3: None,
    }

    me = await client.get("/api/v1/nations/me", headers=_headers(token))
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == nation_id
    assert body["leader_name"] == VALID_PROFILE["leader_name"]
    assert body["leader_title"] == VALID_PROFILE["leader_title"]
    assert body["history_url"] == VALID_PROFILE["history_url"]
    assert body["province_ids"] == [1, 2]

    # PATCH leader_title: exactly that one column changes in the DB.
    before = _nation_snapshot(await _fetch_nation(pg_db, nation_id))
    patch = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"leader_title": "Grand Prince"},
    )
    assert patch.status_code == 200, patch.text
    after = _nation_snapshot(await _fetch_nation(pg_db, nation_id))
    changed = {key for key in before if before[key] != after[key]}
    assert changed == {"leader_title"}
    assert after["leader_title"] == "Grand Prince"

    # Userinfo-spoofed history link: rejected, nothing mutates.
    bad = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"history_url": "https://vk.com@evil.com/@x"},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "HISTORY_URL_INVALID"
    assert _nation_snapshot(await _fetch_nation(pg_db, nation_id)) == after

    # DELETE: the row goes, the provinces are freed — not deleted.
    delete = await client.request(
        "DELETE",
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"confirm": True},
    )
    assert delete.status_code == 204
    assert await _fetch_nation(pg_db, nation_id) is None
    assert await _province_owners(pg_db, [1, 2]) == {1: None, 2: None}


class TestCreateRejections:
    """Every rejected POST must persist nothing and free nothing."""

    @pytest.mark.parametrize(
        "field,code",
        [
            ("leader_name", "LEADER_NAME_INVALID"),
            ("leader_title", "LEADER_TITLE_INVALID"),
            ("history_url", "HISTORY_URL_INVALID"),
        ],
    )
    async def test_invalid_profile_field(
        self, pg_live_client, pg_db, field, code
    ):
        # Invalid values derived from the rules, not hardcoded limits:
        # newline (control char), below-min-length, non-https scheme.
        bad_values = {
            "leader_name": "Ivan\nGrozny",
            "leader_title": "x"
            * (CORE_CONFIG.nation.leader_title_min_length - 1),
            "history_url": "http://vk.com/@x",
        }
        token, _ = await _auth(pg_live_client, vk_user_id=920001)
        body = {
            "name": "Rejected Realm",
            "color_hex": "#A0B1C2",
            "province_ids": [5],
            **VALID_PROFILE,
        }
        body[field] = bad_values[field]

        resp = await pg_live_client.post(
            "/api/v1/nations", headers=_headers(token), json=body
        )

        assert resp.status_code == 422
        payload = resp.json()
        assert payload["code"] == code
        assert payload["detail"]
        await _assert_world_clean(pg_db, [5])

    async def test_missing_profile_field_is_fastapi_422(
        self, pg_live_client, pg_db
    ):
        """An absent required field hits pydantic, not the domain layer:
        422 in FastAPI's own shape (a detail list, no domain code)."""
        token, _ = await _auth(pg_live_client, vk_user_id=920002)
        body = {
            "name": "Rejected Realm",
            "color_hex": "#A0B1C2",
            "province_ids": [5],
            **VALID_PROFILE,
        }
        del body["history_url"]

        resp = await pg_live_client.post(
            "/api/v1/nations", headers=_headers(token), json=body
        )

        assert resp.status_code == 422
        assert "code" not in resp.json()
        await _assert_world_clean(pg_db, [5])

    async def test_already_exists_beats_profile_validation(
        self, pg_live_client, pg_db
    ):
        """Spec Part 2 check order: INV-1 precedes profile validation, so
        a second POST with an invalid profile answers 409 — not 422."""
        token, _ = await _auth(pg_live_client, vk_user_id=920003)
        first = await pg_live_client.post(
            "/api/v1/nations",
            headers=_headers(token),
            json={
                "name": "First Realm",
                "color_hex": "#123123",
                "province_ids": [6],
                **VALID_PROFILE,
            },
        )
        assert first.status_code == 201
        nation_id = first.json()["id"]

        second = await pg_live_client.post(
            "/api/v1/nations",
            headers=_headers(token),
            json={
                "name": "Second Realm",
                "color_hex": "#321321",
                "province_ids": [7],
                "leader_name": "Broken\nName",
                "leader_title": "x",
                "history_url": "http://vk.com/@x",
            },
        )
        assert second.status_code == 409
        assert second.json()["code"] == "NATION_ALREADY_EXISTS"

        async with pg_db() as session:
            result = await session.execute(select(Nation))
            assert [n.id for n in result.scalars().all()] == [nation_id]
        assert await _province_owners(pg_db, [6, 7]) == {
            6: nation_id,
            7: None,
        }


async def test_legacy_nation_null_profile_on_postgres(pg_live_client, pg_db):
    """A pre-migration nation (NULL profile) reads nulls, accepts a plain
    rename, fills its profile field by field, and refuses empty values."""
    client = pg_live_client
    token, player_id = await _auth(client, vk_user_id=930001)
    nation_id = str(uuid.uuid4())

    async with pg_db() as session:
        await session.execute(
            text(
                "INSERT INTO nations "
                "(id, owner_player_id, name, color_hex, created_at) "
                "VALUES (:id, :owner, :name, :color, :created_at)"
            ),
            {
                "id": nation_id,
                "owner": player_id,
                "name": "Old Realm",
                "color": "#778899",
                "created_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(
            text(
                "UPDATE provinces SET nation_id = :nid "
                "WHERE id IN (10, 11)"
            ),
            {"nid": nation_id},
        )
        await session.commit()

    me = await client.get("/api/v1/nations/me", headers=_headers(token))
    assert me.status_code == 200
    body = me.json()
    assert body["leader_name"] is None
    assert body["leader_title"] is None
    assert body["history_url"] is None
    assert body["province_ids"] == [10, 11]

    # A plain rename works on a legacy row; profile stays NULL.
    patch = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"name": "Renamed Realm"},
    )
    assert patch.status_code == 200, patch.text
    nation = await _fetch_nation(pg_db, nation_id)
    assert nation.name == "Renamed Realm"
    assert nation.leader_name is None
    assert nation.leader_title is None
    assert nation.history_url is None

    # One field at a time: the profile is still incomplete.
    patch = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"leader_name": "Boris Godunov"},
    )
    assert patch.status_code == 200
    nation = await _fetch_nation(pg_db, nation_id)
    assert nation.leader_name == "Boris Godunov"
    assert nation.leader_title is None
    assert nation.history_url is None

    # The remaining two fields complete the profile.
    patch = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={
            "leader_title": "Tsar of Old Realm",
            "history_url": "https://vk.com/@old-realm",
        },
    )
    assert patch.status_code == 200
    nation = await _fetch_nation(pg_db, nation_id)
    assert nation.leader_name == "Boris Godunov"
    assert nation.leader_title == "Tsar of Old Realm"
    assert nation.history_url == "https://vk.com/@old-realm"

    # An empty link is invalid — never a reset back to NULL.
    patch = await client.patch(
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"history_url": ""},
    )
    assert patch.status_code == 422
    assert patch.json()["code"] == "HISTORY_URL_INVALID"
    nation = await _fetch_nation(pg_db, nation_id)
    assert nation.history_url == "https://vk.com/@old-realm"


async def test_admin_tick_and_state_reset_on_postgres(pg_live_client, pg_db):
    """Admin founds a nation, fires a real tick, then resets the world:
    nations (and their profiles) go, provinces free, turn rewinds to 0,
    and players survive."""
    client = pg_live_client
    token, _ = await _auth(client, vk_user_id=ADMIN_VK_ID)

    create = await client.post(
        "/api/v1/nations",
        headers=_headers(token),
        json={
            "name": "Tickland",
            "color_hex": "#0ACE55",
            "province_ids": [20],
            **VALID_PROFILE,
        },
    )
    assert create.status_code == 201
    nation_id = create.json()["id"]

    tick = await client.post("/api/v1/admin/tick/run", headers=_headers(token))
    assert tick.status_code == 200, tick.text
    body = tick.json()
    assert body["ok"] is True
    assert body["current_turn"] == 1
    assert body["tick_log"]["status"] == TickLogStatus.COMPLETED.value

    async with pg_db() as session:
        result = await session.execute(
            select(TickLog).where(TickLog.turn_number == 1)
        )
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED
        assert logs[0].finished_at is not None
        # The tick must not touch nation profile fields.
        nation = (
            await session.execute(
                select(Nation).where(Nation.id == nation_id)
            )
        ).scalar_one()
        assert nation.leader_name == VALID_PROFILE["leader_name"]
        assert nation.leader_title == VALID_PROFILE["leader_title"]
        assert nation.history_url == VALID_PROFILE["history_url"]

    reset = await client.post(
        "/api/v1/admin/state/reset",
        headers=_headers(token),
        json={"confirm": True},
    )
    assert reset.status_code == 200, reset.text

    async with pg_db() as session:
        nations = await session.execute(
            select(func.count()).select_from(Nation)
        )
        assert nations.scalar_one() == 0
        provinces = await session.execute(select(Province))
        all_provinces = provinces.scalars().all()
        assert len(all_provinces) == 100  # seeded rows survive
        assert all(p.nation_id is None for p in all_provinces)
        clock = (
            await session.execute(
                select(GameClock).where(GameClock.id == 1)
            )
        ).scalar_one()
        assert clock.current_turn == 0
        assert clock.last_tick_at is None
        logs = await session.execute(
            select(func.count()).select_from(TickLog)
        )
        assert logs.scalar_one() == 0
        # Players are kept across a world reset.
        players = await session.execute(select(Player.vk_user_id))
        assert players.scalars().all() == [ADMIN_VK_ID]


async def test_failed_tick_rolls_back_and_keeps_attempt_history(
    pg_live_client, pg_db
):
    """A PHASE_1 handler that dirties state then raises: the whole tick
    transaction rolls back (turn and nation unchanged), tick_log records
    FAILED with the error — and a clean retry lands COMPLETED under the
    same turn_number (attempt history, migration 0002)."""
    client = pg_live_client
    token, _ = await _auth(client, vk_user_id=ADMIN_VK_ID)

    create = await client.post(
        "/api/v1/nations",
        headers=_headers(token),
        json={
            "name": "Immutable Realm",
            "color_hex": "#AA55AA",
            "province_ids": [30],
            **VALID_PROFILE,
        },
    )
    assert create.status_code == 201
    nation_id = create.json()["id"]

    async def rename_then_fail(session, turn_number):
        await session.execute(
            update(Nation)
            .where(Nation.id == nation_id)
            .values(name="Corrupted By Tick")
        )
        raise RuntimeError("PG tick blew up on purpose")

    TickOrchestrator.register(
        TickPhase.PHASE_1_ENVIRONMENT, rename_then_fail
    )

    tick = await client.post("/api/v1/admin/tick/run", headers=_headers(token))
    assert tick.status_code == 200
    body = tick.json()
    assert body["ok"] is False
    assert body["current_turn"] == 0
    assert body["tick_log"]["status"] == TickLogStatus.FAILED.value

    async with pg_db() as session:
        nation = (
            await session.execute(
                select(Nation).where(Nation.id == nation_id)
            )
        ).scalar_one()
        # Rollback: the in-tick rename never committed.
        assert nation.name == "Immutable Realm"
        clock = (
            await session.execute(
                select(GameClock).where(GameClock.id == 1)
            )
        ).scalar_one()
        assert clock.current_turn == 0
        result = await session.execute(
            select(TickLog).order_by(TickLog.id)
        )
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.FAILED
        assert "PG tick blew up on purpose" in logs[0].error_message

    TickOrchestrator.clear_handlers()

    tick2 = await client.post("/api/v1/admin/tick/run", headers=_headers(token))
    assert tick2.status_code == 200
    body2 = tick2.json()
    assert body2["ok"] is True
    assert body2["current_turn"] == 1

    async with pg_db() as session:
        result = await session.execute(
            select(TickLog)
            .where(TickLog.turn_number == 1)
            .order_by(TickLog.id)
        )
        logs = result.scalars().all()
    assert [log.status for log in logs] == [
        TickLogStatus.FAILED,
        TickLogStatus.COMPLETED,
    ]


async def test_pg_foreign_keys_and_orphaned_actions(pg_live_client, pg_db):
    """PostgreSQL-only guarantees SQLite's default pragma cannot prove:
    nations.owner_player_id is a real FK, and deleting a nation leaves
    its scheduled actions orphaned (ON DELETE SET NULL, migration 0004)."""
    client = pg_live_client

    async with pg_db() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, created_at) "
                    "VALUES (:id, :owner, :name, :color, now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "owner": str(uuid.uuid4()),  # no such player
                    "name": "Ghost Nation",
                    "color": "#0B0B0B",
                },
            )
        await session.rollback()

    token, _ = await _auth(client, vk_user_id=940001)
    create = await client.post(
        "/api/v1/nations",
        headers=_headers(token),
        json={
            "name": "Actionland",
            "color_hex": "#C1C1C1",
            "province_ids": [40],
            **VALID_PROFILE,
        },
    )
    assert create.status_code == 201
    nation_id = create.json()["id"]
    action_id = str(uuid.uuid4())

    async with pg_db() as session:
        await session.execute(
            text(
                "INSERT INTO scheduled_actions "
                "(id, nation_id, module_slug, action_type, payload, "
                " turn_number, status, created_at) "
                "VALUES (:id, :nid, '00_core', 'probe', '{}'::json, "
                "        1, 'PENDING', now())"
            ),
            {"id": action_id, "nid": nation_id},
        )
        await session.commit()

    delete = await client.request(
        "DELETE",
        "/api/v1/nations/me",
        headers=_headers(token),
        json={"confirm": True},
    )
    assert delete.status_code == 204

    async with pg_db() as session:
        action = (
            await session.execute(
                select(ScheduledAction).where(ScheduledAction.id == action_id)
            )
        ).scalar_one()
    assert action.nation_id is None
    assert action.status == ScheduledActionStatus.PENDING
