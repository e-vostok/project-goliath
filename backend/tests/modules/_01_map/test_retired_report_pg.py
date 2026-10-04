"""
Read-only retired-nodes report (map_polish_2b) on real PostgreSQL.

Mirrors test_retired_report.py: the report resolves DATABASE_URL —
here pointed at the throwaway *_test database — and must produce the
same verdicts against the production dialect. Requires
DATABASE_URL_TEST; skips like the rest of the postgres suite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa

from modules._00_core.models import Nation, Player, Province
from modules._01_map import retired_report
from modules._01_map.models import MapOwnershipLog
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — resolved through the fixture chain
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,
)
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._01_map.conftest import (
    copy_map_mini,
    fix_input_hashes,
    load_lock,
    save_lock,
    sync_map_nodes,
)

pytestmark = pytest.mark.postgres

RETIRED_ID = 9999


@pytest_asyncio.fixture
async def pg_report_db(pg_url, pg_clean, monkeypatch, tmp_path, mini_map_config):
    """
    DATABASE_URL -> the PG test DB and MAP_DATA_DIR -> a mini-map copy
    with one retired lock id, so ``retired_report.run()`` exercises the
    real resolution path end to end.
    """
    monkeypatch.setenv("DATABASE_URL", pg_url)
    data_dir = copy_map_mini(tmp_path)
    lock = load_lock(data_dir)
    lock["ids"]["mini_retired"] = RETIRED_ID
    save_lock(data_dir, lock)
    fix_input_hashes(data_dir)
    monkeypatch.setenv("MAP_DATA_DIR", str(data_dir))
    yield pg_url


async def _table_counts(session) -> dict[str, int]:
    counts = {}
    for name, model in (
        ("provinces", Province),
        ("nations", Nation),
        ("map_ownership_log", MapOwnershipLog),
    ):
        result = await session.execute(
            sa.select(sa.func.count()).select_from(model)
        )
        counts[name] = result.scalar_one()
    return counts


class TestRetiredReportPg:
    @pytest.mark.asyncio
    async def test_ready_with_removable_retired_row(
        self, pg_report_db, pg_db, flat_map_service, capsys
    ):
        async with pg_db() as session:
            await sync_map_nodes(session, flat_map_service)
            session.add(
                Province(id=RETIRED_ID, kind="LAND", nation_id=None)
            )
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_OK
        assert out.startswith("Target: postgresql+asyncpg://")
        assert "(LAND: 1, SEA: 0)" in out
        assert "ГОТОВО: запуск пройдёт, будет удалено 1 строка" in out

    @pytest.mark.asyncio
    async def test_owned_and_journalled_retired_row_stops(
        self, pg_report_db, pg_db, capsys
    ):
        async with pg_db() as session:
            session.add(
                Player(
                    id="player-pg",
                    vk_user_id=777004,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                Nation(
                    id="nation-pg",
                    owner_player_id="player-pg",
                    name="Pg Owner",
                    color_hex="#334455",
                    created_at=datetime.now(timezone.utc),
                    **VALID_PROFILE,
                )
            )
            session.add(
                Province(
                    id=RETIRED_ID, kind="LAND", nation_id="nation-pg"
                )
            )
            # PG enforces the map_ownership_log -> provinces FK: flush
            # the row before appending its journal entries.
            await session.flush()
            session.add(
                MapOwnershipLog(
                    province_id=RETIRED_ID,
                    turn_number=2,
                    prev_nation_id=None,
                    new_nation_id="old-nation",
                    new_nation_name="Old Nation",
                    new_nation_color="#112233",
                    created_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_STOP
        assert "Pg Owner" in out
        assert "СТОП: запуск остановится" in out
        assert "RETIRED_PROVINCE_OWNED" in out
        assert "RETIRED_PROVINCE_HISTORY" in out

    @pytest.mark.asyncio
    async def test_read_only_on_postgres(
        self, pg_report_db, pg_db, flat_map_service, capsys
    ):
        """Row counts of provinces/nations/map_ownership_log unchanged."""
        async with pg_db() as session:
            await sync_map_nodes(session, flat_map_service)
            session.add(
                Province(id=RETIRED_ID, kind="LAND", nation_id=None)
            )
            await session.commit()
            before = await _table_counts(session)

        code = await retired_report.run()

        async with pg_db() as session:
            after = await _table_counts(session)
        assert code == retired_report.EXIT_OK
        assert before == after
