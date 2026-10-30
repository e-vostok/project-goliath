"""
Service tests for ProvinceService.transfer (0.11.0 unit 9a).

Real in-memory database, shared factories (Anti-Mock Guard): nations
and provinces are seeded straight through the ORM; the ownership
journal assertions go through the REAL 01_map listener path
(``record_changes`` registered as the ownership listener), and the
extension-point registries are snapshotted/restored per test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    AlreadyOwnerError,
    CapitalNameInvalidError,
    CapitalNotInProvincesError,
    CapitalRequiredError,
    LastProvinceError,
    NationNotFoundError,
    ProvinceNotFoundError,
    ProvinceNotLandError,
    SeizeNotConfirmedError,
)
from modules._00_core.hooks import (
    register_ownership_listener,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import GameClock, Nation, Province
from modules._00_core.service import ProvinceService
from modules._01_map.models import MapOwnershipLog
from modules._01_map.ownership_service import record_changes
from tests.fixtures.factories import make_player
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province, make_sea_province

CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture(autouse=True)
def extension_point_isolation():
    """Every test sees a clean listener registry and restores it after."""
    saved = snapshot_extension_points()
    yield
    restore_extension_points(saved)


async def _journal_listener(session, changes) -> None:
    """The real 01_map listener path: one journal row per change."""
    await record_changes(session, changes)


async def _make_provinces(session, ids: list[int]) -> None:
    for pid in ids:
        await make_land_province(session, id=pid)


_vk_seq = 990001


async def _make_nation(
    session,
    province_ids: list[int],
    *,
    capital_province_id: int | None = None,
    name: str = "Donor Realm",
    color_hex: str = "#AA0000",
    short_name: str = "Donor",
) -> Nation:
    """Seed a bare nation owning the given (already seeded) provinces."""
    global _vk_seq
    player = await make_player(session, vk_user_id=_vk_seq)
    _vk_seq += 1
    nation = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name=name,
        color_hex=color_hex,
        leader_name=VALID_PROFILE["leader_name"],
        leader_title=VALID_PROFILE["leader_title"],
        history_url=VALID_PROFILE["history_url"],
        short_name=short_name,
        gender=VALID_PROFILE["gender"],
        succession_type=VALID_PROFILE["succession_type"],
        capital_province_id=capital_province_id,
        capital_name="Testburg" if capital_province_id is not None else None,
        created_at=datetime.now(UTC),
        created_turn=0,
    )
    session.add(nation)
    await session.flush()
    for pid in province_ids:
        (await session.get(Province, pid)).nation_id = nation.id
    await session.flush()
    return nation


async def _province_ids_of(session, nation_id: str) -> list[int]:
    result = await session.execute(
        select(Province.id).where(Province.nation_id == nation_id)
    )
    return sorted(result.scalars().all())


class TestTransferBasics:
    """Free -> nation, release, and the seize confirmation."""

    @pytest.mark.asyncio
    async def test_free_province_to_nation(self, test_db_session):
        register_ownership_listener("test.journal", _journal_listener)
        await make_land_province(test_db_session, id=1001)
        receiver = await _make_nation(test_db_session, [], name="Receiver")

        result = await ProvinceService.transfer(
            test_db_session, 1001, receiver.id, config=CONFIG
        )

        assert result.province_id == 1001
        assert result.previous_nation_id is None
        assert result.new_nation_id == receiver.id
        assert result.new_capital_province_id is None
        assert await _province_ids_of(test_db_session, receiver.id) == [1001]

        journal = list(
            (
                await test_db_session.execute(
                    select(MapOwnershipLog).where(
                        MapOwnershipLog.province_id == 1001
                    )
                )
            ).scalars()
        )
        assert len(journal) == 1
        assert journal[0].prev_nation_id is None
        assert journal[0].new_nation_id == receiver.id
        assert journal[0].new_nation_short_name == receiver.short_name
        assert journal[0].new_nation_color == receiver.color_hex

    @pytest.mark.asyncio
    async def test_release(self, test_db_session):
        register_ownership_listener("test.journal", _journal_listener)
        await _make_provinces(test_db_session, [1001, 1002])
        donor = await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1002
        )

        result = await ProvinceService.transfer(
            test_db_session, 1001, None, config=CONFIG
        )

        assert result.previous_nation_id == donor.id
        assert result.new_nation_id is None
        assert await _province_ids_of(test_db_session, donor.id) == [1002]
        journal = list(
            (
                await test_db_session.execute(
                    select(MapOwnershipLog).where(
                        MapOwnershipLog.province_id == 1001
                    )
                )
            ).scalars()
        )
        assert len(journal) == 1
        assert journal[0].prev_nation_id == donor.id
        assert journal[0].new_nation_id is None
        assert journal[0].new_nation_name is None
        assert journal[0].new_nation_color is None

    @pytest.mark.asyncio
    async def test_seize_requires_confirm_seize(self, test_db_session):
        await _make_provinces(test_db_session, [1001, 1002, 1003])
        donor = await _make_nation(test_db_session, [1001, 1002])
        receiver = await _make_nation(
            test_db_session,
            [1003],
            name="Receiver",
            color_hex="#00AA00",
            short_name="Recv",
        )

        with pytest.raises(SeizeNotConfirmedError):
            await ProvinceService.transfer(
                test_db_session, 1001, receiver.id, config=CONFIG
            )
        assert (await test_db_session.get(Province, 1001)).nation_id == donor.id

        result = await ProvinceService.transfer(
            test_db_session,
            1001,
            receiver.id,
            confirm_seize=True,
            config=CONFIG,
        )
        assert result.previous_nation_id == donor.id
        assert result.new_nation_id == receiver.id

    @pytest.mark.asyncio
    async def test_already_owner_refused_both_ways(self, test_db_session):
        await _make_provinces(test_db_session, [1001, 1002, 1005])
        nation = await _make_nation(test_db_session, [1001, 1002])

        with pytest.raises(AlreadyOwnerError):
            await ProvinceService.transfer(
                test_db_session, 1001, nation.id, config=CONFIG
            )
        with pytest.raises(AlreadyOwnerError):
            await ProvinceService.transfer(
                test_db_session, 1005, None, config=CONFIG
            )

    @pytest.mark.asyncio
    async def test_no_min_max_bound(self, test_db_session):
        """The admin is not bound by min/max_provinces_per_nation: a
        5-province nation may end with 6 and a 5-province donor with 4."""
        await _make_provinces(test_db_session, list(range(1001, 1012)))
        donor = await _make_nation(
            test_db_session, [1001, 1002, 1003, 1004, 1005]
        )
        receiver = await _make_nation(
            test_db_session,
            [1006, 1007, 1008, 1009, 1010],
            name="Receiver",
            color_hex="#00AA00",
            short_name="Recv",
        )

        # Receiver: 5 -> 6 (above max_provinces_per_nation = 5).
        await ProvinceService.transfer(
            test_db_session, 1011, receiver.id, config=CONFIG
        )
        assert len(await _province_ids_of(test_db_session, receiver.id)) == 6
        # Donor: 5 -> 4 (below min_provinces_per_nation = 5).
        await ProvinceService.transfer(
            test_db_session, 1001, None, config=CONFIG
        )
        assert len(await _province_ids_of(test_db_session, donor.id)) == 4


class TestLastProvince:
    """The donor's last province can never leave (409 LAST_PROVINCE)."""

    @pytest.mark.asyncio
    async def test_last_province_refused_release_and_transfer(
        self, test_db_session
    ):
        await _make_provinces(test_db_session, [1001, 1002, 1003])
        donor = await _make_nation(test_db_session, [1001])
        receiver = await _make_nation(
            test_db_session,
            [1002, 1003],
            name="Receiver",
            color_hex="#00AA00",
            short_name="Recv",
        )

        for to_nation_id in (None, receiver.id):
            with pytest.raises(LastProvinceError):
                await ProvinceService.transfer(
                    test_db_session,
                    1001,
                    to_nation_id,
                    confirm_seize=True,
                    config=CONFIG,
                )
            # Nothing changed: ownership and the journal are untouched.
            assert (
                await test_db_session.get(Province, 1001)
            ).nation_id == donor.id
            journal_count = (
                await test_db_session.execute(
                    select(func.count()).select_from(MapOwnershipLog)
                )
            ).scalar_one()
            assert journal_count == 0


