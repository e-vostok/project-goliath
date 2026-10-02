"""
Extension-point registries of 00_core (Spec 01_map Part 2).

00_core must work alone: with empty registries nation create/delete
behave exactly as before — this file proves that, plus the registry
contract (named, re-registering replaces, invocation order preserved).
No 01_map import anywhere in core.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    OwnershipChange,
    get_ownership_listeners,
    get_registration_checks,
    notify_ownership_changed,
    register_ownership_listener,
    register_registration_check,
    restore_extension_points,
    run_registration_checks,
    snapshot_extension_points,
)
from modules._00_core.models import Nation, Player, Province
from modules._00_core.service import NationService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture(autouse=True)
def clean_registries():
    saved = snapshot_extension_points()
    yield
    restore_extension_points(saved)


async def _make_nation(session, player, ids, name="Realm"):
    return await NationService.create(
        session,
        owner_player_id=player.id,
        name=name,
        color_hex="#102030",
        province_ids=ids,
        config=CORE_CONFIG,
        **VALID_PROFILE,
    )


class TestCoreAlone:
    """Empty registries: core behaviour is unchanged (Spec INV-M7)."""

    @pytest.mark.asyncio
    async def test_create_delete_without_listeners(
        self, test_db_session
    ):
        assert get_ownership_listeners() == {}
        player = Player(vk_user_id=777)
        test_db_session.add(player)
        for pid in (1001, 1002):
            await make_land_province(test_db_session, id=pid)
        await test_db_session.flush()

        nation = await _make_nation(test_db_session, player, [1001, 1002])
        assert nation.id is not None

        await NationService.delete(test_db_session, nation.id)
        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation.id)
        )
        assert result.scalar_one_or_none() is None


class TestOwnershipRegistry:
    @pytest.mark.asyncio
    async def test_notify_calls_in_registration_order(
        self, test_db_session
    ):
        calls = []

        async def first(session, changes):
            calls.append(("first", len(changes)))

        async def second(session, changes):
            calls.append(("second", len(changes)))

        register_ownership_listener("a", first)
        register_ownership_listener("b", second)

        change = OwnershipChange(
            province_id=1001,
            prev_nation_id=None,
            new_nation_id="n",
            new_name="N",
            new_color="#FFFFFF",
            turn=0,
        )
        await notify_ownership_changed(test_db_session, [change])

        assert calls == [("first", 1), ("second", 1)]

    @pytest.mark.asyncio
    async def test_same_name_replaces(self, test_db_session):
        calls = []

        async def old(session, changes):
            calls.append("old")

        async def new(session, changes):
            calls.append("new")

        register_ownership_listener("dup", old)
        register_ownership_listener("dup", new)

        await notify_ownership_changed(
            test_db_session,
            [
                OwnershipChange(
                    province_id=1,
                    prev_nation_id=None,
                    new_nation_id="n",
                    new_name="N",
                    new_color="#FFFFFF",
                    turn=0,
                )
            ],
        )
        assert calls == ["new"]
        assert list(get_ownership_listeners()) == ["dup"]

    @pytest.mark.asyncio
    async def test_raising_listener_propagates(self, test_db_session):
        async def boom(session, changes):
            raise RuntimeError("nope")

        register_ownership_listener("boom", boom)

        with pytest.raises(RuntimeError, match="nope"):
            await notify_ownership_changed(
                test_db_session,
                [
                    OwnershipChange(
                        province_id=1,
                        prev_nation_id=None,
                        new_nation_id=None,
                        new_name=None,
                        new_color=None,
                        turn=0,
                    )
                ],
            )


class TestCheckRegistry:
    @pytest.mark.asyncio
    async def test_stages_run_in_registration_order(
        self, test_db_session
    ):
        calls = []

        async def first(session, provinces):
            calls.append("first")

        async def second(session, provinces):
            calls.append("second")

        register_registration_check(STAGE_AFTER_FREE, "f", first)
        register_registration_check(STAGE_AFTER_COUNT, "s", second)

        await run_registration_checks(
            STAGE_AFTER_FREE, test_db_session, []
        )
        await run_registration_checks(
            STAGE_AFTER_COUNT, test_db_session, []
        )
        assert calls == ["first", "second"]

    @pytest.mark.asyncio
    async def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError, match="Unknown"):
            register_registration_check(
                "nonsense", "x", lambda s, p: None
            )


class TestWiredIntoNationService:
    """The registries actually gate and observe create/delete."""

    @pytest.mark.asyncio
    async def test_check_vetoes_create(self, test_db_session):
        from modules._00_core.exceptions import CoreDomainError

        async def veto(session, provinces):
            raise CoreDomainError("отказано", "TEST_VETO")

        register_registration_check(STAGE_AFTER_FREE, "veto", veto)
        player = Player(vk_user_id=778)
        test_db_session.add(player)
        await make_land_province(test_db_session, id=1001)
        await test_db_session.flush()

        with pytest.raises(CoreDomainError) as exc_info:
            await _make_nation(test_db_session, player, [1001])
        assert exc_info.value.code == "TEST_VETO"

    @pytest.mark.asyncio
    async def test_listener_sees_create_and_delete(
        self, test_db_session
    ):
        seen = []

        async def watcher(session, changes):
            seen.extend(changes)

        register_ownership_listener("watcher", watcher)
        player = Player(vk_user_id=779)
        test_db_session.add(player)
        await make_land_province(test_db_session, id=1001)
        await test_db_session.flush()

        nation = await _make_nation(test_db_session, player, [1001])
        assert len(seen) == 1
        assert seen[0].new_nation_id == nation.id
        assert seen[0].prev_nation_id is None

        await NationService.delete(test_db_session, nation.id)
        assert len(seen) == 2
        assert seen[1].prev_nation_id == nation.id
        assert seen[1].new_nation_id is None
