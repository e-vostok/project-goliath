"""
Admin-panel hooks for module 00_core.

00_core owns the players/nations/provinces/scheduled_actions/game_clock/
tick_log tables, so its admin state view and reset live here in the module
package and are exposed to the panel through AdminRegistry — one
registration call per hook, from the app lifespan.

register_admin_hooks() is idempotent: the lifespan runs on every app boot
(including repeated LifespanManager boots in tests), so re-registration
must not raise.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    TickLog,
)
from modules._00_core.tick_schedule import format_game_time, next_tick_after

MODULE_SLUG = "00_core"
LIST_CAP = 200


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def admin_state_view(session: AsyncSession) -> dict:
    """
    Read-only JSON snapshot of the 00_core world for the admin panel.

    Lists are ordered by created_at then id and capped at LIST_CAP rows;
    *_total plus `truncated` flag report what the cap hides. All datetimes
    are 'YYYY-MM-DD HH:MM:SS' display strings in tick_timezone (storage
    stays UTC; this is presentation only).
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    clock_result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    clock = clock_result.scalar_one_or_none()

    players_total = await _count(session, Player)
    nations_total = await _count(session, Nation)
    provinces_total = await _count(session, Province)
    owned_result = await session.execute(
        select(func.count())
        .select_from(Province)
        .where(Province.nation_id.is_not(None))
    )
    provinces_owned = owned_result.scalar_one()

    players_result = await session.execute(
        select(Player)
        .order_by(Player.created_at, Player.id)
        .limit(LIST_CAP)
    )
    players = list(players_result.scalars().all())

    nation_by_owner_result = await session.execute(
        select(Nation.owner_player_id, Nation.id)
    )
    nation_id_by_owner = dict(nation_by_owner_result.all())

    nations_result = await session.execute(
        select(Nation)
        .order_by(Nation.created_at, Nation.id)
        .limit(LIST_CAP)
    )
    nations = list(nations_result.scalars().all())

    nation_ids = [nation.id for nation in nations]
    provinces_by_nation: dict[str, list[int]] = {nid: [] for nid in nation_ids}
    if nation_ids:
        provinces_result = await session.execute(
            select(Province.id, Province.nation_id)
            .where(Province.nation_id.in_(nation_ids))
            .order_by(Province.id)
        )
        for province_id, nation_id in provinces_result.all():
            provinces_by_nation[nation_id].append(province_id)

    return {
        "clock": (
            None
            if clock is None
            else {
                "current_turn": clock.current_turn,
                "last_tick_at": format_game_time(
                    clock.last_tick_at, config.tick.tick_timezone
                ),
                "next_tick_at": format_game_time(
                    clock.next_tick_at, config.tick.tick_timezone
                ),
                "tick_timezone": config.tick.tick_timezone,
            }
        ),
        "counts": {
            "players": players_total,
            "nations": nations_total,
            "provinces_total": provinces_total,
            "provinces_owned": provinces_owned,
        },
        "players_total": players_total,
        "nations_total": nations_total,
        "truncated": players_total > len(players)
        or nations_total > len(nations),
        "players_truncated": players_total > len(players),
        "players": [
            {
                "id": player.id,
                "vk_user_id": player.vk_user_id,
                "created_at": format_game_time(
                    player.created_at, config.tick.tick_timezone
                ),
                "nation_id": nation_id_by_owner.get(player.id),
            }
            for player in players
        ],
        "nations_truncated": nations_total > len(nations),
        "nations": [
            {
                "id": nation.id,
                "name": nation.name,
                "color_hex": nation.color_hex,
                "owner_player_id": nation.owner_player_id,
                "province_ids": provinces_by_nation[nation.id],
                "created_at": format_game_time(
                    nation.created_at, config.tick.tick_timezone
                ),
            }
            for nation in nations
        ],
    }


async def admin_reset(session: AsyncSession) -> None:
    """
    Wipe the 00_core world back to a fresh game.

    Clears scheduled_actions, frees every province, deletes all nations
    and the whole tick_log journal, and rewinds game_clock to turn 0
    (inserting the singleton row if it is somehow absent). players are
    kept on purpose — accounts survive a world reset.

    The caller owns the transaction: this hook never commits.
    """
    await session.execute(delete(ScheduledAction))
    await session.execute(update(Province).values(nation_id=None))
    await session.execute(delete(Nation))
    await session.execute(delete(TickLog))

    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    now = datetime.now(timezone.utc)
    next_tick_at = next_tick_after(
        now, config.tick.tick_time, config.tick.tick_timezone
    )

    clock_result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    clock = clock_result.scalar_one_or_none()
    if clock is None:
        session.add(
            GameClock(
                id=1,
                current_turn=0,
                last_tick_at=None,
                next_tick_at=next_tick_at,
            )
        )
    else:
        clock.current_turn = 0
        clock.last_tick_at = None
        clock.next_tick_at = next_tick_at

    await session.flush()


def register_admin_hooks() -> None:
    """
    Register the 00_core admin hooks with AdminRegistry.

    Safe to call on every app boot: skips registration when the slug is
    already present instead of raising the registry's duplicate ValueError.
    """
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, admin_state_view)
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, admin_reset)
