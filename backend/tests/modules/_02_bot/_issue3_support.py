"""
Shared helpers for the Issue-3 suite of 02_bot.

Seeding helpers (players, nations, consents, outbox rows with full
field control, bot_state) and a session factory over the test engine —
the runtime/sender steps open their own sessions, so tests work with
``session_factory(engine)`` rather than the single-session fixture.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules._00_core.models import Nation, Player
from modules._02_bot.models import BotConsent, BotOutbox, BotState
from tests.fixtures.profile import VALID_PROFILE

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


def make_session_factory(engine):
    """A ``get_session_context``-shaped factory over the test engine."""
    return async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def add_player(
    session: AsyncSession, vk_user_id: int | None = None
) -> Player:
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=vk_user_id or uuid.uuid4().int % 10**9,
        created_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


async def add_member(
    session: AsyncSession,
    *,
    consent: str | None = "ALLOWED",
    vk_user_id: int | None = None,
) -> Player:
    """A player with a nation and (optionally) a consent row."""
    player = await add_player(session, vk_user_id)
    session.add(
        Nation(
            id=str(uuid.uuid4()),
            owner_player_id=player.id,
            name=f"N-{player.id[:8]}",
            color_hex="#" + uuid.uuid4().hex[:6].upper(),
            leader_name=VALID_PROFILE["leader_name"],
            leader_title=VALID_PROFILE["leader_title"],
            history_url=VALID_PROFILE["history_url"],
            created_at=NOW,
        )
    )
    await session.flush()
    if consent is not None:
        await add_consent(session, player.id, state=consent)
    return player


async def add_consent(
    session: AsyncSession,
    player_id: str,
    *,
    state: str = "ALLOWED",
    created_at: datetime | None = None,
) -> BotConsent:
    row = BotConsent(
        player_id=player_id,
        state=state,
        state_source="INIT",
        state_changed_at=NOW,
        created_at=created_at or NOW,
    )
    session.add(row)
    await session.flush()
    return row


async def add_outbox(
    session: AsyncSession,
    player_id: str,
    *,
    type_key: str = "TICK_DIGEST",
    event_key: str | None = None,
    kind: str = "NOTIFICATION",
    priority: str = "normal",
    counts_toward_cap: bool = True,
    payload: dict | None = None,
    status: str = "PENDING",
    drop_reason: str | None = None,
    created_at: datetime | None = None,
    not_before: datetime | None = None,
    expires_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
    attempts: int = 0,
    lease_until: datetime | None = None,
    lease_token: str | None = None,
    group_id: str | None = None,
    random_id: int | None = None,
    render_mode: str | None = None,
    vk_message_id: int | None = None,
    sent_at: datetime | None = None,
    last_error_code: int | None = None,
) -> BotOutbox:
    """A bot_outbox row with every field controllable."""
    row = BotOutbox(
        player_id=player_id,
        kind=kind,
        type_key=type_key,
        event_key=event_key or f"k:{uuid.uuid4()}",
        priority=priority,
        counts_toward_cap=counts_toward_cap,
        payload=payload if payload is not None else {},
        status=status,
        drop_reason=drop_reason,
        created_at=created_at or NOW,
        not_before=not_before or NOW,
        expires_at=expires_at or NOW + timedelta(hours=1),
        next_attempt_at=next_attempt_at or not_before or NOW,
        attempts=attempts,
        lease_until=lease_until,
        lease_token=lease_token,
        group_id=group_id,
        random_id=random_id,
        render_mode=render_mode,
        vk_message_id=vk_message_id,
        sent_at=sent_at,
        last_error_code=last_error_code,
    )
    session.add(row)
    await session.flush()
    return row


async def add_bot_state(
    session: AsyncSession, last_digest_turn: int = 0
) -> BotState:
    row = BotState(id=1, last_digest_turn=last_digest_turn)
    session.add(row)
    await session.flush()
    return row


def reply_payload(
    template: str = "help",
    vars: dict | None = None,
    keyboard: str = "AUTO",
) -> dict:
    """A REPLY row payload in the Spec 3.9 shape."""
    return {"template": template, "vars": vars or {}, "keyboard": keyboard}
