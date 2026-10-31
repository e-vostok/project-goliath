"""
Migration 0019 tests on a real SQLite file database (Spec
applications §1 — the «анкета» tables and the nation_images reshape
of 0.13.0 unit 4).

Upgrading 0018 -> 0019 creates ``nation_applications`` and
``nation_application_provinces`` with their partial unique indexes,
and reshapes ``nation_images`` (nullable nation_id, application_id
FK, the one-owner CHECK, the second unique key). Downgrade restores
the 0018 shape exactly.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

APP = "nation_applications"
APPROV = "nation_application_provinces"
IMG = "nation_images"

APP_COLUMNS = {
    "id",
    "owner_player_id",
    "status",
    "name",
    "short_name",
    "color_hex",
    "motto",
    "description",
    "leader_name",
    "leader_title",
    "gender",
    "succession_type",
    "leader_bio",
    "history_url",
    "capital_province_id",
    "capital_name",
    "draft_reason",
    "return_comment",
    "submissions",
    "submitted_at",
    "review_deadline_at",
    "reviewer_player_id",
    "reviewer_assigned_at",
    "decided_at",
    "decided_by_player_id",
    "auto_accepted",
    "accepted_nation_id",
    "created_at",
    "updated_at",
}
APPROV_COLUMNS = {"application_id", "province_id", "position", "is_reserved"}


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _schema(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            tables = set(insp.get_table_names())
            return {
                "tables": tables,
                "app_columns": (
                    {c["name"] for c in insp.get_columns(APP)}
                    if APP in tables
                    else set()
                ),
                "approv_columns": (
                    {c["name"] for c in insp.get_columns(APPROV)}
                    if APPROV in tables
                    else set()
                ),
                "app_indexes": (
                    {i["name"] for i in insp.get_indexes(APP)} if APP in tables else set()
                ),
                "approv_indexes": (
                    {i["name"] for i in insp.get_indexes(APPROV)}
                    if APPROV in tables
                    else set()
                ),
                "img_columns": {
                    c["name"]: c for c in insp.get_columns(IMG)
                },
                "img_uniques": {
                    u["name"]: u["column_names"]
                    for u in insp.get_unique_constraints(IMG)
                },
                "img_checks": {
                    c["name"]: c["sqltext"] for c in insp.get_check_constraints(IMG)
                },
                "img_fks": {
                    fk["name"]: fk["referred_table"]
                    for fk in insp.get_foreign_keys(IMG)
                },
            }
    finally:
        engine.dispose()


def test_0019_creates_application_tables(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0018", monkeypatch)
    before = _schema(url)
    assert APP not in before["tables"]
    assert APPROV not in before["tables"]

    _alembic(url, command.upgrade, "0019", monkeypatch)

    schema = _schema(url)
    assert schema["tables"] == before["tables"] | {APP, APPROV}
    assert schema["app_columns"] == APP_COLUMNS
    assert schema["approv_columns"] == APPROV_COLUMNS
    assert schema["app_indexes"] == {
        "uq_nation_applications_owner_live",
        "uq_nation_applications_pending_name",
        "uq_nation_applications_pending_short_name",
        "uq_nation_applications_pending_color_hex",
    }
    assert schema["approv_indexes"] == {
        "uq_nation_application_provinces_reserved"
    }
    # nation_images: application_id arrived, nation_id went nullable.
    assert "application_id" in schema["img_columns"]
    assert schema["img_columns"]["nation_id"]["nullable"] is True
    assert schema["img_uniques"]["uq_nation_images_application_kind"] == [
        "application_id",
        "kind",
    ]
    assert "ck_nation_images_one_owner" in schema["img_checks"]
    assert schema["img_fks"]["fk_nation_images_application_id"] == (
        "nation_applications"
    )


def test_0019_downgrade_restores_0018_shape(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0019", monkeypatch)
    assert APP in _schema(url)["tables"]

    _alembic(url, command.downgrade, "0018", monkeypatch)

    schema = _schema(url)
    assert APP not in schema["tables"]
    assert APPROV not in schema["tables"]
    assert "application_id" not in schema["img_columns"]
    assert schema["img_columns"]["nation_id"]["nullable"] is False
    assert "uq_nation_images_application_kind" not in schema["img_uniques"]
    assert "ck_nation_images_one_owner" not in schema["img_checks"]

    # A second upgrade recreates everything cleanly.
    _alembic(url, command.upgrade, "0019", monkeypatch)
    assert APP in _schema(url)["tables"]
