"""
Digest watcher of module 02_bot (Spec 3.8).

Every pass: read ``game_clock`` once, then in a single transaction

1. claim the turn with compare-and-swap ``UPDATE bot_state SET
   last_digest_turn = N WHERE last_digest_turn < N`` — zero rows
   touched means another process won (or the row is missing, which a
   seeding INSERT resolves the same way);
2. enqueue ``TICK_DIGEST`` (``event_key = turn:N``) for every player
   with a nation and consent ``ALLOWED``, ``event_at`` backdated to
   ``last_tick_at`` so a stale digest lands already expired;
3. enqueue ``DEADLINE_WARNING`` (``event_key = deadline:N``) when the
   type is enabled, at least one audience provider is registered, and
   ``now`` entered the ``deadline.offset_minutes`` window — once per
   turn, for the union of provider audiences.

Missed turns are never back-filled: ``last_digest_turn`` jumps to N.
A committed ``wake`` rings the sender's bell (Spec 3.1).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.service import GameClockService, NationService
from modules._00_core.tick_schedule import format_game_time
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.models import BotConsent, BotOutbox, BotState
from modules._02_bot.registry import get_deadline_audience_providers
from modules._02_bot.service import BotService
from modules._02_bot.signal import request_wake

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_DIGEST_TYPE = "TICK_DIGEST"
_DEADLINE_TYPE = "DEADLINE_WARNING"


async def digest_watcher_step(
    session_factory: SessionFactory,
    config: BotConfig,
    now: datetime | None = None,
) -> None:
    """One watcher pass (digest + deadline) in a single commit."""
    t = now if now is not None else datetime.now(timezone.utc)
    async with session_factory() as session:
        snapshot = await GameClockService.snapshot(session)
    if snapshot is None or snapshot.current_turn == 0:
        return
    turn = snapshot.current_turn

    core_config = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    )
    enqueued_any = False
    async with session_factory() as session:
        async with session.begin():
            if await _claim_turn(session, turn):
                await _enqueue_digests(
                    session, snapshot, core_config, turn
                )
                enqueued_any = True
            await _maybe_enqueue_deadline(
                session, snapshot, config, turn, t
            )
    if enqueued_any:
        request_wake()


async def _claim_turn(session: AsyncSession, turn: int) -> bool:
    """
    Compare-and-swap ``last_digest_turn`` to ``turn``; True when this
    process won. A missing singleton row (bare test schema) is seeded
    in a savepoint — a lost race on the insert also means 'not won'.
    """
    result = await session.execute(
        update(BotState)
        .where(BotState.id == 1, BotState.last_digest_turn < turn)
        .values(last_digest_turn=turn)
    )
    if result.rowcount > 0:
        return True
    existing = (
        await session.execute(
            select(BotState.id).where(BotState.id == 1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    try:
        async with session.begin_nested():
            session.add(BotState(id=1, last_digest_turn=turn))
    except IntegrityError:
        return False
    return True


async def _enqueue_digests(
    session: AsyncSession,
    snapshot,
    core_config: CoreConfig,
    turn: int,
) -> None:
    """One TICK_DIGEST row per (nation owner ∩ consent ALLOWED)."""
    player_ids = (
        await session.execute(
            select(BotConsent.player_id).where(
                BotConsent.state == "ALLOWED"
            )
        )
    ).scalars().all()
    game_date = compute_game_date(turn, core_config).isoformat()
    next_tick_time = format_game_time(
        snapshot.next_tick_at, core_config.tick.tick_timezone
    ) or "—"
    for player_id in player_ids:
        nation = await NationService.player_nation_summary(
            session, player_id
        )
        if nation is None:
            continue
        await BotService.enqueue(
            session,
            type_key=_DIGEST_TYPE,
            player_id=player_id,
            event_key=f"turn:{turn}",
            variables={
                "turn": turn,
                "game_date": game_date,
                "nation_name": nation.name,
                "province_count": nation.province_count,
                "next_tick_time": next_tick_time,
            },
            event_at=snapshot.last_tick_at,
        )


async def _maybe_enqueue_deadline(
    session: AsyncSession,
    snapshot,
    config: BotConfig,
    turn: int,
    now: datetime,
) -> None:
    """The once-per-turn DEADLINE_WARNING inside the offset window."""
    type_cfg = config.types.get(_DEADLINE_TYPE)
    providers = get_deadline_audience_providers()
    if (
        type_cfg is None
        or not type_cfg.enabled
        or not providers
        or snapshot.next_tick_at is None
    ):
        return
    next_tick_at = snapshot.next_tick_at
    if next_tick_at.tzinfo is None:
        next_tick_at = next_tick_at.replace(tzinfo=timezone.utc)
    offset = timedelta(minutes=config.deadline.offset_minutes)
    if now < next_tick_at - offset:
        return
    event_key = f"deadline:{turn}"
    already = (
        await session.execute(
            select(func.count())
            .select_from(BotOutbox)
            .where(
                BotOutbox.type_key == _DEADLINE_TYPE,
                BotOutbox.event_key == event_key,
            )
        )
    ).scalar_one()
    if already:
        return

    audience: set[str] = set()
    for provider in providers:
        audience |= await provider(session, turn)
    if not audience:
        return
    hours_left = max(
        1, math.ceil((next_tick_at - now).total_seconds() / 3600)
    )
    for player_id in audience:
        await BotService.enqueue(
            session,
            type_key=_DEADLINE_TYPE,
            player_id=player_id,
            event_key=event_key,
            variables={"hours_left": hours_left},
            event_at=next_tick_at - offset,
        )
