"""
Migration 0006 tests on real SQLite file databases (module 01_map).

Covers Spec Part 1 / Appendix B:
- upgrade from 0005 removes the placeholder provinces 1..100 and adds
  ``kind`` plus ``ck_provinces_kind`` / ``ck_provinces_sea_unowned``;
- the guard aborts with the Russian world-reset message when a nation
  owns a placeholder, or when another table references provinces.id —
  and in both cases the schema and rows stay untouched;
- ``map_ownership_log`` is created with its checks and indexes;
- downgrade restores the schema and the 100 placeholder rows, and a
  subsequent upgrade lands cleanly (round trip).

Every test drives ``alembic upgrade/downgrade`` against a real file —
no mocks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[3]

GUARD_MESSAGE = (
    "Сначала выполните сброс мира: провинции 1..100 "
    "закреплены за государствами"
)


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _cfg() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


def _upgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_cfg(), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(_cfg(), target)


def _columns(url: str, table: str) -> dict[str, dict]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                col["name"]: col
                for col in sa.inspect(conn).get_columns(table)
            }
    finally:
        engine.dispose()


def _table_names(url: str) -> list[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()


def _province_rows(url: str) -> list[dict]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(sa.text("SELECT * FROM provinces"))
                .mappings()
                .all()
            )
    finally:
        engine.dispose()


def _nation_owning(url: str, province_id: int) -> None:
    """Insert player + nation rows and assign them a province."""
    player_id = str(uuid.uuid4())
    nation_id = str(uuid.uuid4())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id) "
                    "VALUES (:id, 42424201)"
                ),
                {"id": player_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, created_at) "
                    "VALUES (:id, :owner, 'Guard Nation', '#123456', :ts)"
                ),
                {
                    "id": nation_id,
                    "owner": player_id,
                    "ts": datetime.now(timezone.utc),
                },
            )
            conn.execute(
                sa.text(
                    "UPDATE provinces SET nation_id = :nid WHERE id = :pid"
                ),
                {"nid": nation_id, "pid": province_id},
            )
    finally:
        engine.dispose()


class TestUpgradeToHead:
    def test_kind_column_and_constraints(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        columns = _columns(url, "provinces")
        assert "kind" in columns
        assert columns["kind"]["nullable"] is False

        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                checks = {
                    chk["name"]
                    for chk in sa.inspect(conn).get_check_constraints(
                        "provinces"
                    )
                }
        finally:
            engine.dispose()
        assert "ck_provinces_kind" in checks
        assert "ck_provinces_sea_unowned" in checks

    def test_placeholder_rows_removed(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        assert _province_rows(url) == []

    def test_ownership_log_created(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        assert "map_ownership_log" in _table_names(url)

        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                insp = sa.inspect(conn)
                indexes = {
                    idx["name"] for idx in insp.get_indexes("map_ownership_log")
                }
                checks = {
                    chk["name"]
                    for chk in insp.get_check_constraints("map_ownership_log")
                }
                fks = insp.get_foreign_keys("map_ownership_log")
                pk = insp.get_pk_constraint("map_ownership_log")
        finally:
            engine.dispose()

        assert {"ix_map_log_province_turn", "ix_map_log_turn"} <= indexes
        assert "ck_log_new_nation_consistent" in checks
        assert len(fks) == 1
        assert fks[0]["referred_table"] == "provinces"
        assert pk["constrained_columns"] == ["id"]

    def test_log_id_autoincrements_on_sqlite(self, tmp_path, monkeypatch):
        """The tick_log.id lesson: two inserts must get distinct ids."""
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("INSERT INTO provinces (id, kind) VALUES (1001, 'LAND')")
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, created_at) "
                        "VALUES (1001, 1, :ts)"
                    ),
                    {"ts": datetime.now(timezone.utc)},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, created_at) "
                        "VALUES (1001, 2, :ts)"
                    ),
                    {"ts": datetime.now(timezone.utc)},
                )
                ids = [
                    row[0]
                    for row in conn.execute(
                        sa.text("SELECT id FROM map_ownership_log ORDER BY id")
                    )
                ]
        finally:
            engine.dispose()
        assert len(ids) == 2
        assert ids[0] != ids[1]


class TestProvinceInvariants:
    """ck_provinces_kind / ck_provinces_sea_unowned on the migrated DB."""

    @pytest.fixture
    def migrated(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        return url

    def test_sea_with_owner_rejected(self, migrated):
        _nation_owning(migrated, 0)  # creates nation; no province touched
        # province 0 does not exist — update hits nothing; now insert a
        # SEA row owned by that nation directly:
        nation_id = self._first_nation_id(migrated)
        engine = sa.create_engine(migrated)
        try:
            with pytest.raises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO provinces (id, kind, nation_id) "
                            "VALUES (2001, 'SEA', :nid)"
                        ),
                        {"nid": nation_id},
                    )
        finally:
            engine.dispose()

    def test_sea_without_owner_accepted(self, migrated):
        engine = sa.create_engine(migrated)
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO provinces (id, kind, nation_id) "
                        "VALUES (2001, 'SEA', NULL)"
                    )
                )
        finally:
            engine.dispose()

    def test_land_with_owner_accepted(self, migrated):
        _nation_owning(migrated, 0)
        nation_id = self._first_nation_id(migrated)
        engine = sa.create_engine(migrated)
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO provinces (id, kind, nation_id) "
                        "VALUES (1001, 'LAND', :nid)"
                    ),
                    {"nid": nation_id},
                )
        finally:
            engine.dispose()

    def test_invalid_kind_rejected(self, migrated):
        engine = sa.create_engine(migrated)
        try:
            with pytest.raises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO provinces (id, kind, nation_id) "
                            "VALUES (1001, 'XXX', NULL)"
                        )
                    )
        finally:
            engine.dispose()

    @staticmethod
    def _first_nation_id(url: str) -> str:
        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                return conn.execute(
                    sa.text("SELECT id FROM nations LIMIT 1")
                ).scalar_one()
        finally:
            engine.dispose()


class TestGuards:
    def test_owned_placeholder_aborts_with_russian_message(
        self, tmp_path, monkeypatch
    ):
        url = _db_url(tmp_path)
        _upgrade(url, "0005", monkeypatch)
        _nation_owning(url, 5)

        with pytest.raises(RuntimeError, match="сброс мира"):
            _upgrade(url, "head", monkeypatch)

        # The database is unchanged: no kind column, no log table, and
        # all 100 placeholder rows survived.
        columns = _columns(url, "provinces")
        assert "kind" not in columns
        assert "map_ownership_log" not in _table_names(url)
        assert len(_province_rows(url)) == 100

    def test_external_fk_to_provinces_aborts(self, tmp_path, monkeypatch):
        """If another table references provinces.id, the delete is unsafe
        and the migration must stop instead of guessing."""
        url = _db_url(tmp_path)
        _upgrade(url, "0005", monkeypatch)

        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "CREATE TABLE dangling_ref ("
                        "id INTEGER PRIMARY KEY, "
                        "province_id INTEGER REFERENCES provinces(id))"
                    )
                )
        finally:
            engine.dispose()

        with pytest.raises(RuntimeError, match="Refusing to delete"):
            _upgrade(url, "head", monkeypatch)

        assert "kind" not in _columns(url, "provinces")
        assert len(_province_rows(url)) == 100


class TestDowngradeRoundTrip:
    def test_downgrade_restores_schema_and_placeholders(
        self, tmp_path, monkeypatch
    ):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        _downgrade(url, "0005", monkeypatch)

        assert "kind" not in _columns(url, "provinces")
        assert "map_ownership_log" not in _table_names(url)
        rows = _province_rows(url)
        assert len(rows) == 100
        assert {row["id"] for row in rows} == set(range(1, 101))
        assert all(row["nation_id"] is None for row in rows)

    def test_upgrade_after_downgrade_works(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        _downgrade(url, "0005", monkeypatch)
        _upgrade(url, "head", monkeypatch)

        assert "kind" in _columns(url, "provinces")
        assert "map_ownership_log" in _table_names(url)
        assert _province_rows(url) == []
