"""
Permanent player numbers (0.11.0 unit 11).

The Registry number is stored, issued once and never reused: deleting
player 2 leaves 1 and 3 with their numbers, the route for 2 answers
the domain 404, and the next player gets 4 — not 2. Everything runs on
the real in-memory DB with the shared factories (Anti-Mock Guard).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modules._00_core.service import PlayerService
from modules._03_registry.admin_hooks import registry_player_info
from modules._03_registry.errors import RegistryPlayerNotFoundError
from modules._03_registry.models import (
    RegistryNumberCounter,
    RegistryPlayerNumber,
)
from modules._03_registry.service import build_table, ensure_player_numbers
from modules._03_registry.sources import load_player
from tests.fixtures.factories import PlayerFactory
from tests.modules._03_registry.conftest import bearer_headers, seed_player

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

PLAYERS_URL = "/api/v1/registry/players"


async def _issued(session, player_id: str) -> int | None:
    return (
        await session.execute(
            select(RegistryPlayerNumber.number).where(
                RegistryPlayerNumber.player_id == player_id
            )
        )
    ).scalar_one_or_none()


class TestEnsurePlayerNumbers:
    """Issuing order, idempotency and race safety."""

    async def test_issues_in_created_at_id_order_and_is_idempotent(
        self, test_db_session
    ):
        # Deliberately seed newest-first so insertion order ≠ order.
        p2 = await seed_player(test_db_session, 510101, created_at=T0 + timedelta(hours=1))
        p1 = await seed_player(test_db_session, 510102, created_at=T0)

        numbers = await ensure_player_numbers(test_db_session)

        assert numbers[p1.id] == 1
        assert numbers[p2.id] == 2

        # A second call changes nothing and writes nothing.
        again = await ensure_player_numbers(test_db_session)
        assert again == numbers

        counter = (
            await test_db_session.execute(select(RegistryNumberCounter))
        ).scalar_one()
        assert counter.last_number == 2

    async def test_counter_row_created_when_schema_has_none(
        self, test_db_session
    ):
        """Metadata-built schemas (no migration 0016) have no counter
        row — ensure seeds it from the highest issued number."""
        await seed_player(test_db_session, 510201, created_at=T0)
        numbers = await ensure_player_numbers(test_db_session)
        assert list(numbers.values()) == [1]

    async def test_concurrent_calls_never_duplicate(
        self, test_db_engine, session_factory
    ):
        """Two racing ensures produce distinct numbers — the re-read
        under the issuing branch plus the unique constraint hold."""
        async with session_factory() as seeder:
            p1 = PlayerFactory.build(vk_user_id=510301, nations=[])
            p2 = PlayerFactory.build(vk_user_id=510302, nations=[])
            seeder.add_all([p1, p2])
            await seeder.commit()

        async def _run():
            async with session_factory() as session:
                return await ensure_player_numbers(session)

        results = await asyncio.gather(_run(), _run())

        merged = results[0] | results[1]
        assert sorted(merged.values()) == [1, 2]

    async def test_issue_to_deleted_player_cannot_duplicate(self, test_db_session):
        """The unique constraint is the second line of defence — a
        manual duplicate insert must fail at the database."""
        player = await seed_player(test_db_session, 510401, created_at=T0)
        await ensure_player_numbers(test_db_session)
        other = await seed_player(test_db_session, 510402, created_at=T0)

        test_db_session.add(
            RegistryPlayerNumber(player_id=other.id, number=1)
        )
        with pytest.raises(IntegrityError):
            await test_db_session.flush()
        await test_db_session.rollback()


class TestNumbersSurviveDeletion:
    """Deleting a player never moves another player's number."""

    async def test_gap_after_delete_and_no_reuse(
        self, client, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 511001, created_at=T0)
        p2 = await seed_player(test_db_session, 511002, created_at=T0 + timedelta(hours=1))
        p3 = await seed_player(test_db_session, 511003, created_at=T0 + timedelta(hours=2))
        await ensure_player_numbers(test_db_session)

        await PlayerService.delete_player(test_db_session, p2.id)
        await test_db_session.commit()

        # Number row for p2 removed by the hook; 1 and 3 unchanged.
        assert await _issued(test_db_session, p2.id) is None
        assert await _issued(test_db_session, p1.id) == 1
        assert await _issued(test_db_session, p3.id) == 3

        # The table keeps (created_at, id) order with keys p1/p3.
        built = await build_table(test_db_session, "players")
        assert [row.key for row in built.rows] == ["p1", "p3"]

        # The route for the freed number answers the domain 404.
        resp = await client.get(f"{PLAYERS_URL}/2", headers=bearer_headers(p1.id))
        assert resp.status_code == 404
        assert resp.json()["code"] == "REGISTRY_PLAYER_NOT_FOUND"

        # A brand-new player gets 4 — the freed 2 is never reused.
        p4 = await seed_player(test_db_session, 511004, created_at=T0 + timedelta(hours=3))
        numbers = await ensure_player_numbers(test_db_session)
        assert numbers[p4.id] == 4

        # Deleting the newest player then adding another: same rule.
        await PlayerService.delete_player(test_db_session, p4.id)
        await test_db_session.commit()
        p5 = await seed_player(test_db_session, 511005, created_at=T0 + timedelta(hours=4))
        numbers = await ensure_player_numbers(test_db_session)
        assert numbers[p5.id] == 5
        counter = (
            await test_db_session.execute(select(RegistryNumberCounter))
        ).scalar_one()
        assert counter.last_number == 5

    async def test_load_player_number_with_no_player_is_not_found(
        self, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 511101, created_at=T0)
        await ensure_player_numbers(test_db_session)

        # A number never issued → not found.
        with pytest.raises(RegistryPlayerNotFoundError):
            await load_player(test_db_session, 99)

        # A stored number whose row was removed manually (no hook —
        # direct SQL delete) → also not found.
        await test_db_session.execute(
            RegistryPlayerNumber.__table__.delete().where(
                RegistryPlayerNumber.player_id == p1.id
            )
        )
        with pytest.raises(RegistryPlayerNotFoundError):
            await load_player(test_db_session, 1)


