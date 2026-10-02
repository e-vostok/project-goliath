"""
Ownership journal behaviour (Spec Part 1, Part 3.5, INV-M7).

Real in-memory SQLite via the shared test_db_session fixture; the
01_map hooks are registered through the conftest ``map_hooks``
fixture — the same functions startup registers. Nothing is mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import OwnershipChange, register_ownership_listener
from modules._00_core.models import GameClock, Nation, Player, Province
from modules._00_core.service import NationService
from modules._01_map.models import MapOwnershipLog
from modules._01_map.service import (
    OwnerAtTurn,
    clear_all,
    owners_at_turn,
    record_changes,
    records_for_province,
)
from tests.fixtures.profile import VALID_PROFILE

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


async def _create_player(session, vk_user_id: int = 11111) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


async def _create_nation(
    session,
    player: Player,
    province_ids: list[int],
    name: str = "Test Nation",
    color_hex: str = "#FF0000",
) -> Nation:
    return await NationService.create(
        session,
        owner_player_id=player.id,
        name=name,
        color_hex=color_hex,
        province_ids=province_ids,
        config=CORE_CONFIG,
        **VALID_PROFILE,
    )


async def _set_turn(session, turn: int) -> None:
    """Give the game_clock singleton a turn for the next create."""
    result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    clock = result.scalar_one_or_none()
    if clock is None:
        session.add(
            GameClock(
                id=1,
                current_turn=turn,
                next_tick_at=datetime.now(timezone.utc),
            )
        )
    else:
        clock.current_turn = turn
    await session.flush()


async def _log_rows(session) -> list[MapOwnershipLog]:
    result = await session.execute(
        select(MapOwnershipLog).order_by(MapOwnershipLog.id)
    )
    return list(result.scalars().all())


class TestListenerWrites:
    """NationService create/delete -> one journal row per province."""

    @pytest.mark.asyncio
    async def test_create_writes_claim_rows(
        self, map_db_session, map_hooks
    ):
        player = await _create_player(map_db_session)
        nation = await _create_nation(
            map_db_session, player, [1001, 1002, 1003]
        )

        rows = await _log_rows(map_db_session)
        assert len(rows) == 3
        assert [r.province_id for r in rows] == [1001, 1002, 1003]
        for row in rows:
            assert row.prev_nation_id is None
            assert row.new_nation_id == nation.id
            assert row.new_nation_name == "Test Nation"
            assert row.new_nation_color == "#FF0000"
            assert row.turn_number == 0  # no game_clock row -> turn 0

    @pytest.mark.asyncio
    async def test_turn_comes_from_game_clock(
        self, map_db_session, map_hooks
    ):
        player = await _create_player(map_db_session)
        await _set_turn(map_db_session, 7)
        await _create_nation(map_db_session, player, [1001])

        rows = await _log_rows(map_db_session)
        assert [r.turn_number for r in rows] == [7]

    @pytest.mark.asyncio
    async def test_delete_writes_release_rows(
        self, map_db_session, map_hooks
    ):
        player = await _create_player(map_db_session)
        nation = await _create_nation(
            map_db_session, player, [1001, 1002, 1003]
        )
        await _set_turn(map_db_session, 4)

        await NationService.delete(map_db_session, nation.id)

        rows = await _log_rows(map_db_session)
        assert len(rows) == 6
        releases = [r for r in rows if r.new_nation_id is None]
        assert len(releases) == 3
        for row in releases:
            assert row.prev_nation_id == nation.id
            assert row.new_nation_name is None
            assert row.new_nation_color is None
            assert row.turn_number == 4

    @pytest.mark.asyncio
    async def test_two_nations_order_by_turn_then_id(
        self, map_db_session, map_hooks
    ):
        player_a = await _create_player(map_db_session, vk_user_id=11)
        player_b = await _create_player(map_db_session, vk_user_id=22)
        await _set_turn(map_db_session, 1)
        nation_a = await _create_nation(
            map_db_session, player_a, [1001], name="A Realm"
        )
        await _set_turn(map_db_session, 5)
        nation_b = await _create_nation(
            map_db_session,
            player_b,
            [1005, 1006],
            name="B Realm",
            color_hex="#00FF00",
        )

        rows = await _log_rows(map_db_session)
        ordered = [(r.turn_number, r.id) for r in rows]
        assert ordered == sorted(ordered)
        assert rows[0].new_nation_id == nation_a.id
        assert [r.new_nation_id for r in rows[1:]] == [
            nation_b.id,
            nation_b.id,
        ]


class TestAtomicity:
    """INV-M7: a raising listener rolls the whole operation back."""

    @pytest.mark.asyncio
    async def test_failing_listener_rolls_back_create(
        self, map_db_session, map_hooks
    ):
        async def boom(session, changes):
            raise RuntimeError("listener exploded")

        register_ownership_listener("zz_test_boom", boom)
        player = await _create_player(map_db_session)

        with pytest.raises(RuntimeError, match="listener exploded"):
            await _create_nation(map_db_session, player, [1001, 1002])
        # The HTTP layer's session context rolls back on the error;
        # replicate that boundary here.
        await map_db_session.rollback()

        result = await map_db_session.execute(select(func.count()).select_from(Nation))
        assert result.scalar_one() == 0
        owners = await map_db_session.execute(
            select(Province.nation_id).where(Province.id.in_([1001, 1002]))
        )
        assert all(o is None for o in owners.scalars().all())
        assert await _log_rows(map_db_session) == []

    @pytest.mark.asyncio
    async def test_failing_listener_rolls_back_delete(
        self, map_db_session, map_hooks
    ):
        player = await _create_player(map_db_session)
        nation = await _create_nation(map_db_session, player, [1001])
        nation_id = nation.id
        await map_db_session.commit()

        async def boom(session, changes):
            raise RuntimeError("listener exploded")

        register_ownership_listener("zz_test_boom", boom)

        with pytest.raises(RuntimeError, match="listener exploded"):
            await NationService.delete(map_db_session, nation_id)
        await map_db_session.rollback()

        kept = await map_db_session.get(Nation, nation_id)
        assert kept is not None
        province = await map_db_session.get(Province, 1001)
        assert province.nation_id == nation_id
        rows = await _log_rows(map_db_session)
        assert len(rows) == 1  # only the committed create row remains


class TestOwnersAtTurn:
    """Formula 3.5: per-turn snapshot from the journal alone."""

    async def _scripted_history(self, session) -> dict:
        """Nation A claims 1001 at turn 1, releases at turn 3;
        nation B (renamed before its event) claims at turn 5."""
        await _set_turn(session, 0)
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
            ],
        )

    @pytest.mark.asyncio
    async def test_snapshot_answers(self, map_db_session, map_hooks):
        await self._scripted_history(map_db_session)

        assert await owners_at_turn(map_db_session, 0) == {}

        for turn in (1, 2):
            owners = await owners_at_turn(map_db_session, turn)
            assert owners == {
                1001: OwnerAtTurn(
                    nation_id="nation-a",
                    name="Old A Name",
                    color="#111111",
                )
            }

        # Released at turn 3 -> absent at 3 and 4.
        for turn in (3, 4):
            assert await owners_at_turn(map_db_session, turn) == {}

        for turn in (5, 9):
            owners = await owners_at_turn(map_db_session, turn)
            assert owners == {
                1001: OwnerAtTurn(
                    nation_id="nation-b",
                    name="B Renamed",
                    color="#222222",
                )
            }

    @pytest.mark.asyncio
    async def test_negative_turn_raises(self, map_db_session):
        with pytest.raises(ValueError):
            await owners_at_turn(map_db_session, -1)

    @pytest.mark.asyncio
    async def test_never_owned_province_absent(self, map_db_session):
        assert await owners_at_turn(map_db_session, 42) == {}


class TestRecordsForProvince:
    @pytest.mark.asyncio
    async def test_ordered_by_turn_then_id(self, map_db_session, map_hooks):
        player = await _create_player(map_db_session)
        nation = await _create_nation(map_db_session, player, [1002])
        await NationService.delete(map_db_session, nation.id)

        rows = await records_for_province(map_db_session, 1002)
        assert len(rows) == 2
        assert rows[0].new_nation_id == nation.id
        assert rows[1].new_nation_id is None
        assert rows[1].prev_nation_id == nation.id

    @pytest.mark.asyncio
    async def test_empty_for_untouched_province(self, map_db_session):
        assert await records_for_province(map_db_session, 1004) == []


class TestServiceGuards:
    @pytest.mark.asyncio
    async def test_inconsistent_triple_rejected(self, map_db_session):
        """The Python guard fires before the DB check constraint."""
        change = OwnershipChange(
            province_id=1001,
            prev_nation_id=None,
            new_nation_id="nation-x",
            new_name=None,  # inconsistent: id set, name NULL
            new_color="#ABCDEF",
            turn=0,
        )
        with pytest.raises(ValueError, match="all set"):
            await record_changes(map_db_session, [change])

    @pytest.mark.asyncio
    async def test_clear_all_wipes_journal(self, map_db_session, map_hooks):
        player = await _create_player(map_db_session)
        await _create_nation(map_db_session, player, [1001, 1002])
        assert len(await _log_rows(map_db_session)) == 2

        await clear_all(map_db_session)

        assert await _log_rows(map_db_session) == []
