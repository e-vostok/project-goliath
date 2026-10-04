"""
Read-only retired-nodes report (map_polish_2b) on real SQLite.

Each test gets a migrated tmp SQLite file reached through
DATABASE_URL — the same resolution the CLI uses — and a mini-map
directory via MAP_DATA_DIR. Anti-Mock Guard: real engine, real Alembic
schema, real map files; nothing is mocked.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules._00_core.models import Nation, Player, Province
from modules._01_map import retired_report
from modules._01_map.models import MapOwnershipLog
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._01_map.conftest import (
    copy_map_mini,
    fix_input_hashes,
    load_lock,
    save_lock,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]

RETIRED_LAND = 9999
RETIRED_SEA = 9998
UNKNOWN_ID = 8888


@pytest_asyncio.fixture
async def report_db(tmp_path, monkeypatch):
    """
    A migrated tmp SQLite file with DATABASE_URL pointing at it —
    exactly what the report resolves when run as a CLI.
    """
    db_file = tmp_path / "report.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    # alembic env.py shares resolve_database_url; to_sync_database_url
    # turns sqlite+aiosqlite into the sync form for the migration run.
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    yield url


@pytest.fixture
def mini_map_env(monkeypatch, mini_map_config):
    """MAP_DATA_DIR -> the mini fixture (no retired ids in its lock)."""
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    yield


@pytest.fixture
def retired_map_env(tmp_path, monkeypatch, mini_map_config):
    """MAP_DATA_DIR -> a mini-map copy with two retired lock ids."""
    data_dir = copy_map_mini(tmp_path)
    lock = load_lock(data_dir)
    lock["ids"]["mini_retired_land"] = RETIRED_LAND
    lock["ids"]["sea_mini_retired"] = RETIRED_SEA
    save_lock(data_dir, lock)
    fix_input_hashes(data_dir)
    monkeypatch.setenv("MAP_DATA_DIR", str(data_dir))
    yield


@asynccontextmanager
async def _session(url: str):
    """A second engine on the same DB — seeds and checks committed state."""
    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed_active_nodes(session) -> None:
    """All 10 mini-map nodes — what a synced database looks like."""
    for node_id in range(1001, 1009):
        session.add(Province(id=node_id, kind="LAND", nation_id=None))
    for node_id in (2001, 2002):
        session.add(Province(id=node_id, kind="SEA", nation_id=None))


async def _table_counts(url: str) -> dict[str, int]:
    async with _session(url) as session:
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


def _journal_row(province_id: int, turn: int) -> MapOwnershipLog:
    return MapOwnershipLog(
        province_id=province_id,
        turn_number=turn,
        prev_nation_id="gone-nation",
        new_nation_id=None,
        new_nation_name=None,
        new_nation_color=None,
        created_at=datetime.now(timezone.utc),
    )


class TestReady:
    @pytest.mark.asyncio
    async def test_clean_db_with_active_nodes(
        self, report_db, mini_map_env, capsys
    ):
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_OK
        assert out.startswith("Target: sqlite+aiosqlite")
        assert "Версия геометрии:" in out
        assert "Узлов в manifest.json: 10" in out
        assert "Строк в таблице provinces: 10" in out
        assert "ГОТОВО: запуск пройдёт, будет удалено 0 строк" in out

    @pytest.mark.asyncio
    async def test_retired_unowned_rows_counted(
        self, report_db, retired_map_env, capsys
    ):
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            session.add(
                Province(id=RETIRED_LAND, kind="LAND", nation_id=None)
            )
            session.add(
                Province(id=RETIRED_SEA, kind="SEA", nation_id=None)
            )
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_OK
        assert "Выведенных id в ids.lock.json" in out
        assert "(LAND: 1, SEA: 1)" in out
        assert "ГОТОВО: запуск пройдёт, будет удалено 2 строки" in out


class TestStop:
    @pytest.mark.asyncio
    async def test_owned_retired_province_stops(
        self, report_db, retired_map_env, capsys
    ):
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            session.add(
                Player(
                    id="player-retired",
                    vk_user_id=777002,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                Nation(
                    id="nation-retired",
                    owner_player_id="player-retired",
                    name="Retired Owner",
                    color_hex="#102030",
                    created_at=datetime.now(timezone.utc),
                    **VALID_PROFILE,
                )
            )
            session.add(
                Province(
                    id=RETIRED_LAND,
                    kind="LAND",
                    nation_id="nation-retired",
                )
            )
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_STOP
        assert f"id {RETIRED_LAND} (mini_retired_land)" in out
        assert "nation-retired" in out
        assert "Retired Owner" in out
        assert "СТОП: запуск остановится" in out
        assert "RETIRED_PROVINCE_OWNED" in out

    @pytest.mark.asyncio
    async def test_journal_rows_on_retired_province_stop(
        self, report_db, retired_map_env, capsys
    ):
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            session.add(
                Province(id=RETIRED_LAND, kind="LAND", nation_id=None)
            )
            session.add(_journal_row(RETIRED_LAND, 3))
            session.add(_journal_row(RETIRED_LAND, 7))
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_STOP
        assert f"id {RETIRED_LAND} (mini_retired_land)" in out
        assert "записей: 2, ходы 3–7" in out
        assert "СТОП: запуск остановится" in out
        assert "RETIRED_PROVINCE_HISTORY" in out

    @pytest.mark.asyncio
    async def test_unknown_extra_row_stops(
        self, report_db, mini_map_env, capsys
    ):
        """A row whose id is in neither manifest nor lock — INV_M5."""
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            session.add(
                Province(id=UNKNOWN_ID, kind="LAND", nation_id=None)
            )
            await session.commit()

        code = await retired_report.run()

        out = capsys.readouterr().out
        assert code == retired_report.EXIT_STOP
        assert str(UNKNOWN_ID) in out
        assert "СТОП: запуск остановится" in out
        assert "INV_M5" in out

    @pytest.mark.asyncio
    async def test_corrupted_map_exits_2(
        self, report_db, tmp_path, monkeypatch, mini_map_config, capsys
    ):
        data_dir = copy_map_mini(tmp_path)
        boundary = data_dir / "boundary.yaml"
        boundary.write_text(
            boundary.read_text(encoding="utf-8") + "\n# touched\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAP_DATA_DIR", str(data_dir))

        code = await retired_report.run()

        captured = capsys.readouterr()
        assert code == retired_report.EXIT_MAP_DATA
        assert captured.out.startswith("Target: sqlite+aiosqlite")
        assert "INV_M10" in captured.err


class TestReadOnly:
    @pytest.mark.asyncio
    async def test_row_counts_unchanged(
        self, report_db, retired_map_env, capsys
    ):
        """Seeded rows survive the report byte-for-byte — it is SELECT-only."""
        async with _session(report_db) as session:
            await _seed_active_nodes(session)
            session.add(
                Player(
                    id="player-ro",
                    vk_user_id=777003,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                Nation(
                    id="nation-ro",
                    owner_player_id="player-ro",
                    name="Read Only",
                    color_hex="#203040",
                    created_at=datetime.now(timezone.utc),
                    **VALID_PROFILE,
                )
            )
            session.add(
                Province(
                    id=RETIRED_LAND,
                    kind="LAND",
                    nation_id="nation-ro",
                )
            )
            session.add(
                Province(id=RETIRED_SEA, kind="SEA", nation_id=None)
            )
            session.add(_journal_row(RETIRED_LAND, 5))
            await session.commit()

        before = await _table_counts(report_db)
        code = await retired_report.run()
        after = await _table_counts(report_db)

        assert code == retired_report.EXIT_STOP
        assert before == after == {
            "provinces": 12,
            "nations": 1,
            "map_ownership_log": 1,
        }
        async with _session(report_db) as session:
            assert await session.get(Province, RETIRED_LAND) is not None


def test_main_entrypoint(
    tmp_path, monkeypatch, mini_map_config, capsys
):
    """python -m path: sync main() wraps asyncio.run(run())."""
    db_file = tmp_path / "cli.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

    assert retired_report.main() == retired_report.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Target: sqlite+aiosqlite")
    assert "ГОТОВО: запуск пройдёт" in out
