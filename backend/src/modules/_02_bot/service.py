"""
Public service API of module 02_bot (Spec Appendix A, 3.1).

``BotService.enqueue`` is the ONLY way other modules create
notifications: it runs inside the caller's transaction, never commits,
never touches the network, and never raises domain exceptions — every
inapplicable case returns an :class:`EnqueueResult` value instead
(INV-B1). A successful insert arms a one-shot ``after_commit`` listener
that rings the sender's bell; a rollback never rings it.

The registry functions of Spec 2.6 are re-exported here so producers
have a single import surface.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import event as sa_event
from sqlalchemy import delete, false, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService
from modules._02_bot import consent
from modules._02_bot.models import BotOutbox
from modules._02_bot.registry import (
    get_notification_type,
    register_deadline_audience,
    register_notification_type,
)
from modules._02_bot.settings import is_bot_active
from modules._02_bot.signal import request_wake
from modules._02_bot.startup import get_bot_config

logger = logging.getLogger(__name__)

__all__ = [
    "BotService",
    "EnqueueResult",
    "register_deadline_audience",
    "register_notification_type",
]


class EnqueueResult(str, Enum):
    QUEUED = "QUEUED"
    DUPLICATE = "DUPLICATE"  # то же событие уже в очереди
    SKIPPED_BOT_OFF = "SKIPPED_BOT_OFF"
    SKIPPED_TYPE_DISABLED = "SKIPPED_TYPE_DISABLED"
    SKIPPED_NO_CONSENT = "SKIPPED_NO_CONSENT"
    SKIPPED_NO_NATION = "SKIPPED_NO_NATION"
    REJECTED_INVALID = "REJECTED_INVALID"  # ошибка продюсера


class BotService:
    """The module's public API for producers (Spec Appendix A)."""

    @staticmethod
    async def enqueue(
        session: AsyncSession,
        *,
        type_key: str,
        player_id: str,
        event_key: str,
        variables: Mapping[str, str | int],
        event_at: datetime | None = None,
        now: datetime | None = None,
    ) -> EnqueueResult:
        """
        Queue one notification event for a player (Spec 3.1).

        Runs inside the caller's transaction and never commits; the
        duplicate guard is ``uq_bot_outbox_dedup`` behind a SAVEPOINT.
        ``event_at`` backdates the event (digest t0 = last_tick_at):
        ``expires_at`` counts from it, so a stale event inserts an
        already-expired row instead of resurrecting. ``now`` only
        exists for tests.
        """
        if not is_bot_active():
            return EnqueueResult.SKIPPED_BOT_OFF

        registered = get_notification_type(type_key)
        if registered is None:
            logger.error(
                "enqueue rejected: type_key '%s' is not registered",
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID
        if frozenset(variables) != registered:
            logger.error(
                "enqueue rejected: variables for '%s' differ from the "
                "registered set: got %s, expected %s",
                type_key,
                sorted(variables),
                sorted(registered),
            )
            return EnqueueResult.REJECTED_INVALID
        bad_values = sorted(
            key
            for key, value in variables.items()
            if isinstance(value, bool)
            or not isinstance(value, (str, int))
        )
        if bad_values:
            logger.error(
                "enqueue rejected: variables %s of '%s' are not str|int",
                bad_values,
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID

        type_cfg = get_bot_config().types.get(type_key)
        if type_cfg is None:
            # Unreachable past startup validation; stay defensive.
            logger.error(
                "enqueue rejected: type_key '%s' is absent from "
                "configs/02_bot.yaml",
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID
        if not type_cfg.enabled:
            return EnqueueResult.SKIPPED_TYPE_DISABLED

        nation = await NationService.player_nation_summary(
            session, player_id
        )
        if nation is None:
            return EnqueueResult.SKIPPED_NO_NATION

        if type_cfg.requires_consent and not await consent.is_allowed(
            session, player_id
        ):
            return EnqueueResult.SKIPPED_NO_CONSENT

        t = now if now is not None else datetime.now(timezone.utc)
        t0 = event_at if event_at is not None else t
        not_before = t + timedelta(seconds=type_cfg.hold_seconds)
        row = BotOutbox(
            player_id=player_id,
            kind="NOTIFICATION",
            type_key=type_key,
            event_key=event_key,
            priority=type_cfg.priority,
            counts_toward_cap=type_cfg.counts_toward_cap,
            payload=dict(variables),
            status="PENDING",
            attempts=0,
            created_at=t,
            not_before=not_before,
            next_attempt_at=not_before,
            expires_at=t0 + timedelta(minutes=type_cfg.ttl_minutes),
        )
        # SQLite drivers open the connection-level transaction lazily
        # on the first DML; a SAVEPOINT issued while the driver is still
        # in autocommit would escape the caller's transaction (its
        # RELEASE commits). Force the transaction open with a no-op
        # DELETE so the savepoint below really nests inside the
        # caller's transaction (INV-B1: no commits). SQLite-only:
        # PostgreSQL opens its transaction eagerly, and the extra
        # statement would be a needless round trip there.
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(BotOutbox).where(false()))
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            # The savepoint was rolled back; only the dedup unique maps
            # to DUPLICATE — anything else (FK, CHECK) propagates.
            existing = (
                await session.execute(
                    select(BotOutbox.id).where(
                        BotOutbox.player_id == player_id,
                        BotOutbox.type_key == type_key,
                        BotOutbox.event_key == event_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return EnqueueResult.DUPLICATE
            raise

        # Arm the wake bell for THIS transaction only: the paired
        # after_rollback hook disarms it if the caller's transaction is
        # rolled back, so the bell never rings for a vanished row.
        sync = session.sync_session

        def _wake(_s) -> None:
            sa_event.remove(sync, "after_rollback", _disarm)
            request_wake()

        def _disarm(_s) -> None:
            sa_event.remove(sync, "after_commit", _wake)

        sa_event.listen(sync, "after_commit", _wake, once=True)
        sa_event.listen(sync, "after_rollback", _disarm, once=True)
        return EnqueueResult.QUEUED
