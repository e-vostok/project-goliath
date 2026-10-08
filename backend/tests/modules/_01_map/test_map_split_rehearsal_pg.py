"""
map2_2 PostgreSQL rehearsal: a production-like database synced to the
pre-split manifest gains exactly one provinces row at startup.

Ids are append-only and never reused, so the old 1065-node database is
exactly the current manifest minus the newly appended (max) id. The
test seeds that set into the throwaway *_test database, points
DATABASE_URL at it, runs the real ``startup_map()`` and asserts the
log line reports ``1 added`` / ``0 retired removed``, the row count is
1066, and the appended id is a LAND row.

Requires DATABASE_URL_TEST; skips like the rest of the postgres suite.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import sqlalchemy as sa

import core.db as core_db
from core.db import get_session_context, init_engine
from modules._00_core.models import Province
from modules._01_map.config_schema import MapConfig
from modules._01_map.loader import load_map_data
from modules._01_map.startup import startup_map
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — resolved through the fixture chain
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,
)

pytestmark = pytest.mark.postgres

REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_MAP_DIR = REPO_ROOT / "data" / "map"


class _Capture(logging.Handler):
    """Collects emitted LogRecords — fileConfig inside alembic's env.py
    replaces root handlers, so pytest's caplog cannot be trusted here."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.mark.asyncio
async def test_map2_2_old_manifest_db_gains_one_row(
    pg_url, pg_clean, monkeypatch, extension_snapshot
):
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    map_data = load_map_data(REAL_MAP_DIR, config)
    new_id = max(n.id for n in map_data.nodes.values())
    kinds = {n.id: n.kind for n in map_data.nodes.values()}

    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("MAP_DATA_DIR", str(REAL_MAP_DIR))
    init_engine(pg_url)
    try:
        async with get_session_context() as session:
            await session.execute(
                sa.insert(Province),
                [
                    {"id": i, "kind": kinds[i]}
                    for i in sorted(kinds)
                    if i != new_id
                ],
            )
            await session.commit()

        capture = _Capture()
        startup_logger = logging.getLogger("modules._01_map.startup")
        old_level = startup_logger.level
        startup_logger.addHandler(capture)
        startup_logger.setLevel(logging.INFO)
        try:
            service = await startup_map()
        finally:
            startup_logger.removeHandler(capture)
            startup_logger.setLevel(old_level)

        assert len(service.all_nodes()) == 1066
        async with get_session_context() as session:
            count = await session.execute(
                sa.select(sa.func.count()).select_from(Province)
            )
            assert count.scalar_one() == 1066
            kind = await session.execute(
                sa.select(Province.kind).where(Province.id == new_id)
            )
            assert kind.scalar_one() == "LAND"
        assert any(
            "1 added to provinces" in r.getMessage()
            and "0 retired removed" in r.getMessage()
            for r in capture.records
        )
    finally:
        await core_db.get_engine().dispose()
        core_db._engine = None
        core_db._async_session_maker = None