class TestCapitalRule:
    """Moving the donor's capital forces a replacement (INV-14)."""

    @pytest.mark.asyncio
    async def test_capital_move_without_replacement_refused(
        self, test_db_session
    ):
        await _make_provinces(test_db_session, [1001, 1002])
        await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1001
        )

        with pytest.raises(CapitalRequiredError):
            await ProvinceService.transfer(
                test_db_session, 1001, None, config=CONFIG
            )

    @pytest.mark.asyncio
    async def test_capital_move_with_wrong_replacement_refused(
        self, test_db_session
    ):
        await _make_provinces(test_db_session, [1001, 1002, 1003])
        await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1001
        )

        # 1003 is not one of the donor's remaining provinces.
        with pytest.raises(CapitalNotInProvincesError):
            await ProvinceService.transfer(
                test_db_session,
                1001,
                None,
                new_capital_province_id=1003,
                new_capital_name="Mini Beta",
                config=CONFIG,
            )

    @pytest.mark.asyncio
    async def test_capital_move_updates_capital_fields(
        self, test_db_session
    ):
        await _make_provinces(test_db_session, [1001, 1002])
        donor = await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1001
        )

        result = await ProvinceService.transfer(
            test_db_session,
            1001,
            None,
            new_capital_province_id=1002,
            new_capital_name="Mini Beta",
            config=CONFIG,
        )

        assert result.new_capital_province_id == 1002
        assert donor.capital_province_id == 1002
        assert donor.capital_name == "Mini Beta"

    @pytest.mark.asyncio
    async def test_capital_name_validated(self, test_db_session):
        await _make_provinces(test_db_session, [1001, 1002])
        await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1001
        )

        with pytest.raises(CapitalNameInvalidError):
            await ProvinceService.transfer(
                test_db_session,
                1001,
                None,
                new_capital_province_id=1002,
                new_capital_name="",
                config=CONFIG,
            )

    @pytest.mark.asyncio
    async def test_donor_without_capital_moves_freely(
        self, test_db_session
    ):
        """A pre-0.8.0 nation with no capital province is left as is."""
        await _make_provinces(test_db_session, [1001, 1002])
        donor = await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=None
        )

        result = await ProvinceService.transfer(
            test_db_session, 1001, None, config=CONFIG
        )

        assert result.new_capital_province_id is None
        assert donor.capital_province_id is None


