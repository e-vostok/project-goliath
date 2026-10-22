"""
Tests for the built-in table sources (Spec 3.2, 3.3, 3.5, Appendix T).

Everything is exercised through ``build_table`` on the real in-memory
DB — the sources are reached exactly the way the endpoint reaches them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Province
from modules._00_core.service import NationService
from modules._03_registry.service import build_table
from modules._03_registry.startup import startup_registry
from tests.fixtures.factories import make_vk_profile
from tests.fixtures.provinces import make_land_province, make_sea_province
from tests.modules._03_registry.conftest import seed_nation, seed_player

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _rows_by_key(built) -> dict[str, dict]:
    """row key -> cells dict of a built table."""
    return {row.key: row.cells for row in built.rows}


class TestPlayersTable:
    """The ``players`` table (Spec 3.2)."""

    async def test_rows_numbering_and_fallback_names(
        self, test_db_session, registry_started
    ):
        await seed_player(test_db_session, 501001, created_at=T0)
        p2 = await seed_player(test_db_session, 501002, created_at=T0.replace(hour=13))
        n2 = await seed_nation(
            test_db_session, p2, "Второе", "#112233", created_turn=0
        )

        built = await build_table(test_db_session, "players")
        rows = _rows_by_key(built)

        assert built.total == 2
        assert built.truncated is False
        assert set(rows) == {"p1", "p2"}

        first, second = rows["p1"], rows["p2"]
        assert first["number"] == 1
        assert second["number"] == 2
        # No profile rows yet -> the configured fallback name.
        assert first["player"] == {
            "name": "Игрок №1",
            "avatar_url": None,
            "is_fallback": True,
        }
        # The nationless player's nation cell is null; the owner's
        # carries {id, name, color, flag_url} (Spec 3.6).
        assert first["nation"] is None
        assert second["nation"] == {
            "id": n2.id,
            "name": "Второе",
            "color": "#112233",
            "flag_url": None,
        }
        assert first["level"] == 1
        assert first["judge_rating"] == 0

        # A newer player appended later leaves existing numbers fixed
        # (Spec D2 / 3.2).
        await seed_player(test_db_session, 501003, created_at=T0.replace(hour=14))
        rows = _rows_by_key(await build_table(test_db_session, "players"))
        assert rows["p1"]["number"] == 1
        assert rows["p2"]["number"] == 2
        assert rows["p3"]["player"]["name"] == "Игрок №3"

    async def test_saved_profile_supplies_name_and_avatar(
        self, test_db_session, registry_started
    ):
        p1 = await seed_player(test_db_session, 501101, created_at=T0)
        p2 = await seed_player(test_db_session, 501102, created_at=T0.replace(hour=13))
        # OK profile: real name + avatar. PENDING row without names:
        # still the fallback.
        await make_vk_profile(
            test_db_session,
            p1,
            status="OK",
            first_name="Иван",
            last_name="Петров",
            photo_url="https://example.ru/a50.png",
        )
        await make_vk_profile(
            test_db_session,
            p2,
            status="PENDING",
            first_name=None,
            last_name=None,
        )

        rows = _rows_by_key(await build_table(test_db_session, "players"))

        assert rows["p1"]["player"] == {
            "name": "Иван Петров",
            "avatar_url": "https://example.ru/a50.png",
            "is_fallback": False,
        }
        assert rows["p2"]["player"] == {
            "name": "Игрок №2",
            "avatar_url": None,
            "is_fallback": True,
        }

    async def test_joined_uses_tick_timezone(self, test_db_session, registry_started):
        # 22:30 UTC = 01:30 Europe/Moscow of the NEXT day (Spec 3.5, D7).
        await seed_player(
            test_db_session,
            501201,
            created_at=datetime(2026, 10, 13, 22, 30, tzinfo=UTC),
        )

        rows = _rows_by_key(await build_table(test_db_session, "players"))

        assert rows["p1"]["joined"] == {
            "text": "14 октября 2026",
            "key": (date(2026, 10, 14) - date(1970, 1, 1)).days,
        }

    async def test_players_build_query_count_is_constant(
        self, test_db_session, test_db_engine, registry_started
    ):
        """One players join + one profiles fetch — independent of N."""
        for i in range(5):
            await seed_player(
                test_db_session, 501300 + i, created_at=T0.replace(hour=i)
            )
        await test_db_session.flush()

        statements: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(test_db_engine.sync_engine, "before_cursor_execute", _count)
        try:
            await build_table(test_db_session, "players")
        finally:
            event.remove(
                test_db_engine.sync_engine,
                "before_cursor_execute",
                _count,
            )
        assert len(statements) == 2


class TestNationsTable:
    """The ``nations`` table (Spec 3.3)."""

    async def test_numbering_delete_shift_and_province_count(
        self, test_db_session, registry_started
    ):
        owners = [await seed_player(test_db_session, 502001 + i) for i in range(3)]
        # Deliberately out of created_at order vs created_turn: the
        # ordering key is (created_turn, created_at, id).
        n1 = await seed_nation(
            test_db_session,
            owners[0],
            "Первая",
            "#AA0001",
            created_turn=2,
            created_at=T0,
        )
        n2 = await seed_nation(
            test_db_session,
            owners[1],
            "Вторая",
            "#AA0002",
            created_turn=0,
            created_at=T0.replace(hour=13),
        )
        n3 = await seed_nation(
            test_db_session,
            owners[2],
            "Третья",
            "#AA0003",
            created_turn=2,
            created_at=T0.replace(hour=14),
        )
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await make_land_province(test_db_session, id=1003)
        await make_sea_province(test_db_session, id=2001)
        for pid in (1001, 1002):
            (
                await test_db_session.execute(
                    select(Province).where(Province.id == pid)
                )
            ).scalar_one().nation_id = n1.id
        await test_db_session.flush()

        built = await build_table(test_db_session, "nations")
        ordered = [row.key for row in built.rows]
        # n2 (turn 0) first; n1 before n3 within turn 2 by created_at.
        assert ordered == [n2.id, n1.id, n3.id]
        rows = _rows_by_key(built)
        assert rows[n2.id]["number"] == 1
        assert rows[n1.id]["number"] == 2
        assert rows[n3.id]["number"] == 3
        # Only the nation's own land provinces count.
        assert rows[n1.id]["provinces"] == 2
        assert rows[n2.id]["provinces"] == 0
        # formed: key = created_turn; text on the game calendar
        # (epoch 2040-01-01 + 2 turns * 1 month = Март 2040).
        assert rows[n1.id]["formed"] == {
            "text": "Март 2040",
            "key": 2,
        }
        assert rows[n1.id]["flag"] == {"color": "#AA0001", "image_url": None}

        # Deleting a nation shifts the numbers after it (Spec 3.3, D2).
        await NationService.delete(test_db_session, n1.id)
        rows = _rows_by_key(await build_table(test_db_session, "nations"))
        assert rows[n2.id]["number"] == 1
        assert rows[n3.id]["number"] == 2


class TestCoreConfigInjection:
    """The sources use the CoreConfig captured at startup — a table
    request must never re-open ``00_core.yaml``."""

    async def test_source_uses_injected_config_without_disk_read(
        self, test_db_session, registry_isolation, monkeypatch
    ):
        core_config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        monkeypatch.setattr(
            CoreConfig,
            "from_yaml",
            classmethod(
                lambda cls, path: pytest.fail(
                    "CoreConfig.from_yaml called during a table request"
                )
            ),
        )
        startup_registry(core_config=core_config)

        player = await seed_player(test_db_session, 503001, created_at=T0)
        nation = await seed_nation(
            test_db_session, player, "Инъекция", "#00AA44", created_turn=2
        )

        players = await build_table(test_db_session, "players")
        nations = await build_table(test_db_session, "nations")
        assert players.total == 1
        assert _rows_by_key(nations)[nation.id]["formed"] == {
            "text": "Март 2040",
            "key": 2,
        }
