"""
Polyfactory factories for 00_core models and module-02_bot row helpers.

Provides test data factories for Player, Nation, and Province models,
plus ``make_consent`` / ``make_outbox_row`` — function-style seeders for
the 02_bot tables, in the style of ``tests/fixtures/provinces.py``.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta

from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select
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
from modules._00_core.player_stats import (
    JUDGE_RATING_DEFAULT,
    LEVEL_DEFAULT,
)
from modules._02_bot.models import BotConsent, BotOutbox
from modules._03_registry.models import RegistryVkProfile
from modules._04_orders.models import Order
from tests.fixtures.profile import VALID_PROFILE


def utcnow():
    """Helper to get current UTC datetime."""
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _new_short_name() -> str:
    return f"N{uuid.uuid4().hex[:15]}"


class PlayerFactory(SQLAlchemyFactory[Player]):
    """Factory for creating Player instances."""

    __model__ = Player

    id = _new_uuid
    vk_user_id = 1234567890
    created_at = utcnow
    level = LEVEL_DEFAULT
    judge_rating = JUDGE_RATING_DEFAULT


class NationFactory(SQLAlchemyFactory[Nation]):
    """Factory for creating Nation instances."""

    __model__ = Nation

    id = _new_uuid
    owner_player_id = None  # Set explicitly in tests
    name = "Test Nation"
    color_hex = "#FF0000"
    leader_name = VALID_PROFILE["leader_name"]
    leader_title = VALID_PROFILE["leader_title"]
    history_url = VALID_PROFILE["history_url"]
    # UNIQUE (INV-11): each built nation gets a fresh short name.
    short_name = _new_short_name
    gender = VALID_PROFILE["gender"]
    succession_type = VALID_PROFILE["succession_type"]
    capital_name = VALID_PROFILE["capital_name"]
    created_at = utcnow
    created_turn = 0
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

    id = _new_uuid
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


async def make_vk_profile(
    session: AsyncSession,
    player: Player,
    *,
    status: str = "OK",
    first_name: str | None = "Иван",
    last_name: str | None = "Петров",
    photo_url: str | None = None,
    fetched_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> RegistryVkProfile:
    """Insert a ``registry_vk_profiles`` row for ``player`` and flush it."""
    now = utcnow()
    row = RegistryVkProfile(
        player_id=player.id,
        status=status,
        first_name=first_name,
        last_name=last_name,
        photo_url=photo_url,
        fetched_at=fetched_at or now,
        next_attempt_at=next_attempt_at or now,
    )
    session.add(row)
    await session.flush()
    return row


# ── Module 04_orders seeders (Spec Part 1) ────────────────────────────


async def make_order(
    session: AsyncSession,
    author: Player,
    *,
    nation: Nation | None = None,
    number: int | None = None,
    client_request_id: str | None = None,
    nation_id: str | None = None,
    nation_name: str | None = None,
    nation_color: str | None = None,
    title: str = "Тестовый приказ",
    summary: str = "Краткая суть тестового приказа.",
    article_url: str = "https://vk.com/@test/order-article",
    submitted_at: datetime | None = None,
    judge: Player | None = None,
    distributed_at: datetime | None = None,
    deadline_at: datetime | None = None,
    reminder_at: datetime | None = None,
    reminder_sent_at: datetime | None = None,
    verdict_title: str | None = None,
    verdict_summary: str | None = None,
    verdict_url: str | None = None,
    verdict_effects: dict | None = None,
    verdict_at: datetime | None = None,
) -> Order:
    """Insert an ``orders`` row for ``author`` and flush it.

    Defaults describe a valid SUBMITTED order: no judge, the nation
    snapshot taken from ``nation`` (or synthetic values), a sequential
    public ``number`` and a unique ``client_request_id``. Passing
    ``judge`` fills the missing distribution timestamps with consistent
    values (``distributed_at`` = submission, deadline +72 h, reminder
    +54 h); passing ``verdict_at`` fills the missing verdict fields.
    Explicitly passed values always win — a halfway combination is kept
    as given so the CHECK groups can be exercised.
    """
    now = utcnow()
    submitted = submitted_at or now
    if judge is not None:
        distributed_at = distributed_at or submitted
        deadline_at = deadline_at or distributed_at + timedelta(hours=72)
        reminder_at = reminder_at or distributed_at + timedelta(hours=54)
    if verdict_at is not None:
        verdict_title = verdict_title if verdict_title is not None else title
        verdict_summary = verdict_summary if verdict_summary is not None else summary
        verdict_url = verdict_url if verdict_url is not None else article_url
    if number is None:
        # Spec 3.5: the public number is the next after the maximum.
        number = await session.scalar(
            sa_select(sa_func.coalesce(sa_func.max(Order.number), 0) + 1)
        )
    row = Order(
        number=number,
        author_player_id=author.id,
        client_request_id=client_request_id or str(uuid.uuid4()),
        nation_id=nation_id or (nation.id if nation else str(uuid.uuid4())),
        nation_name=nation_name or (nation.name if nation else "Test Nation"),
        nation_color=nation_color or (nation.color_hex if nation else "#FF0000"),
        title=title,
        summary=summary,
        article_url=article_url,
        submitted_at=submitted,
        judge_player_id=judge.id if judge is not None else None,
        distributed_at=distributed_at,
        deadline_at=deadline_at,
        reminder_at=reminder_at,
        reminder_sent_at=reminder_sent_at,
        verdict_title=verdict_title,
        verdict_summary=verdict_summary,
        verdict_url=verdict_url,
        verdict_effects=verdict_effects,
        verdict_at=verdict_at,
    )
    session.add(row)
    await session.flush()
    return row


# ── Module 02_bot seeders (Spec Part 1.1) ─────────────────────────────

_event_key_seq = itertools.count()


async def make_player(
    session: AsyncSession,
    *,
    vk_user_id: int | None = None,
    judge_rating: int | None = None,
    consent_state: str | None = None,
) -> Player:
    """Insert a ``players`` row and flush it.

    ``judge_rating`` overrides the registry rating default (the judge
    threshold tests need values both sides of ``judge.min_rating``);
    ``consent_state`` seeds the ``bot_consents`` row that decides the
    reachability of a nationless player (Spec 04_orders 3.2).
    """
    build_kwargs: dict = {"nations": []}
    if vk_user_id is not None:
        build_kwargs["vk_user_id"] = vk_user_id
    if judge_rating is not None:
        build_kwargs["judge_rating"] = judge_rating
    player = PlayerFactory.build(**build_kwargs)
    session.add(player)
    await session.flush()
    if consent_state is not None:
        await make_consent(session, player, state=consent_state)
    return player


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
