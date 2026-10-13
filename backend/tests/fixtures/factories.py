"""
Polyfactory factories for 00_core models and module-02_bot row helpers.

Provides test data factories for Player, Nation, and Province models,
plus ``make_consent`` / ``make_outbox_row`` — function-style seeders for
the 02_bot tables, in the style of ``tests/fixtures/provinces.py``.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
    TickLog,
    TickLogStatus,
)
from modules._02_bot.models import BotConsent, BotOutbox
from tests.fixtures.profile import VALID_PROFILE


def utcnow():
    """Helper to get current UTC datetime."""
    return datetime.now(timezone.utc)


class PlayerFactory(SQLAlchemyFactory[Player]):
    """Factory for creating Player instances."""
    
    __model__ = Player
    
    id = lambda: str(uuid.uuid4())
    vk_user_id = 1234567890
    created_at = utcnow


class NationFactory(SQLAlchemyFactory[Nation]):
    """Factory for creating Nation instances."""
    
    __model__ = Nation
    
    id = lambda: str(uuid.uuid4())
    owner_player_id = None  # Set explicitly in tests
    name = "Test Nation"
    color_hex = "#FF0000"
    leader_name = VALID_PROFILE["leader_name"]
    leader_title = VALID_PROFILE["leader_title"]
    history_url = VALID_PROFILE["history_url"]
    created_at = utcnow
    __set_foreign_keys__ = False


class ProvinceFactory(SQLAlchemyFactory[Province]):
    """Factory for creating Province instances."""

    __model__ = Province

    # Default id is outside the removed placeholder range 1..100.
    id = 1001
    kind = "LAND"
    nation_id = None
    __set_foreign_keys__ = False


class GameClockFactory(SQLAlchemyFactory[GameClock]):
    """Factory for creating GameClock instances."""
    
    __model__ = GameClock
    
    id = 1
    current_turn = 0
    last_tick_at = None
    next_tick_at = utcnow


class ScheduledActionFactory(SQLAlchemyFactory[ScheduledAction]):
    """Factory for creating ScheduledAction instances."""
    
    __model__ = ScheduledAction
    
    id = lambda: str(uuid.uuid4())
    nation_id = None  # Set explicitly in tests
    module_slug = "test_module"
    action_type = "test_action"
    payload = {"test": "data"}
    turn_number = 1
    status = ScheduledActionStatus.PENDING
    created_at = utcnow
    applied_at = None
    __set_foreign_keys__ = False


class TickLogFactory(SQLAlchemyFactory[TickLog]):
    """Factory for creating TickLog instances."""
    
    __model__ = TickLog
    
    turn_number = 1
    started_at = utcnow
    finished_at = None
    status = TickLogStatus.RUNNING
    error_message = None


# ── Module 02_bot seeders (Spec Part 1.1) ─────────────────────────────

_event_key_seq = itertools.count()


async def make_consent(
    session: AsyncSession,
    player: Player,
    *,
    state: str = "ALLOWED",
    state_source: str = "INIT",
    state_changed_at: datetime | None = None,
    last_checked_at: datetime | None = None,
    last_plate_at: datetime | None = None,
    created_at: datetime | None = None,
) -> BotConsent:
    """Insert a ``bot_consents`` row for ``player`` and flush it."""
    now = utcnow()
    consent = BotConsent(
        player_id=player.id,
        state=state,
        state_source=state_source,
        state_changed_at=state_changed_at or now,
        last_checked_at=last_checked_at,
        last_plate_at=last_plate_at,
        created_at=created_at or now,
    )
    session.add(consent)
    await session.flush()
    return consent


async def make_outbox_row(
    session: AsyncSession,
    player: Player,
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
) -> BotOutbox:
    """Insert a ready ``bot_outbox`` row for ``player`` and flush it.

    Defaults describe a fresh queued row: ``PENDING``, zero attempts,
    a unique ``event_key`` (``uq_bot_outbox_dedup``) and ``expires_at``
    an hour in the future.
    """
    now = utcnow()
    row = BotOutbox(
        player_id=player.id,
        kind=kind,
        type_key=type_key,
        event_key=event_key or f"test:{next(_event_key_seq)}:{uuid.uuid4()}",
        priority=priority,
        counts_toward_cap=counts_toward_cap,
        payload=payload if payload is not None else {},
        status=status,
        drop_reason=drop_reason,
        created_at=created_at or now,
        not_before=not_before or now,
        expires_at=expires_at or (now + timedelta(hours=1)),
        next_attempt_at=next_attempt_at or not_before or now,
    )
    session.add(row)
    await session.flush()
    return row