class TestRefusalsAndJournal:
    """Kind/existence refusals, one journal entry, rollback."""

    @pytest.mark.asyncio
    async def test_sea_node_and_unknown_ids_refused(self, test_db_session):
        await make_sea_province(test_db_session, id=2001)
        nation = await _make_nation(test_db_session, [])

        with pytest.raises(ProvinceNotLandError):
            await ProvinceService.transfer(
                test_db_session, 2001, nation.id, config=CONFIG
            )
        with pytest.raises(ProvinceNotFoundError):
            await ProvinceService.transfer(
                test_db_session, 9999, nation.id, config=CONFIG
            )
        await make_land_province(test_db_session, id=1001)
        with pytest.raises(NationNotFoundError):
            await ProvinceService.transfer(
                test_db_session, 1001, "nation-missing", config=CONFIG
            )

    @pytest.mark.asyncio
    async def test_journal_gains_exactly_one_entry_with_turn(
        self, test_db_session
    ):
        register_ownership_listener("test.journal", _journal_listener)
        test_db_session.add(
            GameClock(
                id=1,
                current_turn=7,
                last_tick_at=None,
                next_tick_at=datetime.now(UTC),
            )
        )
        await _make_provinces(test_db_session, [1001, 1002])
        donor = await _make_nation(test_db_session, [1001, 1002])
        receiver = await _make_nation(
            test_db_session,
            [],
            name="Receiver",
            color_hex="#00AA00",
            short_name="Recv",
        )

        await ProvinceService.transfer(
            test_db_session,
            1001,
            receiver.id,
            confirm_seize=True,
            config=CONFIG,
        )

        journal = list(
            (await test_db_session.execute(select(MapOwnershipLog))).scalars()
        )
        assert len(journal) == 1
        entry = journal[0]
        assert entry.province_id == 1001
        assert entry.prev_nation_id == donor.id
        assert entry.new_nation_id == receiver.id
        assert entry.turn_number == 7

    @pytest.mark.asyncio
    async def test_failing_listener_rolls_everything_back(
        self, test_db_session
    ):
        await _make_provinces(test_db_session, [1001, 1002])
        donor = await _make_nation(
            test_db_session, [1001, 1002], capital_province_id=1001
        )
        donor_id = donor.id
        # Commit the seed state so the failed transfer's rollback has a
        # committed baseline to return to.
        await test_db_session.commit()

        async def broken_listener(_session, _changes):
            raise RuntimeError("listener broke")

        register_ownership_listener("broken", broken_listener)

        with pytest.raises(RuntimeError, match="listener broke"):
            await ProvinceService.transfer(
                test_db_session,
                1001,
                None,
                new_capital_province_id=1002,
                new_capital_name="Mini Beta",
                config=CONFIG,
            )
        await test_db_session.rollback()

        # The ORM write and the capital change are rolled back too.
        province = await test_db_session.get(Province, 1001)
        assert province.nation_id == donor_id
        donor_row = await test_db_session.get(Nation, donor_id)
        assert donor_row.capital_province_id == 1001
