"""
Tests for ProvinceService.ensure_nodes (00_core, module 01_map Issue 1).

ensure_nodes is the interim map-node synchronisation primitive: it
inserts manifest nodes that are missing, reports kind mismatches on
existing rows without touching them, and reports extra DB rows without
deleting them (the INV-M5 decision belongs to the caller). All tests run
against a real in-memory SQLite database — no mocks.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import func, select

from modules._00_core.models import Province
from modules._00_core.service import (
    EnsureNodesResult,
    NodeSpec,
    ProvinceService,
)
from tests.fixtures.provinces import make_land_province, make_sea_province


async def _province_count(session) -> int:
    result = await session.execute(select(func.count()).select_from(Province))
    return result.scalar_one()


async def _kind_of(session, province_id: int) -> str:
    result = await session.execute(
        select(Province.kind).where(Province.id == province_id)
    )
    return result.scalar_one()


class TestEnsureNodesInsert:
    async def test_inserts_into_empty_table(self, test_db_session):
        nodes = [
            NodeSpec(id=1001, kind="LAND"),
            NodeSpec(id=2001, kind="SEA"),
        ]

        result = await ProvinceService.ensure_nodes(test_db_session, nodes)

        assert result == EnsureNodesResult(
            added=[1001, 2001], kind_mismatch=[], extra_in_db=[]
        )
        rows = (
            await test_db_session.execute(
                select(Province.id, Province.kind, Province.nation_id)
            )
        ).all()
        assert sorted(rows) == [
            (1001, "LAND", None),
            (2001, "SEA", None),
        ]

    async def test_second_call_is_idempotent(self, test_db_session):
        nodes = [NodeSpec(id=1001, kind="LAND")]

        first = await ProvinceService.ensure_nodes(test_db_session, nodes)
        second = await ProvinceService.ensure_nodes(test_db_session, nodes)

        assert first.added == [1001]
        assert second.added == []
        assert second.kind_mismatch == []
        assert second.extra_in_db == []
        assert await _province_count(test_db_session) == 1

    async def test_empty_input_reports_existing_rows_as_extra(
        self, test_db_session
    ):
        await make_land_province(test_db_session, id=1001)

        result = await ProvinceService.ensure_nodes(test_db_session, [])

        assert result.added == []
        assert result.kind_mismatch == []
        assert result.extra_in_db == [1001]
        assert await _province_count(test_db_session) == 1


class TestEnsureNodesMismatchAndExtra:
    async def test_kind_mismatch_is_reported_not_changed(
        self, test_db_session
    ):
        await make_land_province(test_db_session, id=1001)

        result = await ProvinceService.ensure_nodes(
            test_db_session, [NodeSpec(id=1001, kind="SEA")]
        )

        assert result.added == []
        assert result.kind_mismatch == [1001]
        assert result.extra_in_db == []
        # The existing row keeps its original kind.
        assert await _kind_of(test_db_session, 1001) == "LAND"

    async def test_extra_db_row_is_reported_not_deleted(
        self, test_db_session
    ):
        await make_land_province(test_db_session, id=1001)
        await make_sea_province(test_db_session, id=2001)

        result = await ProvinceService.ensure_nodes(
            test_db_session, [NodeSpec(id=1001, kind="LAND")]
        )

        assert result.added == []
        assert result.kind_mismatch == []
        assert result.extra_in_db == [2001]
        assert await _province_count(test_db_session) == 2

    async def test_mixed_result(self, test_db_session):
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await make_sea_province(test_db_session, id=2009)

        result = await ProvinceService.ensure_nodes(
            test_db_session,
            [
                NodeSpec(id=1001, kind="LAND"),
                NodeSpec(id=1002, kind="SEA"),  # mismatch
                NodeSpec(id=1003, kind="LAND"),  # new
            ],
        )

        assert result.added == [1003]
        assert result.kind_mismatch == [1002]
        assert result.extra_in_db == [2009]


class TestEnsureNodesValidation:
    async def test_duplicate_ids_raise_and_write_nothing(
        self, test_db_session
    ):
        nodes = [
            NodeSpec(id=1001, kind="LAND"),
            NodeSpec(id=1001, kind="SEA"),
        ]

        with pytest.raises(ValueError, match="Duplicate"):
            await ProvinceService.ensure_nodes(test_db_session, nodes)

        assert await _province_count(test_db_session) == 0

    async def test_invalid_kind_raises_and_writes_nothing(
        self, test_db_session
    ):
        nodes = [
            NodeSpec(id=1001, kind="LAND"),
            NodeSpec(id=1002, kind="XXX"),  # type: ignore[arg-type]
        ]

        with pytest.raises(ValueError, match="kind"):
            await ProvinceService.ensure_nodes(test_db_session, nodes)

        assert await _province_count(test_db_session) == 0

    async def test_province_with_nation_is_never_touched(
        self, test_db_session
    ):
        """An owned province with a matching kind is 'existing', not
        'added' — ensure_nodes must not strip ownership."""
        import uuid as _uuid
        from datetime import datetime, timezone

        from modules._00_core.models import Nation, Player
        from tests.fixtures.profile import VALID_PROFILE

        player = Player(
            id=str(_uuid.uuid4()),
            vk_user_id=777001,
            created_at=datetime.now(timezone.utc),
        )
        nation = Nation(
            id=str(_uuid.uuid4()),
            owner_player_id=player.id,
            name="Owning Nation",
            color_hex="#101010",
            created_at=datetime.now(timezone.utc),
            **VALID_PROFILE,
        )
        test_db_session.add_all([player, nation])
        await test_db_session.flush()
        province = await make_land_province(test_db_session, id=1001)
        province.nation_id = nation.id
        await test_db_session.flush()

        result = await ProvinceService.ensure_nodes(
            test_db_session, [NodeSpec(id=1001, kind="LAND")]
        )

        assert result.added == []
        await test_db_session.refresh(province)
        assert province.nation_id == nation.id


class TestEnsureNodesPerformance:
    async def test_bulk_insert_of_full_map_is_fast(self, test_db_session):
        """1123 nodes — the real manifest size — in a couple of
        statements, not per-row round trips (generous time bound)."""
        nodes = [
            NodeSpec(id=3000 + i, kind="LAND" if i % 10 else "SEA")
            for i in range(1123)
        ]

        start = time.monotonic()
        result = await ProvinceService.ensure_nodes(test_db_session, nodes)
        elapsed = time.monotonic() - start

        assert len(result.added) == 1123
        assert await _province_count(test_db_session) == 1123
        assert elapsed < 10.0  # a per-row loop would still pass; the
        # real assertion is the single bulk insert below.

    async def test_bulk_insert_uses_few_statements(
        self, test_db_session, test_db_engine
    ):
        """Inserting 1123 nodes must not execute one statement per row."""
        from sqlalchemy import event

        statements = []

        def count_stmt(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(test_db_engine.sync_engine, "before_cursor_execute", count_stmt)
        try:
            nodes = [
                NodeSpec(id=5000 + i, kind="LAND") for i in range(1123)
            ]
            await ProvinceService.ensure_nodes(test_db_session, nodes)
        finally:
            event.remove(
                test_db_engine.sync_engine, "before_cursor_execute", count_stmt
            )

        # 1 SELECT + 1 bulk INSERT — nowhere near 1123 round trips.
        assert len(statements) <= 5