class TestStoredNumberInCells:
    """The stored number drives keys, cells and fallback names."""

    async def test_fallback_name_and_row_key_use_stored_number(
        self, test_db_session, registry_started
    ):
        player = await seed_player(test_db_session, 512001, created_at=T0)
        # Pre-issue a deliberately non-sequential number via the counter.
        test_db_session.add(RegistryNumberCounter(id=1, last_number=40))
        await test_db_session.flush()
        await ensure_player_numbers(test_db_session)

        built = await build_table(test_db_session, "players")
        assert built.rows[0].key == "p41"
        assert built.rows[0].cells["number"] == 41
        assert built.rows[0].cells["player"]["name"] == "Игрок №41"

        # The player route and the table row agree.
        row = await load_player(test_db_session, 41)
        assert row.key == "p41"
        assert row.cells["player"]["name"] == "Игрок №41"

    async def test_table_and_route_agree_after_gap(
        self, client, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 512101, created_at=T0)
        p2 = await seed_player(test_db_session, 512102, created_at=T0 + timedelta(hours=1))
        await ensure_player_numbers(test_db_session)
        await PlayerService.delete_player(test_db_session, p1.id)
        await test_db_session.commit()

        table = await client.get("/api/v1/registry/tables/players", headers=bearer_headers(p2.id))
        rows = table.json()["rows"]
        assert [r["key"] for r in rows] == ["p2"]

        resp = await client.get(f"{PLAYERS_URL}/2", headers=bearer_headers(p2.id))
        assert resp.status_code == 200
        assert resp.json()["number"] == 2


class TestAdminIntegration:
    """Player-info hook + delete hook behaviour."""

    async def test_player_info_returns_registry_number(
        self, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 513001, created_at=T0)
        p2 = await seed_player(test_db_session, 513002, created_at=T0 + timedelta(hours=1))
        await ensure_player_numbers(test_db_session)

        info = await registry_player_info(test_db_session, [p1.id, p2.id])
        assert info[p1.id]["registry_number"] == 1
        assert info[p2.id]["registry_number"] == 2
        # No VK profile rows → no display_name keys at all.
        assert "display_name" not in info[p1.id]

    async def test_admin_delete_removes_number_row(
        self, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 513101, created_at=T0)
        await ensure_player_numbers(test_db_session)
        assert await _issued(test_db_session, p1.id) == 1

        await PlayerService.delete_player(test_db_session, p1.id)
        await test_db_session.commit()

        assert await _issued(test_db_session, p1.id) is None
        # The counter keeps the freed number reserved.
        counter = (
            await test_db_session.execute(select(RegistryNumberCounter))
        ).scalar_one()
        assert counter.last_number == 1
