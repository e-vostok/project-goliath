"""
Player stat columns and ``nations.created_turn`` (Spec 03_registry 1.2,
1.4 — module 03_registry Issue 1).

Real in-memory database, no mocks: a new player gets the scale defaults;
the named CHECKs reject out-of-scale values; ``NationService.create``
stamps the transaction's current turn and ``update`` never rewrites it
(INV-R9).
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock, Player
from modules._00_core.service import NationService, PlayerService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import (
    STARTING_GROUP,
    make_starting_group,
)

_vk_seq = itertools.count(42420001)


@pytest.mark.asyncio
async def test_new_player_defaults_and_scale_bounds(test_db_session):
    """Defaults land on insert; ck_players_level_min and
    ck_players_judge_rating_range reject out-of-scale values."""
    player = await PlayerService.get_or_create(
        test_db_session, vk_user_id=next(_vk_seq)
    )
    assert player.level == 1
    assert player.judge_rating == 0

    for bad_field in ({"level": 0}, {"judge_rating": 101}):
        with pytest.raises(IntegrityError):
            async with test_db_session.begin_nested():
                test_db_session.add(
                    Player(vk_user_id=next(_vk_seq), **bad_field)
                )
                await test_db_session.flush()


@pytest.mark.asyncio
async def test_created_turn_stamped_on_create_and_immutable(
    test_db_session,
):
    """create() writes game_clock.current_turn; update() leaves it."""
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    test_db_session.add(
        GameClock(
            id=1,
            current_turn=7,
            next_tick_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.flush()
    player = await PlayerService.get_or_create(
        test_db_session, vk_user_id=next(_vk_seq)
    )
    await make_starting_group(test_db_session)

    nation = await NationService.create(
        test_db_session,
        owner_player_id=player.id,
        name="Turn Nation",
        color_hex="#0A0B0C",
        province_ids=list(STARTING_GROUP),
        config=config,
        **VALID_PROFILE,
    )
    assert nation.created_turn == 7

    updated = await NationService.update(
        test_db_session,
        nation.id,
        name="Renamed Nation",
        config=config,
    )
    assert updated.created_turn == 7
