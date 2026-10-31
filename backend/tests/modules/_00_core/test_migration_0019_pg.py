"""
Migration 0019 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0019.py against the dedicated *_test
database: the two application tables with their partial unique
indexes and the nation_images reshape run on the real dialect, and
the downgrade restores the 0018 shape.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.fixtures.postgres import (
    _reset_public_schema,
    _sync_url,
    pg_url,  # noqa: F401
)

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[3]

APP = "nation_applications"
APPROV = "nation_application_provinces"
IMG = "nation_images"


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _schema(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            tables = set(insp.get_table_names())
            return {
                "tables": tables,
                "app_indexes": (
                    {i["name"]: i["unique"] for i in insp.get_indexes(APP)}
                    if APP in tables
                    else {}
                ),
                "approv_indexes": (
                    {i["name"]: i["unique"] for i in insp.get_indexes(APPROV)}
                    if APPROV in tables
                    else {}
                ),
                "app_checks": (
                    {c["name"] for c in insp.get_check_constraints(APP)}
                    if APP in tables
                    else set()
                ),
                "app_fks": (
                    {
                        fk["name"]: fk["options"].get("ondelete")
                        for fk in insp.get_foreign_keys(APP)
                    }
                    if APP in tables
                    else {}
                ),
                "img_columns": (
                    {c["name"]: c for c in insp.get_columns(IMG)}
                    if IMG in tables
                    else {}
                ),
                "img_uniques": (
                    {u["name"] for u in insp.get_unique_constraints(IMG)}
                    if IMG in tables
                    else set()
                ),
                "img_checks": (
                    {c["name"] for c in insp.get_check_constraints(IMG)}
                    if IMG in tables
                    else set()
                ),
            }
    finally:
        engine.dispose()


def test_0019_creates_application_tables_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0018", monkeypatch)
    before = _schema(wiped_pg)

    _alembic(wiped_pg, command.upgrade, "0019", monkeypatch)

    schema = _schema(wiped_pg)
    assert schema["tables"] == before["tables"] | {APP, APPROV}
    assert schema["app_indexes"] == {
        "uq_nation_applications_owner_live": True,
        "uq_nation_applications_pending_name": True,
        "uq_nation_applications_pending_short_name": True,
        "uq_nation_applications_pending_color_hex": True,
    }
    assert schema["approv_indexes"] == {
        "uq_nation_application_provinces_reserved": True
    }
    assert {
        "ck_nation_applications_status",
        "ck_nation_applications_draft_reason",
    } <= schema["app_checks"]
    assert schema["app_fks"]["fk_nation_applications_reviewer_player_id"] == (
        "SET NULL"
    )
    assert schema["app_fks"]["fk_nation_applications_accepted_nation_id"] == (
        "SET NULL"
    )
    assert schema["app_fks"][
        "fk_nation_applications_capital_province_id"
    ] == ("SET NULL")
    assert schema["img_columns"]["nation_id"]["nullable"] is True
    assert "application_id" in schema["img_columns"]
    assert "uq_nation_images_application_kind" in schema["img_uniques"]
    assert "ck_nation_images_one_owner" in schema["img_checks"]


def test_0019_downgrade_restores_0018_shape_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0019", monkeypatch)
    assert APP in _schema(wiped_pg)["tables"]

    _alembic(wiped_pg, command.downgrade, "0018", monkeypatch)

    schema = _schema(wiped_pg)
    assert APP not in schema["tables"]
    assert APPROV not in schema["tables"]
    assert "application_id" not in schema["img_columns"]
    assert schema["img_columns"]["nation_id"]["nullable"] is False
    assert "uq_nation_images_application_kind" not in schema["img_uniques"]
    assert "ck_nation_images_one_owner" not in schema["img_checks"]

    _alembic(wiped_pg, command.upgrade, "0019", monkeypatch)
    assert APP in _schema(wiped_pg)["tables"]
