"""
The ``before_all`` registration-check stage (Spec 02_bot B9 / 3.10).

``STAGE_BEFORE_ALL`` checks receive ``(session, player_id)`` — unlike
the ``after_*`` stages, which see the loaded provinces — and run first
in ``NationService.create``, before any write. A raising check leaves
no nation, no province claim and no listener traces.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import CoreDomainError
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    STAGE_BEFORE_ALL,
    clear_registration_checks,
    register_registration_check,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import Nation, Player, Province
from modules._00_core.service import NationService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture(autouse=True)
def _isolated_checks():
    """Clear the registry for the test, then restore what was there."""
    saved = snapshot_extension_points()
    clear_registration_checks()
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


class TestBeforeAllStage:
    async def test_receives_player_id_and_runs_first(
        self, test_db_session
    ):
        calls: list[tuple[str, object]] = []

        async def before_all(session, player_id):
            calls.append(("before_all", player_id))

        async def after_free(session, provinces):
            calls.append(("after_free", [p.id for p in provinces]))

        async def after_count(session, provinces):
            calls.append(("after_count", [p.id for p in provinces]))

        register_registration_check(
            STAGE_AFTER_COUNT, "test.count", after_count
        )
        register_registration_check(
            STAGE_BEFORE_ALL, "test.player", before_all
        )
        register_registration_check(
            STAGE_AFTER_FREE, "test.free", after_free
        )

        player = await _player(test_db_session, 501)
        await make_land_province(test_db_session, id=1001)

        nation = await _create(test_db_session, player, [1001])

        assert nation.id is not None
        # before_all ran first and saw the player id, not provinces.
        assert calls == [
            ("before_all", player.id),
            ("after_free", [1001]),
            ("after_count", [1001]),
        ]

    async def test_raising_check_persists_nothing(self, test_db_session):
        class _Reject(CoreDomainError):
            def __init__(self):
                super().__init__("rejected", "TEST_REJECT")

        seen = {"after_free_ran": False}

        async def before_all(session, player_id):
            raise _Reject()

        async def after_free(session, provinces):
            seen["after_free_ran"] = True

        register_registration_check(
            STAGE_BEFORE_ALL, "test.reject", before_all
        )
        register_registration_check(
            STAGE_AFTER_FREE, "test.free", after_free
        )

        player = await _player(test_db_session, 502)
        await make_land_province(test_db_session, id=1001)

        with pytest.raises(_Reject):
            await _create(test_db_session, player, [1001])

        assert seen["after_free_ran"] is False
        assert (
            await test_db_session.execute(select(Nation.id))
        ).scalar_one_or_none() is None
        province = (
            await test_db_session.execute(
                select(Province).where(Province.id == 1001)
            )
        ).scalar_one()
        assert province.nation_id is None

    async def test_no_checks_behaves_as_before(self, test_db_session):
        player = await _player(test_db_session, 503)
        await make_land_province(test_db_session, id=1001)

        nation = await _create(test_db_session, player, [1001])

        assert nation.owner_player_id == player.id
        province = (
            await test_db_session.execute(
                select(Province).where(Province.id == 1001)
            )
        ).scalar_one()
        assert province.nation_id == nation.id
