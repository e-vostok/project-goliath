"""
Dialog handler of module 02_bot (Spec 3.9) — the ``message_*`` events.

The handler never calls VK: it only writes rows — the consent FSM
(``message_allow``/``message_deny``) and ``REPLY`` outbox rows
(``message_new``). Replies are delivered by the sender within seconds;
no consent is needed for them (V7).

Player message text is read only to match it against the button labels
and is never stored or logged (INV-B12).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.service import (
    GameClockService,
    NationService,
    PlayerService,
)
from modules._00_core.tick_schedule import format_game_time
from modules._02_bot import consent as consent_mod
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.events import CallbackEvent, MessageNew
from modules._02_bot.models import BotConsent, BotVkEvent
from modules._02_bot.service import BotService

logger = logging.getLogger(__name__)

DialogCommand = Literal["start", "status", "help"]


async def handle_event(
    session: AsyncSession,
    config: BotConfig,
    event: CallbackEvent,
    event_id: str,
    now: datetime,
) -> None:
    """
    Spec 3.9 dispatch inside the caller's transaction (the journal row
    is already in it — nothing is committed here).
    """
    if event.event_type in ("message_allow", "message_deny"):
        # vk_user_id is guaranteed int by the parser for these types.
        player = await PlayerService.get_or_create(
            session, event.vk_user_id
        )
        await consent_mod.apply_consent_signal(
            session,
            player.id,
            "ALLOWED" if event.event_type == "message_allow" else "DENIED",
            "VK_EVENT",
            now=now,
        )
        return
    if event.event_type == "message_new" and event.message is not None:
        await _handle_message_new(
            session, config, event.message, event_id, now
        )


async def _handle_message_new(
    session: AsyncSession,
    config: BotConfig,
    message: MessageNew,
    event_id: str,
    now: datetime,
) -> None:
    """Spec 3.9 ``message_new``: ignore rules, command, reply row."""
    # Step 1 — ignore: no positive from_id, outgoing, or a chat
    # (peer_id != from_id). Journal row only, nothing else happens.
    if (
        message.from_id is None
        or message.from_id <= 0
        or message.out == 1
        or message.peer_id != message.from_id
    ):
        return

    player = await PlayerService.get_or_create(session, message.from_id)
    await consent_mod.get_or_create_consent(session, player.id, now=now)

    is_first_contact = await _is_first_contact(
        session, message.from_id, event_id
    )
    command = _command(message, config)

    # Step 4 — the reply table of Spec 3.9.
    if command == "start" or is_first_contact:
        nation = await NationService.player_nation_summary(
            session, player.id
        )
        if nation is None:
            await _reply(
                session, player.id, "start_guest", {}, "AUTO",
                event_id, now,
            )
        else:
            await _reply(
                session, player.id, "start_member",
                {"nation_name": nation.name}, "AUTO", event_id, now,
            )
        return

    if command == "status":
        nation = await NationService.player_nation_summary(
            session, player.id
        )
        if nation is None:
            await _reply(
                session, player.id, "start_guest", {}, "AUTO",
                event_id, now,
            )
        else:
            variables = await _status_variables(session, nation)
            await _reply(
                session, player.id, "status", variables, "AUTO",
                event_id, now,
            )
        return

    if command == "help":
        await _reply(
            session, player.id, "help", {}, "HELP", event_id, now,
        )
        return

    # Free text: the plate at most once per plate_cooldown_minutes.
    # The conditional UPDATE is the race-safe gate — only the event
    # that moves last_plate_at sends the plate.
    cooldown = timedelta(minutes=config.dialog.plate_cooldown_minutes)
    result = await session.execute(
        update(BotConsent)
        .where(
            BotConsent.player_id == player.id,
            or_(
                BotConsent.last_plate_at.is_(None),
                BotConsent.last_plate_at <= now - cooldown,
            ),
        )
        .values(last_plate_at=now)
    )
    if result.rowcount == 1:
        await _reply(
            session, player.id, "plate", {}, "AUTO", event_id, now,
        )


async def _is_first_contact(
    session: AsyncSession, vk_user_id: int, event_id: str
) -> bool:
    """No earlier ``message_new`` from this vk_user_id in the journal —
    the current event's own row is excluded by event_id (Spec 3.9)."""
    earlier = (
        await session.execute(
            select(BotVkEvent.id)
            .where(
                BotVkEvent.event_type == "message_new",
                BotVkEvent.vk_user_id == vk_user_id,
                BotVkEvent.event_id != event_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return earlier is None


def _command(message: MessageNew, config: BotConfig) -> DialogCommand | None:
    """
    The command of a ``message_new`` (Spec 3.9 step 3): a recognised
    payload dict wins; with no payload the label text is matched
    case/space-insensitively; anything else is free text (None). The
    ``register_nation`` label is deliberately not matched as text.
    """
    if message.payload is not None:
        try:
            payload = json.loads(message.payload)
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("command") == "start":
            return "start"
        cmd = payload.get("cmd")
        if cmd == "status":
            return "status"
        if cmd == "help":
            return "help"
        return None
    text = message.text.strip().casefold()
    labels = config.dialog.labels
    if text == labels.status.casefold():
        return "status"
    if text == labels.help.casefold():
        return "help"
    return None


async def _status_variables(
    session: AsyncSession, nation
) -> dict[str, str | int]:
    """
    The seven ``status`` template variables, computed at handling time —
    the same values the digest watcher builds for ``TICK_DIGEST`` plus
    the leader fields (``turn``/``game_date``/``next_tick_time`` come
    from ``game_clock`` through the same helpers).
    """
    core_config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    snapshot = await GameClockService.snapshot(session)
    turn = snapshot.current_turn if snapshot is not None else 0
    next_tick_time = (
        format_game_time(
            snapshot.next_tick_at, core_config.tick.tick_timezone
        )
        if snapshot is not None
        else None
    ) or "—"
    return {
        "nation_name": nation.name,
        "leader_title": nation.leader_title or "—",
        "leader_name": nation.leader_name or "—",
        "province_count": nation.province_count,
        "turn": turn,
        "game_date": compute_game_date(turn, core_config).isoformat(),
        "next_tick_time": next_tick_time,
    }


async def _reply(
    session: AsyncSession,
    player_id: str,
    template: str,
    variables: dict[str, str | int],
    keyboard: str,
    event_id: str,
    now: datetime,
) -> None:
    """Insert the REPLY outbox row for this event (Spec 3.9 step 5)."""
    await BotService.enqueue_reply(
        session,
        player_id=player_id,
        template=template,
        variables=variables,
        keyboard=keyboard,
        event_key=f"vk:{event_id}",
        now=now,
    )
