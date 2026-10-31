"""
Migration 0018 tests on a real SQLite file database (Spec 00_core
Part 1 — the ``nation_images`` table of 0.12.0 unit 5b).

Upgrading 0017 -> 0018 creates ``nation_images`` with its columns,
``UNIQUE (nation_id, kind)``, ``CHECK (kind IN ('flag','portrait'))``,
the two foreign keys and the non-unique ``ix_nation_images_sha256``
index; no other table moves. Downgrade drops the table.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

TABLE = "nation_images"

EXPECTED_COLUMNS = {
    "id",
    "nation_id",
    "kind",
    "sha256",
    "full_bytes",
    "thumb_bytes",
    "byte_size",
    "uploaded_by_player_id",
    "uploaded_at",
}


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _upgrade(url: str, target: str, monkeypatch) -> None:
    _alembic(url, command.upgrade, target, monkeypatch)


def _schema(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {
                "tables": set(insp.get_table_names()),
                "columns": (
                    {c["name"] for c in insp.get_columns(TABLE)}
                    if TABLE in insp.get_table_names()
                    else set()
                ),
                "uniques": (
                    {
                        u["name"]: u["column_names"]
                        for u in insp.get_unique_constraints(TABLE)
                    }
                    if TABLE in insp.get_table_names()
                    else {}
                ),
                "checks": (
                    insp.get_check_constraints(TABLE)
                    if TABLE in insp.get_table_names()
                    else []
                ),
                "fks": (
                    insp.get_foreign_keys(TABLE)
                    if TABLE in insp.get_table_names()
                    else []
                ),
                "indexes": (
                    {i["name"] for i in insp.get_indexes(TABLE)}
                    if TABLE in insp.get_table_names()
                    else set()
                ),
            }
    finally:
        engine.dispose()


def test_0018_creates_nation_images(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0017", monkeypatch)
    before = _schema(url)
    assert TABLE not in before["tables"]

    _upgrade(url, "0018", monkeypatch)

    schema = _schema(url)
    assert TABLE in schema["tables"]
    assert schema["columns"] == EXPECTED_COLUMNS

    assert schema["uniques"]["uq_nation_images_nation_kind"] == [
        "nation_id",
        "kind",
    ]
    assert any(
        "flag" in (c["sqltext"] or "") and "portrait" in (c["sqltext"] or "")
        for c in schema["checks"]
    )
    fks = {
        fk["name"]: (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in schema["fks"]
    }
    assert fks["fk_nation_images_nation_id"] == ("nations", "CASCADE")
    assert fks["fk_nation_images_uploaded_by_player_id"] == (
        "players",
        "SET NULL",
    )
    assert "ix_nation_images_sha256" in schema["indexes"]
    # No other table was touched by the additive migration.
    assert schema["tables"] == before["tables"] | {TABLE}


def test_0018_downgrade_drops_nation_images(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0018", monkeypatch)
    assert TABLE in _schema(url)["tables"]

    _alembic(url, command.downgrade, "0017", monkeypatch)
    assert TABLE not in _schema(url)["tables"]

    # A second upgrade recreates the table cleanly.
    _upgrade(url, "0018", monkeypatch)
    assert TABLE in _schema(url)["tables"]
