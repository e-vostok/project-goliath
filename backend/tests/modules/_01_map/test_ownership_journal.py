"""
Ownership journal behaviour (Spec Part 1, Part 3.5, INV-M7).

Real in-memory SQLite via the shared test_db_session fixture; the
01_map hooks are registered through the conftest ``map_hooks``
fixture — the same functions startup registers. Nothing is mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from tests.fixtures.provinces import STARTING_GROUP

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
    short_name: str | None = None,
) -> Nation:
    profile = dict(VALID_PROFILE)
    if short_name is not None:
        profile["short_name"] = short_name
    return await NationService.create(
        session,
        owner_player_id=player.id,
        name=name,
        color_hex=color_hex,
        province_ids=province_ids,
        config=CORE_CONFIG,
        **profile,
    )


async def _set_turn(session, turn: int) -> None:
    """Give the game_clock singleton a turn for the next create."""
    result = await session.execute(select(GameClock).where(GameClock.id == 1))
    clock = result.scalar_one_or_none()
    if clock is None:
        session.add(
            GameClock(
                id=1,
                current_turn=turn,
                next_tick_at=datetime.now(UTC),
            )
        )
    else:
        clock.current_turn = turn
    await session.flush()


async def _log_rows(session) -> list[MapOwnershipLog]:
    result = await session.execute(select(MapOwnershipLog).order_by(MapOwnershipLog.id))
    return list(result.scalars().all())


class TestListenerWrites:
    """NationService create/delete -> one journal row per province."""

    @pytest.mark.asyncio
    async def test_create_writes_claim_rows(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session
        player = await _create_player(session)
        nation = await _create_nation(session, player, list(STARTING_GROUP))

        rows = await _log_rows(session)
        assert len(rows) == 5
        assert [r.province_id for r in rows] == list(STARTING_GROUP)
        for row in rows:
            assert row.prev_nation_id is None
            assert row.new_nation_id == nation.id
            assert row.new_nation_name == "Test Nation"
            # The event-time snapshot carries the short name too.
            assert row.new_nation_short_name == "Testland"
            assert row.new_nation_color == "#FF0000"
            assert row.turn_number == 0  # no game_clock row -> turn 0

    @pytest.mark.asyncio
    async def test_turn_comes_from_game_clock(
        self, linked_map_db_session, linked_map_hooks
    ):
        player = await _create_player(linked_map_db_session)
        await _set_turn(linked_map_db_session, 7)
        await _create_nation(linked_map_db_session, player, list(STARTING_GROUP))

        rows = await _log_rows(linked_map_db_session)
        assert [r.turn_number for r in rows] == [7] * 5

    @pytest.mark.asyncio
    async def test_delete_writes_release_rows(
        self, linked_map_db_session, linked_map_hooks
    ):
        player = await _create_player(linked_map_db_session)
        nation = await _create_nation(
            linked_map_db_session, player, list(STARTING_GROUP)
        )
        await _set_turn(linked_map_db_session, 4)

        await NationService.delete(linked_map_db_session, nation.id)

        rows = await _log_rows(linked_map_db_session)
        assert len(rows) == 10
        releases = [r for r in rows if r.new_nation_id is None]
        assert len(releases) == 5
        for row in releases:
            assert row.prev_nation_id == nation.id
            assert row.new_nation_name is None
            assert row.new_nation_short_name is None
            assert row.new_nation_color is None
            assert row.turn_number == 4

    @pytest.mark.asyncio
    async def test_two_nations_order_by_turn_then_id(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session
        player_a = await _create_player(session, vk_user_id=11)
        player_b = await _create_player(session, vk_user_id=22)
        await _set_turn(session, 1)
        nation_a = await _create_nation(
            session, player_a, list(STARTING_GROUP), name="A Realm"
        )
        await _set_turn(session, 5)
        nation_b = await _create_nation(
            session,
            player_b,
            [1009, 1010, 1011, 1012, 1013],
            name="B Realm",
            color_hex="#00FF00",
            short_name="BRealm",
        )

        rows = await _log_rows(session)
        ordered = [(r.turn_number, r.id) for r in rows]
        assert ordered == sorted(ordered)
        assert [r.new_nation_id for r in rows[:5]] == [nation_a.id] * 5
        assert [r.new_nation_id for r in rows[5:]] == [nation_b.id] * 5


class TestAtomicity:
    """INV-M7: a raising listener rolls the whole operation back."""

    @pytest.mark.asyncio
    async def test_failing_listener_rolls_back_create(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session

        async def boom(session, changes):
            raise RuntimeError("listener exploded")

        register_ownership_listener("zz_test_boom", boom)
        player = await _create_player(session)

        with pytest.raises(RuntimeError, match="listener exploded"):
            await _create_nation(session, player, list(STARTING_GROUP))
        # The HTTP layer's session context rolls back on the error;
        # replicate that boundary here.
        await session.rollback()

        result = await session.execute(select(func.count()).select_from(Nation))
        assert result.scalar_one() == 0
        owners = await session.execute(
            select(Province.nation_id).where(Province.id.in_(STARTING_GROUP))
        )
        assert all(o is None for o in owners.scalars().all())
        assert await _log_rows(session) == []

    @pytest.mark.asyncio
    async def test_failing_listener_rolls_back_delete(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session
        player = await _create_player(session)
        nation = await _create_nation(session, player, list(STARTING_GROUP))
        nation_id = nation.id
        await session.commit()

        async def boom(session, changes):
            raise RuntimeError("listener exploded")

        register_ownership_listener("zz_test_boom", boom)

        with pytest.raises(RuntimeError, match="listener exploded"):
            await NationService.delete(session, nation_id)
        await session.rollback()

        kept = await session.get(Nation, nation_id)
        assert kept is not None
        province = await session.get(Province, 1001)
        assert province.nation_id == nation_id
        rows = await _log_rows(session)
        assert len(rows) == 5  # only the committed create rows remain


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
                    new_short_name="OldA",
                    new_color="#111111",
                    turn=1,
                ),
                OwnershipChange(
                    province_id=1001,
                    prev_nation_id="nation-a",
                    new_nation_id=None,
                    new_name=None,
                    new_short_name=None,
                    new_color=None,
                    turn=3,
                ),
                OwnershipChange(
                    province_id=1001,
                    prev_nation_id=None,
                    new_nation_id="nation-b",
                    new_name="B Renamed",
                    new_short_name="B",
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
                    short_name="OldA",
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
                    short_name="B",
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
    async def test_ordered_by_turn_then_id(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session
        player = await _create_player(session)
        nation = await _create_nation(session, player, list(STARTING_GROUP))
        await NationService.delete(session, nation.id)

        rows = await records_for_province(session, 1002)
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
            new_short_name="X",
            new_color="#ABCDEF",
            turn=0,
        )
        with pytest.raises(ValueError, match="all set"):
            await record_changes(map_db_session, [change])

    @pytest.mark.asyncio
    async def test_short_name_pairs_with_nation_id(self, map_db_session):
        """Spec Part 1: the short name follows the nation id — a claim
        without it and a release carrying it are both rejected."""
        missing = OwnershipChange(
            province_id=1001,
            prev_nation_id=None,
            new_nation_id="nation-x",
            new_name="X Realm",
            new_short_name=None,  # claim without the short name
            new_color="#ABCDEF",
            turn=0,
        )
        with pytest.raises(ValueError, match="all set"):
            await record_changes(map_db_session, [missing])

        orphan = OwnershipChange(
            province_id=1001,
            prev_nation_id="nation-x",
            new_nation_id=None,
            new_name=None,
            new_short_name="X",  # release carrying a short name
            new_color=None,
            turn=1,
        )
        with pytest.raises(ValueError, match="all set"):
            await record_changes(map_db_session, [orphan])

    @pytest.mark.asyncio
    async def test_clear_all_wipes_journal(
        self, linked_map_db_session, linked_map_hooks
    ):
        session = linked_map_db_session
        player = await _create_player(session)
        await _create_nation(session, player, list(STARTING_GROUP))
        assert len(await _log_rows(session)) == 5

        await clear_all(session)

        assert await _log_rows(session) == []
