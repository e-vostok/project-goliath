"""
Tests for the interim sync command `modules._01_map.sync_nodes`.

The CLI is a temporary bridge (removed in Issue 3): it reads only id and
kind of each node from a manifest.json and writes them through
ProvinceService.ensure_nodes in one transaction, printing
added / kind_mismatch / extra_in_db counts.

Tested on real databases — an in-memory session for the service-level
function and a real SQLite file for the CLI entry point. The manifest is
a small hand-made file in tmp_path, not the real 1.9 MB one.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from core.db import Base
from modules._00_core.service import NodeSpec  # noqa: F401
from modules._01_map.sync_nodes import load_node_specs, main, sync_nodes
from tests.fixtures.provinces import make_land_province, make_sea_province


def _write_manifest(path, nodes: list[dict]) -> str:
    manifest = path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "nodes": nodes, "edges": []}),
        encoding="utf-8",
    )
    return str(manifest)


MANIFEST_NODES = [
    {"id": 1001, "kind": "LAND", "name": "A"},
    {"id": 1002, "kind": "LAND", "name": "B"},
    {"id": 2001, "kind": "SEA", "name": "Sea", "anchor": [0, 0]},
]


def test_load_node_specs_reads_only_id_and_kind(tmp_path):
    path = _write_manifest(tmp_path, MANIFEST_NODES)

    specs = load_node_specs(path)

    assert [(n.id, n.kind) for n in specs] == [
        (1001, "LAND"),
        (1002, "LAND"),
        (2001, "SEA"),
    ]


async def test_sync_nodes_inserts_into_empty_db(test_db_session, tmp_path):
    path = _write_manifest(tmp_path, MANIFEST_NODES)

    result = await sync_nodes(test_db_session, path)

    assert result.added == [1001, 1002, 2001]
    assert result.kind_mismatch == []
    assert result.extra_in_db == []


async def test_sync_nodes_reports_mismatch_and_extra(
    test_db_session, tmp_path
):
    await make_land_province(test_db_session, id=1002)  # manifest says SEA
    await make_sea_province(test_db_session, id=2009)  # not in manifest

    nodes = [
        {"id": 1001, "kind": "LAND"},
        {"id": 1002, "kind": "SEA"},
    ]
    path = _write_manifest(tmp_path, nodes)

    result = await sync_nodes(test_db_session, path)

    assert result.added == [1001]
    assert result.kind_mismatch == [1002]
    assert result.extra_in_db == [2009]


async def test_sync_nodes_is_idempotent(test_db_session, tmp_path):
    path = _write_manifest(tmp_path, MANIFEST_NODES)

    first = await sync_nodes(test_db_session, path)
    second = await sync_nodes(test_db_session, path)

    assert len(first.added) == 3
    assert second.added == []
    assert second.kind_mismatch == []
    assert second.extra_in_db == []


def test_main_end_to_end_on_real_sqlite_file(tmp_path, monkeypatch, capsys):
    """`python -m modules._01_map.sync_nodes` against a real file DB."""
    db_file = tmp_path / "dev.db"
    sync_url = f"sqlite:///{db_file.as_posix()}"

    # Create the schema the way `alembic upgrade head` would have.
    engine = sa.create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    path = _write_manifest(tmp_path, MANIFEST_NODES)
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}"
    )

    assert main(["--manifest", path]) == 0
    out = capsys.readouterr().out
    assert "added=3" in out
    assert "kind_mismatch=0" in out
    assert "extra_in_db=0" in out

    # Idempotent: a second run adds nothing.
    assert main(["--manifest", path]) == 0
    out = capsys.readouterr().out
    assert "added=0" in out

    # The rows are committed — visible from a fresh connection.
    engine = sa.create_engine(sync_url)
    with engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM provinces")
        ).scalar_one()
    engine.dispose()
    assert count == 3
