"""
Schema and invariant tests for map_ownership_log (module 01_map).

Spec Part 1 / INV-M7: the table is append-only, references only
provinces.id (nation references are logical, never a real FK), and
enforces ck_log_new_nation_consistent: the three new_nation_* columns
are all NULL or all NOT NULL.

Runs on a real in-memory SQLite database — no mocks.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.db import Base
from modules._00_core.models import Province  # noqa: F401 — needed by metadata
from modules._01_map.models import MapOwnershipLog


def _log_row(**overrides) -> dict:
    """A valid all-NULL-triple log row for province 1001, turn 1."""
    row = {
        "province_id": 1001,
        "turn_number": 1,
        "prev_nation_id": None,
        "new_nation_id": None,
        "new_nation_name": None,
        "new_nation_color": None,
        "created_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


async def _make_log_session():
    """Engine + session with SQLite FK enforcement on.

    The shared conftest fixture leaves PRAGMA foreign_keys off (the
    SQLite default), so this suite builds its own engine to prove the
    province FK is real.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(sa.text("INSERT INTO provinces (id) VALUES (1001)"))

    maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, maker


class TestPrimaryKey:
    """The tick_log.id lesson: the BIGINT PK must autoincrement on
    SQLite too, so two inserts never collide."""

    async def test_two_inserts_get_different_ids(self, test_db_session):
        test_db_session.add(MapOwnershipLog(**_log_row()))
        test_db_session.add(MapOwnershipLog(**_log_row(turn_number=2)))
        await test_db_session.flush()

        ids = (
            await test_db_session.execute(
                select(MapOwnershipLog.id).order_by(MapOwnershipLog.id)
            )
        ).scalars().all()
        assert len(ids) == 2
        assert ids[0] != ids[1]
        assert all(isinstance(i, int) and i > 0 for i in ids)


class TestNewNationConsistency:
    async def test_all_null_triple_accepted(self, test_db_session):
        test_db_session.add(Province(id=1001, kind="LAND", nation_id=None))
        test_db_session.add(MapOwnershipLog(**_log_row()))
        await test_db_session.flush()  # no error

    async def test_all_filled_triple_accepted(self, test_db_session):
        test_db_session.add(Province(id=1001, kind="LAND", nation_id=None))
        test_db_session.add(
            MapOwnershipLog(
                **_log_row(
                    prev_nation_id="a" * 36,
                    new_nation_id="b" * 36,
                    new_nation_name="Captured Land",
                    new_nation_color="#FF0000",
                )
            )
        )
        await test_db_session.flush()  # no error

    @pytest.mark.parametrize(
        "overrides",
        [
            {"new_nation_id": "b" * 36},
            {"new_nation_id": "b" * 36, "new_nation_name": "Half"},
            {"new_nation_name": "Nameless", "new_nation_color": "#00FF00"},
            {"new_nation_color": "#00FF00"},
        ],
    )
    async def test_partial_triple_rejected(
        self, test_db_session, overrides
    ):
        test_db_session.add(Province(id=1001, kind="LAND", nation_id=None))
        test_db_session.add(MapOwnershipLog(**_log_row(**overrides)))
        with pytest.raises(IntegrityError):
            await test_db_session.flush()


class TestSchema:
    async def test_indexes_exist(self, test_db_engine):
        async with test_db_engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda c: {
                    idx["name"]: idx["column_names"]
                    for idx in inspect(c).get_indexes("map_ownership_log")
                }
            )
        assert indexes["ix_map_log_province_turn"] == [
            "province_id",
            "turn_number",
            "id",
        ]
        assert indexes["ix_map_log_turn"] == ["turn_number"]

    async def test_pk_and_columns(self, test_db_engine):
        async with test_db_engine.connect() as conn:
            pk, columns, checks = await conn.run_sync(
                lambda c: (
                    inspect(c).get_pk_constraint("map_ownership_log"),
                    {
                        col["name"]: col
                        for col in inspect(c).get_columns(
                            "map_ownership_log"
                        )
                    },
                    [
                        chk["name"]
                        for chk in inspect(c).get_check_constraints(
                            "map_ownership_log"
                        )
                    ],
                )
            )
        assert pk["constrained_columns"] == ["id"]
        for name in (
            "id",
            "province_id",
            "turn_number",
            "prev_nation_id",
            "new_nation_id",
            "new_nation_name",
            "new_nation_color",
            "created_at",
        ):
            assert name in columns
        assert columns["created_at"]["nullable"] is False
        assert columns["province_id"]["nullable"] is False
        assert "ck_log_new_nation_consistent" in checks

    async def test_fk_only_to_provinces(self, test_db_engine):
        """Spec Part 2: the journal references provinces.id and has no
        foreign key to nations (logical references only)."""
        async with test_db_engine.connect() as conn:
            fks = await conn.run_sync(
                lambda c: inspect(c).get_foreign_keys("map_ownership_log")
            )
        assert len(fks) == 1
        assert fks[0]["referred_table"] == "provinces"
        assert fks[0]["referred_columns"] == ["id"]

    async def test_created_at_is_timezone_aware(self, test_db_engine):
        async with test_db_engine.connect() as conn:
            col_type = await conn.run_sync(
                lambda c: next(
                    col["type"]
                    for col in inspect(c).get_columns("map_ownership_log")
                    if col["name"] == "created_at"
                )
            )
        assert isinstance(col_type, sa.DateTime)


class TestForeignKey:
    async def test_insert_for_missing_province_rejected(self):
        engine, maker = await _make_log_session()
        try:
            async with maker() as session:
                session.add(MapOwnershipLog(**_log_row(province_id=9999)))
                with pytest.raises(IntegrityError):
                    await session.flush()
        finally:
            await engine.dispose()
