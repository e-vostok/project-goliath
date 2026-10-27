"""
Built-in table sources of module 03_registry (Spec 3.2, 3.3, Appendix A).

``players`` and ``nations`` read only the public functions of 00_core
(INV-R1) plus the module's own ``registry_vk_profiles`` table (read-only;
``profile_worker.py`` owns the writes). Every row is a
``RegistryRow`` whose key carries no ``vk_user_id`` and no player uuid
(INV-R2): ``p<number>`` for players, the nation id for nations.

Both ``load`` functions are a handful of flat queries — the player
list, the stored numbers and one ``registry_vk_profiles`` fetch — so
the query count does not grow with the number of players.

``load_player`` (Spec 5.6) returns the single ``players`` row addressed
by the Registry number — the very cells ``_player_row`` builds for the
table, so the player route and the table can never disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.calendar import compute_game_date, format_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.service import (
    NationService,
    PlayerRegistryRow,
    PlayerService,
)
from modules._03_registry.cells import (
    cell_date,
    cell_nation,
    cell_person,
)
from modules._03_registry.config_schema import RegistryConfig
from modules._03_registry.dates import real_date_parts
from modules._03_registry.errors import RegistryPlayerNotFoundError
from modules._03_registry.models import RegistryVkProfile
from modules._03_registry.profile_worker import aware_utc, request_wake
from modules._03_registry.registry import RegistryRow, register_table_source
from modules._03_registry.service import ensure_player_numbers

# The value keys each source promises (Spec 3.2, 3.3) — a config column's
# ``source`` must name one of these (checked at startup, Spec 2.5).
PLAYERS_PROVIDES = frozenset(
    {"number", "player", "joined", "level", "judge_rating", "nation"}
)
NATIONS_PROVIDES = frozenset({"number", "nation", "formed", "provinces"})


async def load_players(session: AsyncSession) -> list[RegistryRow]:
    """
    The ``players`` source (Spec 3.2).

    ``number`` is the player's permanent Registry number, issued once
    by ``ensure_player_numbers`` and stored in
    ``registry_player_numbers`` — it survives the deletion of other
    players (D2, 0.11.0 unit 11). Rows keep their (created_at, id)
    order of ``PlayerService.list_for_registry``, so the numbers of a
    table can skip the freed ones. The person name comes from the
    saved VK profile: ``"{first} {last}"`` stripped, or the configured
    fallback when it is empty or the profile row is absent; the avatar
    shows only for an ``OK`` profile.
    """
    # Local import: sources.py is imported by startup.py, so a top-level
    # import of the config holder would be a cycle (same pattern as
    # start_runtime_if_ready -> BotRuntime in 02_bot).
    from modules._03_registry.startup import (
        get_core_config,
        get_registry_config,
    )

    registry_config = get_registry_config()
    core_config = get_core_config()

    numbers = await ensure_player_numbers(session)
    rows = await PlayerService.list_for_registry(session)
    player_ids = [row.player_id for row in rows]
    profiles: dict[str, RegistryVkProfile] = {}
    if player_ids:
        result = await session.execute(
            select(RegistryVkProfile).where(RegistryVkProfile.player_id.in_(player_ids))
        )
        profiles = {p.player_id: p for p in result.scalars().all()}

    # Spec 2.4 wake-up: a player without a profile row or with a due
    # retry rings the background worker's bell. Rows with a deferred
    # retry (next_attempt_at in the future) never do — an unreachable
    # VK adds no load from table opens. A plain function call: a no-op
    # while the worker is not running.
    now = datetime.now(UTC)
    if any(
        (profile := profiles.get(row.player_id)) is None
        or aware_utc(profile.next_attempt_at) <= now
        for row in rows
    ):
        request_wake()

    return [
        _player_row(
            row,
            profiles.get(row.player_id),
            numbers[row.player_id],
            registry_config,
            core_config,
        )
        for row in rows
    ]


def _player_row(
    row: PlayerRegistryRow,
    profile: RegistryVkProfile | None,
    number: int,
    registry_config: RegistryConfig,
    core_config: CoreConfig,
) -> RegistryRow:
    """
    One ``players``-table row (Spec 3.2) — the cells shared by
    ``load_players`` and ``load_player`` so the table and the player
    route can never disagree. ``number`` is the stored permanent
    number; the key ``p<number>`` carries no ``vk_user_id`` and no
    uuid (INV-R2).
    """
    name = ""
    avatar_url: str | None = None
    if profile is not None:
        name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
        if profile.status == "OK":
            avatar_url = profile.photo_url
    is_fallback = name == ""
    if is_fallback:
        name = registry_config.profiles.fallback_name_template.format(number=number)
    joined_text, joined_key = real_date_parts(
        row.created_at, core_config.tick.tick_timezone
    )
    return RegistryRow(
        key=f"p{number}",
        cells={
            "number": number,
            "player": cell_person(name, avatar_url, is_fallback),
            "joined": cell_date(joined_text, joined_key),
            "level": row.level,
            "judge_rating": row.judge_rating,
            "nation": (
                cell_nation(
                    row.nation_short_name,
                    row.nation_color,
                    nation_id=row.nation_id,
                )
                if row.nation_id is not None
                else None
            ),
        },
    )


async def load_player(session: AsyncSession, number: int) -> RegistryRow:
    """
    The single ``players`` row addressed by the Registry number
    (Spec 5.6) — the very ``_player_row`` the table shows for
    ``p<number>``.

    The address is the permanent stored number (0.11.0 unit 11), not a
    list position: ``ensure_player_numbers`` runs first, then the row
    whose stored number is ``number`` is picked out of
    ``PlayerService.list_for_registry`` (players are few — no separate
    core method). A number nobody holds — never issued, or freed by a
    deleted player — raises ``RegistryPlayerNotFoundError``. The
    wake-up rule is the table's Spec 2.4 one, narrowed to this one
    player: no profile row or a due retry rings the worker's bell.
    """
    # Local imports, same cycle guard as in load_players.
    from modules._03_registry.startup import (
        get_core_config,
        get_registry_config,
    )

    numbers = await ensure_player_numbers(session)
    rows = await PlayerService.list_for_registry(session)
    row = next(
        (r for r in rows if numbers.get(r.player_id) == number), None
    )
    if row is None:
        raise RegistryPlayerNotFoundError(number)

    result = await session.execute(
        select(RegistryVkProfile).where(RegistryVkProfile.player_id == row.player_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None or aware_utc(profile.next_attempt_at) <= datetime.now(UTC):
        request_wake()

    return _player_row(
        row, profile, number, get_registry_config(), get_core_config()
    )


async def load_nations(session: AsyncSession) -> list[RegistryRow]:
    """
    The ``nations`` source (Spec 3.3).

    ``number`` is the 1-based position in the (created_turn, created_at,
    id) order of ``NationService.list_for_registry`` — a nation's place
    among the existing ones (D2). ``formed`` is the game-calendar date of
    ``created_turn``; the row key is the nation id. ``nation`` is the
    very cell the players table gives for the owner nation — short name
    (mandatory since migration 0012 — no full-name fallback) and
    colour, with no flag image until the upload lands (INV-16) — so the
    ``select_or_contains``
    options match the ``nation`` cells of the players and orders
    tables exactly (Spec 3.7).
    """
    # Local import, same cycle guard as in load_players.
    from modules._03_registry.startup import get_core_config

    core_config = get_core_config()
    rows = await NationService.list_for_registry(session)

    out: list[RegistryRow] = []
    for number, row in enumerate(rows, start=1):
        out.append(
            RegistryRow(
                key=row.nation_id,
                cells={
                    "number": number,
                    "nation": cell_nation(
                        row.short_name,
                        row.color_hex,
                        nation_id=row.nation_id,
                    ),
                    "formed": cell_date(
                        format_game_date(
                            compute_game_date(row.created_turn, core_config),
                            core_config,
                        ),
                        row.created_turn,
                    ),
                    "provinces": row.province_count,
                },
            )
        )
    return out


def register_builtin_sources() -> None:
    """Register the module's two built-in sources (Spec 2.5 step 2)."""
    register_table_source("players", PLAYERS_PROVIDES, load_players)
    register_table_source("nations", NATIONS_PROVIDES, load_nations)
