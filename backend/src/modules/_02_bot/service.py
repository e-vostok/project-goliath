"""
Public service API of module 02_bot (Spec Appendix A, 3.1).

``BotService.enqueue`` is the ONLY way other modules create
notifications: it runs inside the caller's transaction, never commits,
never touches the network, and never raises domain exceptions — every
inapplicable case returns an :class:`EnqueueResult` value instead
(INV-B1). A successful insert arms a one-shot ``after_commit`` listener
that rings the sender's bell; a rollback never rings it.

``BotService.enqueue_reply`` is the module-internal counterpart used
only by the Callback dialog handler (Spec 3.9): it queues ``REPLY``
rows under the same transaction and dedup rules but skips the
notification registry and the nation/consent gates — replies owe
nothing to INV-B3 and need no consent (V7).

The registry functions of Spec 2.6 are re-exported here so producers
have a single import surface.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import and_, delete, false, or_, select, update
from sqlalchemy import event as sa_event
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
from modules._02_bot.render import (
    LINK_VARIABLE_SUFFIX,
    is_valid_link_value,
)
from modules._02_bot.settings import is_bot_active, read_bot_env
from modules._02_bot.signal import request_wake
from modules._02_bot.startup import get_bot_config

logger = logging.getLogger(__name__)

__all__ = [
    "BotService",
    "EnqueueResult",
    "register_deadline_audience",
    "register_notification_type",
]


class EnqueueResult(StrEnum):
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
            if isinstance(value, bool) or not isinstance(value, (str, int))
        )
        if bad_values:
            logger.error(
                "enqueue rejected: variables %s of '%s' are not str|int",
                bad_values,
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID
        # ``*_link`` variables carry URLs (Spec 04_orders, Appendix B2):
        # https only, host from dialog.help.allowed_hosts, <= 300 chars.
        bad_links = sorted(
            key
            for key, value in variables.items()
            if key.endswith(LINK_VARIABLE_SUFFIX)
            and not is_valid_link_value(
                value, get_bot_config().dialog.help.allowed_hosts
            )
        )
        if bad_links:
            logger.error(
                "enqueue rejected: link variables %s of '%s' fail the URL rules",
                bad_links,
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID

        type_cfg = get_bot_config().types.get(type_key)
        if type_cfg is None:
            # Unreachable past startup validation; stay defensive.
            logger.error(
                "enqueue rejected: type_key '%s' is absent from configs/02_bot.yaml",
                type_key,
            )
            return EnqueueResult.REJECTED_INVALID
        if not type_cfg.enabled:
            return EnqueueResult.SKIPPED_TYPE_DISABLED

        if type_cfg.requires_nation:
            nation = await NationService.player_nation_summary(session, player_id)
            if nation is None:
                return EnqueueResult.SKIPPED_NO_NATION

        if type_cfg.requires_consent and not await consent.is_allowed(
            session, player_id
        ):
            return EnqueueResult.SKIPPED_NO_CONSENT

        t = now if now is not None else datetime.now(UTC)
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

        _arm_wake(session)
        return EnqueueResult.QUEUED

    @staticmethod
    async def consented_player_ids(
        session: AsyncSession, player_ids: Iterable[str]
    ) -> set[str]:
        """
        The subset of ``player_ids`` whose consent state is ``ALLOWED``
        — one batched read for producers resolving an audience
        (Spec 04_orders, Appendix B2). Empty when the bot is not active:
        an OFF/MISCONFIGURED bot must promise nobody a message.
        Read-only, never commits.
        """
        if not is_bot_active():
            return set()
        return await consent.allowed_ids(session, player_ids)

    @staticmethod
    async def cancel_pending(
        session: AsyncSession,
        *,
        player_id: str,
        type_key: str,
        event_key: str,
        now: datetime | None = None,
    ) -> int:
        """
        Recall a producer's not-yet-sent NOTIFICATION rows (0.11.0 unit
        10a) — the cancelling half of :meth:`enqueue`, called inside the
        caller's transaction when the queued event became meaningless
        before the send (the order's judge changed). Matched by
        ``(player_id, type_key, event_key)`` — ``uq_bot_outbox_dedup``
        bounds the answer to one row.

        "Not yet sent" means ``PENDING`` plus ``LEASED`` rows whose
        lease already expired: a re-claim would put such a row back on
        the wire, and a late writer still holding the lost lease finds
        no matching row (the sender re-reads by ``lease_token``), so it
        cannot resurrect the drop. A row under a live lease is
        mid-flight — mutating it would race the in-progress send — and
        terminal rows are untouched. Returns the number of dropped
        rows; never commits.
        """
        t = now if now is not None else datetime.now(UTC)
        result = await session.execute(
            update(BotOutbox)
            .where(
                BotOutbox.player_id == player_id,
                BotOutbox.type_key == type_key,
                BotOutbox.event_key == event_key,
                BotOutbox.kind == "NOTIFICATION",
                or_(
                    BotOutbox.status == "PENDING",
                    and_(
                        BotOutbox.status == "LEASED",
                        or_(
                            BotOutbox.lease_until.is_(None),
                            BotOutbox.lease_until <= t,
                        ),
                    ),
                ),
            )
            .values(status="DROPPED", drop_reason="CANCELLED")
        )
        return result.rowcount or 0

    @staticmethod
    def app_link(fragment: str) -> str | None:
        """
        ``https://vk.com/app<VK_APP_ID>#<fragment>`` — a link that opens
        the Mini App straight at ``fragment`` (Spec 04_orders, Appendix
        B2; the host ``vk.com`` is in ``dialog.help.allowed_hosts``).
        ``None`` while ``VK_APP_ID`` is blank or not a number — the
        producer then sends the message without the link.
        """
        app_id = read_bot_env().app_id
        if app_id is None:
            return None
        return f"https://vk.com/app{app_id}#{fragment}"

    @staticmethod
    async def enqueue_reply(
        session: AsyncSession,
        *,
        player_id: str,
        template: str,
        variables: Mapping[str, str | int],
        keyboard: str,
        event_key: str,
        now: datetime | None = None,
    ) -> EnqueueResult:
        """
        Queue one dialog ``REPLY`` row (Spec 3.9 step 5) — module
        internal, called only by the callback's dialog handler.

        Same transaction rules as :meth:`enqueue`: never commits, the
        dedup ``UNIQUE`` violation is caught behind a SAVEPOINT, and a
        queued row rings the same after-commit wake bell. The template
        name, its variables and the ``AUTO``/``HELP`` keyboard marker
        go into ``payload``; ``expires_at`` is
        ``now + dialog.reply_ttl_minutes``. ``now`` only exists for
        tests.
        """
        t = now if now is not None else datetime.now(UTC)
        row = BotOutbox(
            player_id=player_id,
            kind="REPLY",
            type_key="DIALOG",
            event_key=event_key,
            priority="normal",
            counts_toward_cap=False,
            payload={
                "template": template,
                "vars": dict(variables),
                "keyboard": keyboard,
            },
            status="PENDING",
            attempts=0,
            created_at=t,
            not_before=t,
            next_attempt_at=t,
            expires_at=t + timedelta(minutes=get_bot_config().dialog.reply_ttl_minutes),
        )
        # Same SQLite-only transaction opener as enqueue (INV-B1).
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(BotOutbox).where(false()))
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            existing = (
                await session.execute(
                    select(BotOutbox.id).where(
                        BotOutbox.player_id == player_id,
                        BotOutbox.type_key == "DIALOG",
                        BotOutbox.event_key == event_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return EnqueueResult.DUPLICATE
            raise

        _arm_wake(session)
        return EnqueueResult.QUEUED


def _arm_wake(session: AsyncSession) -> None:
    """
    Arm the wake bell for THIS transaction only: the paired
    ``after_rollback`` hook disarms it if the caller's transaction is
    rolled back, so the bell never rings for a vanished row.
    """
    sync = session.sync_session

    def _wake(_s) -> None:
        sa_event.remove(sync, "after_rollback", _disarm)
        request_wake()

    def _disarm(_s) -> None:
        sa_event.remove(sync, "after_commit", _wake)

    sa_event.listen(sync, "after_commit", _wake, once=True)
    sa_event.listen(sync, "after_rollback", _disarm, once=True)
