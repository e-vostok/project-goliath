"""
The "nation created" extension point of 00_core (Spec 02_bot 3.11, B10).

Hooks run inside ``NationService.create`` after all creation writes,
still in the caller's transaction, each under its own SAVEPOINT: a
failing hook keeps none of its writes and never aborts the
registration. With no hooks registered the creation behaves exactly as
before.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    clear_nation_created_hooks,
    get_nation_created_hooks,
    register_nation_created_hook,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Nation, Player, Province
from modules._00_core.service import NationService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture(autouse=True)
def _isolated_hooks():
    """Clear the registry for the test, then restore what was there."""
    saved = snapshot_extension_points()
    clear_nation_created_hooks()
    yield
    restore_extension_points(saved)


async def _player(session, vk_user_id: int) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


async def _create(session, player, province_ids, name="Realm"):
    return await NationService.create(
        session,
        owner_player_id=player.id,
        name=name,
        color_hex="#101010",
        province_ids=province_ids,
        config=CORE_CONFIG,
        **VALID_PROFILE,
    )


async def _nation(session, nation_id: str) -> Nation | None:
    return (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()


class TestNationCreatedHooks:
    async def test_hook_called_once_with_ids(self, test_db_session):
        calls: list[tuple[str, str]] = []

        async def hook(session, player_id, nation_id):
            calls.append((player_id, nation_id))

        register_nation_created_hook("test.hook", hook)
        player = await _player(test_db_session, 601)
        await make_land_province(test_db_session, id=1001)

        nation = await _create(test_db_session, player, [1001])

        assert calls == [(player.id, nation.id)]

    async def test_hook_sees_the_created_nation(self, test_db_session):
        """The hook runs after all writes: the nation row and the
        province claim are already readable (Spec 3.11)."""
        seen: list[tuple[str, int]] = []

        async def hook(session, player_id, nation_id):
            summary = await NationService.player_nation_summary(
                session, player_id
            )
            seen.append((summary.nation_id, summary.province_count))

        register_nation_created_hook("test.reader", hook)
        player = await _player(test_db_session, 602)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)

        nation = await _create(test_db_session, player, [1001, 1002])

        assert seen == [(nation.id, 2)]

    async def test_hooks_run_in_registration_order(self, test_db_session):
        calls: list[str] = []

        async def first(session, player_id, nation_id):
            calls.append("first")

        async def second(session, player_id, nation_id):
            calls.append("second")

        register_nation_created_hook("a", first)
        register_nation_created_hook("b", second)
        player = await _player(test_db_session, 603)
        await make_land_province(test_db_session, id=1001)

        await _create(test_db_session, player, [1001])

        assert calls == ["first", "second"]

    async def test_same_name_replaces(self, test_db_session):
        """Re-registering a name keeps one entry (idempotent startup)."""
        calls: list[str] = []

        async def old(session, player_id, nation_id):
            calls.append("old")

        async def new(session, player_id, nation_id):
            calls.append("new")

        register_nation_created_hook("dup", old)
        register_nation_created_hook("dup", new)

        assert list(get_nation_created_hooks()) == ["dup"]
        player = await _player(test_db_session, 604)
        await make_land_province(test_db_session, id=1001)

        await _create(test_db_session, player, [1001])

        assert calls == ["new"]

    async def test_failing_hook_isolated_and_logged(
        self, test_db_session, caplog
    ):
        """A raising hook loses only its own writes: the nation and the
        other hook's effects survive; one WARNING names hook + class."""
        calls: list[str] = []
        marker = Player(vk_user_id=999999)  # partial write of the hook

        async def boom(session, player_id, nation_id):
            calls.append("boom")
            session.add(marker)
            await session.flush()
            raise RuntimeError("hook exploded")

        async def after(session, player_id, nation_id):
            calls.append("after")

        register_nation_created_hook("test.boom", boom)
        register_nation_created_hook("test.after", after)
        player = await _player(test_db_session, 605)
        await make_land_province(test_db_session, id=1001)

        with caplog.at_level(logging.WARNING):
            nation = await _create(test_db_session, player, [1001])

        # The creation is intact and the next hook still ran.
        assert nation.id is not None
        assert calls == ["boom", "after"]
        assert await _nation(test_db_session, nation.id) is not None
        # ... while the failed hook's partial write is gone.
        assert (
            await test_db_session.execute(
                select(Player).where(Player.id == marker.id)
            )
        ).scalar_one_or_none() is None
        province = (
            await test_db_session.execute(
                select(Province).where(Province.id == 1001)
            )
        ).scalar_one()
        assert province.nation_id == nation.id
        # The WARNING carries the hook name and exception class only.
        assert "nation_created_hook_failed" in caplog.text
        assert "test.boom" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "hook exploded" not in caplog.text

    async def test_cancelled_error_not_swallowed(self, test_db_session):
        """BaseExceptions propagate — only Exception is isolated."""

        async def cancelled(session, player_id, nation_id):
            raise asyncio.CancelledError()

        register_nation_created_hook("test.cancelled", cancelled)
        player = await _player(test_db_session, 606)
        await make_land_province(test_db_session, id=1001)

        with pytest.raises(asyncio.CancelledError):
            await _create(test_db_session, player, [1001])

    async def test_no_hooks_behaves_as_before(self, test_db_session):
        assert get_nation_created_hooks() == {}
        player = await _player(test_db_session, 607)
        await make_land_province(test_db_session, id=1001)

        nation = await _create(test_db_session, player, [1001])

        assert nation.owner_player_id == player.id
        province = (
            await test_db_session.execute(
                select(Province).where(Province.id == 1001)
            )
        ).scalar_one()
        assert province.nation_id == nation.id
