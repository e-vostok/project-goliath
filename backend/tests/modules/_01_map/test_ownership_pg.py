"""
Ownership journal on real PostgreSQL — window functions and the
listener path verified against DATABASE_URL_TEST (Spec Part 3.5,
INV-M7). Mirrors test_ownership_journal.py on SQLite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import OwnershipChange
from modules._00_core.models import GameClock, Nation, Player
from modules._00_core.service import NationService
from modules._01_map.models import MapOwnershipLog
from modules._01_map.service import (
    OwnerAtTurn,
    clear_all,
    owners_at_turn,
    record_changes,
    records_for_province,
)
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._01_map.conftest import sync_map_nodes

pytestmark = pytest.mark.postgres

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


async def _set_turn(session, turn: int) -> None:
    result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    result.scalar_one().current_turn = turn
    await session.flush()


class TestOwnersAtTurnPg:
    @pytest.mark.asyncio
    async def test_scripted_history(self, pg_db, flat_map_service):
        async with pg_db() as session:
            await sync_map_nodes(session, flat_map_service)
            await record_changes(
                session,
                [
                    OwnershipChange(
                        province_id=1001,
                        prev_nation_id=None,
                        new_nation_id="nation-a",
                        new_name="Old A Name",
                        new_color="#111111",
                        turn=1,
                    ),
                    OwnershipChange(
                        province_id=1001,
                        prev_nation_id="nation-a",
                        new_nation_id=None,
                        new_name=None,
                        new_color=None,
                        turn=3,
                    ),
                    OwnershipChange(
                        province_id=1001,
                        prev_nation_id=None,
                        new_nation_id="nation-b",
                        new_name="B Renamed",
                        new_color="#222222",
                        turn=5,
                    ),
                    OwnershipChange(
                        province_id=1002,
                        prev_nation_id=None,
                        new_nation_id="nation-c",
                        new_name="C Realm",
                        new_color="#333333",
                        turn=2,
                    ),
                ],
            )
            await session.commit()

        async with pg_db() as session:
            assert await owners_at_turn(session, 0) == {}
            assert await owners_at_turn(session, 1) == {
                1001: OwnerAtTurn("nation-a", "Old A Name", "#111111")
            }
            assert await owners_at_turn(session, 2) == {
                1001: OwnerAtTurn("nation-a", "Old A Name", "#111111"),
                1002: OwnerAtTurn("nation-c", "C Realm", "#333333"),
            }
            assert await owners_at_turn(session, 3) == {
                1002: OwnerAtTurn("nation-c", "C Realm", "#333333")
            }
            assert await owners_at_turn(session, 4) == {
                1002: OwnerAtTurn("nation-c", "C Realm", "#333333")
            }
            for turn in (5, 9):
                assert await owners_at_turn(session, turn) == {
                    1001: OwnerAtTurn("nation-b", "B Renamed", "#222222"),
                    1002: OwnerAtTurn("nation-c", "C Realm", "#333333"),
                }
            with pytest.raises(ValueError):
                await owners_at_turn(session, -1)

    @pytest.mark.asyncio
    async def test_records_for_province_ordering(
        self, pg_db, flat_map_service
    ):
        async with pg_db() as session:
            await sync_map_nodes(session, flat_map_service)
            await record_changes(
                session,
                [
                    OwnershipChange(1001, None, "n1", "N", "#111111", 1),
                    OwnershipChange(1001, "n1", None, None, None, 2),
                ],
            )
            await session.commit()

        async with pg_db() as session:
            rows = await records_for_province(session, 1001)
            assert [(r.turn_number, r.new_nation_id) for r in rows] == [
                (1, "n1"),
                (2, None),
            ]


class TestListenerOnPg:
    @pytest.mark.asyncio
    async def test_create_and_delete_journal_on_pg(
        self, pg_db, flat_map_service, map_hooks
    ):
        async with pg_db() as session:
            await sync_map_nodes(session, flat_map_service)
            player = Player(vk_user_id=991001)
            session.add(player)
            await session.flush()
            await _set_turn(session, 2)
            nation = await NationService.create(
                session,
                owner_player_id=player.id,
                name="PG Realm",
                color_hex="#0A0B0C",
                province_ids=[1001, 1002, 1003],
                config=CORE_CONFIG,
                **VALID_PROFILE,
            )
            await session.commit()

        async with pg_db() as session:
            rows = (
                (
                    await session.execute(
                        select(MapOwnershipLog).order_by(
                            MapOwnershipLog.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [r.province_id for r in rows] == [1001, 1002, 1003]
            assert all(
                r.prev_nation_id is None
                and r.new_nation_id == nation.id
                and r.new_nation_name == "PG Realm"
                and r.turn_number == 2
                for r in rows
            )

        async with pg_db() as session:
            await _set_turn(session, 6)
            await NationService.delete(session, nation.id)
            await session.commit()

        async with pg_db() as session:
            rows = (
                (
                    await session.execute(
                        select(MapOwnershipLog).order_by(
                            MapOwnershipLog.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 6
            releases = rows[3:]
            assert all(
                r.prev_nation_id == nation.id
                and r.new_nation_id is None
                and r.new_nation_name is None
                and r.turn_number == 6
                for r in releases
            )
            assert await owners_at_turn(session, 6) == {}

            await clear_all(session)
            await session.commit()
            count = await session.execute(
                select(func.count()).select_from(MapOwnershipLog)
            )
            assert count.scalar_one() == 0
