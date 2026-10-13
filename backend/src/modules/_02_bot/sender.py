"""
Send step of the sender (Spec 3.3, 2.7; INV-B6/B7/B8).

``process_group`` per leased group: limiter token -> breaker/pause
gate -> ``expires_at`` re-check (INV-B8) -> render + keyboard -> one
``messages.send`` -> the result written in a NEW transaction and only
for rows still carrying the group's ``lease_token`` (a lease lost to
another worker writes nothing).

Retries follow Spec 2.7: retryable classes return the rows to
PENDING with exponential backoff + jitter; ``RATE_GLOBAL`` pauses the
whole sender for ``backoff_base_seconds``; ``CONSENT_LOST`` flips the
consent FSM and drops; ``AUTH`` halts the sender until restart. The
breaker sees only counted classes (Spec 2.7). Clock, monotonic time
and jitter are injectable — no real sleeps in tests.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService, PlayerService
from modules._02_bot import consent as consent_mod
from modules._02_bot.breaker import BreakerState, CircuitBreaker
from modules._02_bot.claim import ClaimedGroup
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.errors import (
    ErrorClass,
    classify_vk_error,
    counts_for_breaker,
)
from modules._02_bot.keyboard import (
    build_help_inline_keyboard,
    build_persistent_keyboard,
    dumps as keyboard_dumps,
)
from modules._02_bot.limiter import TokenBucket
from modules._02_bot.models import BotOutbox
from modules._02_bot.render import (
    MessageTooLong,
    TemplateError,
    render_message,
    render_reply,
)
from modules._02_bot.settings import BotEnv
from modules._02_bot.vk_client import SendKind, SendOutcome, VkClient

logger = logging.getLogger(__name__)

# Same shape as core.tick.scheduler.SessionFactory (get_session_context).
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_CONSENT_SOURCES = {
    900: "VK_ERROR_900",
    901: "VK_ERROR_901",
    902: "VK_ERROR_902",
    1021: "VK_ERROR_1021",
}
_BLOCKED_CODES = frozenset({900, 901, 902})


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


@dataclass
class SenderState:
    """Mutable sender-level flags shared by all group workers."""

    halted_auth: bool = False
    paused_until: float = 0.0  # monotonic deadline of a RATE_GLOBAL pause


class Sender:
    """Drives leased groups through VK with retry/breaker semantics."""

    def __init__(
        self,
        config: BotConfig,
        env: BotEnv,
        session_factory: SessionFactory,
        vk_client: VkClient,
        limiter: TokenBucket,
        breaker: CircuitBreaker,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        rng: Callable[[], float] = random.random,
    ):
        self._config = config
        self._env = env
        self._session_factory = session_factory
        self._vk = vk_client
        self._limiter = limiter
        self._breaker = breaker
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._rng = rng
        self._semaphore = asyncio.Semaphore(config.sender.concurrency)
        self.state = SenderState()

    def status_word(self) -> str:
        """The admin-view sender state (Spec 5.4)."""
        if self.state.halted_auth:
            return "HALTED_AUTH"
        if self._breaker.state == BreakerState.OPEN:
            return "BREAKER_OPEN"
        if self._breaker.state == BreakerState.HALF_OPEN:
            return "HALF_OPEN"
        return "RUNNING"

    async def process_groups(self, groups: list[ClaimedGroup]) -> None:
        """Send a claimed batch, at most ``sender.concurrency`` in flight."""

        async def _one(group: ClaimedGroup) -> None:
            async with self._semaphore:
                await self.process_group(group)

        results = await asyncio.gather(
            *(_one(group) for group in groups), return_exceptions=True
        )
        for group, result in zip(groups, results):
            if isinstance(result, BaseException):
                logger.exception(
                    "send of group %s crashed", group.group_id,
                    exc_info=result,
                )

    async def process_group(self, group: ClaimedGroup) -> None:
        """Spec 3.3 for one group; every early exit leaves rows LEASED."""
        if self.state.halted_auth:
            return
        await self._limiter.acquire()
        if self.state.halted_auth:
            return
        if self._monotonic() < self.state.paused_until:
            return
        if not self._breaker.allow():
            return

        now = self._now()
        peer_id = await self._recheck_rows(group, now)
        if peer_id is None:
            return

        try:
            text, keyboard_json = await self._render(group)
        except (TemplateError, MessageTooLong) as exc:
            reason = (
                "TEMPLATE_ERROR"
                if isinstance(exc, TemplateError)
                else "TOO_LONG"
            )
            await self._write_rows(group, lambda r: self._drop(r, reason))
            return
        except ValueError:
            # keyboard.dumps guard — a config-level bug, not a retry.
            logger.exception("keyboard build failed for a group")
            await self._write_rows(
                group, lambda r: self._drop(r, "BAD_REQUEST")
            )
            return

        outcome = await self._vk.send_message(
            peer_id=peer_id,
            random_id=group.random_id,
            message=text,
            keyboard_json=keyboard_json,
        )
        await self._record_outcome(group, outcome, now)

    async def _recheck_rows(
        self, group: ClaimedGroup, now: datetime
    ) -> int | None:
        """
        INV-B8: re-read the group's rows under our lease_token; expired
        rows go EXPIRED and the survivors return to PENDING for
        recomposition (the group dissolves, Spec 3.3 step 1). Returns
        the resolved peer id, or None when the send must not happen.
        """
        async with self._session_factory() as session:
            async with session.begin():
                db_rows = await self._leased_rows(session, group)
                if not db_rows:
                    return None
                expired = [
                    row
                    for row in db_rows
                    if _aware(row.expires_at) <= now
                ]
                if expired:
                    for row in expired:
                        row.status = "EXPIRED"
                    for row in db_rows:
                        if row not in expired:
                            row.status = "PENDING"
                            row.lease_until = None
                            row.lease_token = None
                            row.group_id = None
                            row.random_id = None
                            row.render_mode = None
                    return None
            ids = await PlayerService.vk_user_ids(
                session, [group.player_id]
            )
        peer_id = ids.get(group.player_id)
        if peer_id is None:
            logger.error(
                "player %s of a leased group has no vk_user_id",
                group.player_id,
            )
            return None
        return peer_id

    async def _leased_rows(
        self, session: AsyncSession, group: ClaimedGroup
    ) -> list[BotOutbox]:
        """The group's rows still held by our lease — empty when lost."""
        result = await session.execute(
            select(BotOutbox).where(
                BotOutbox.group_id == group.group_id,
                BotOutbox.lease_token == group.lease_token,
                BotOutbox.status == "LEASED",
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            logger.warning(
                "lease %s of group %s matched no rows — lost to another "
                "worker or already written",
                group.lease_token,
                group.group_id,
            )
        return rows

    async def _render(
        self, group: ClaimedGroup
    ) -> tuple[str, str | None]:
        """Text + keyboard JSON per Spec 3.6/5.5."""
        rows_by_id = {row.id: row for row in group.rows}
        first = group.rows[0]
        help_keyboard = False
        if first.kind == "REPLY":
            text = render_reply(first, self._config, {})
            help_keyboard = first.payload.get("keyboard") == "HELP"
        else:
            text = render_message(
                group.composed_message(), rows_by_id, self._config
            )
        if help_keyboard:
            keyboard = build_help_inline_keyboard(self._config)
        else:
            async with self._session_factory() as session:
                nation = await NationService.player_nation_summary(
                    session, group.player_id
                )
            keyboard = build_persistent_keyboard(
                "MEMBER" if nation is not None else "GUEST",
                self._config,
                self._env.app_id,
            )
        return text, keyboard_dumps(keyboard) if keyboard else None

    def _drop(self, row: BotOutbox, reason: str) -> None:
        row.status = "DROPPED"
        row.drop_reason = reason

    async def _write_rows(
        self,
        group: ClaimedGroup,
        apply,
        extra=None,
    ) -> None:
        """One write transaction guarded by lease_token (Spec 3.3 step 4)."""
        async with self._session_factory() as session:
            async with session.begin():
                db_rows = await self._leased_rows(session, group)
                if not db_rows:
                    return
                for row in db_rows:
                    apply(row)
                if extra is not None:
                    await extra(session)

    def _backoff_seconds(self, attempts: int) -> int:
        """Spec 3.3: ceil(min(cap, base*2^(n-1)) * (1 + jitter*u))."""
        sender = self._config.sender
        base = sender.backoff_base_seconds * 2 ** max(0, attempts - 1)
        delay = min(sender.backoff_cap_seconds, base) * (
            1 + sender.backoff_jitter * self._rng()
        )
        return math.ceil(delay)

    def _retry(self, row: BotOutbox, code: int, now: datetime) -> None:
        row.status = "PENDING"
        row.lease_until = None
        row.lease_token = None
        row.last_error_code = code
        row.next_attempt_at = now + timedelta(
            seconds=self._backoff_seconds(row.attempts)
        )

    async def _record_outcome(
        self, group: ClaimedGroup, outcome: SendOutcome, now: datetime
    ) -> None:
        """Map the SendOutcome to row writes + sender-level effects."""
        error_class = (
            classify_vk_error(outcome.code)
            if outcome.kind != SendKind.OK
            else None
        )
        # The probe reads "VK answered" as success: OK and every
        # uncounted recipient outcome prove reachability.
        probe_success = outcome.kind == SendKind.OK or (
            error_class is not None and not counts_for_breaker(error_class)
        )
        self._breaker.record(
            probe_success,
            outcome.kind != SendKind.OK and counts_for_breaker(error_class),
        )

        if outcome.kind == SendKind.OK:
            sent_at = now

            def _sent(row: BotOutbox) -> None:
                row.status = "SENT"
                row.sent_at = sent_at
                row.vk_message_id = outcome.message_id
                row.last_error_code = None

            await self._write_rows(group, _sent)
            return

        code = outcome.code
        retryable = {
            ErrorClass.SYSTEM,
            ErrorClass.RATE_GLOBAL,
            ErrorClass.SPAM_RESTRICTED,
            ErrorClass.UNKNOWN,
            ErrorClass.TRANSPORT,
            ErrorClass.FLOOD_PLAYER,
        }
        if error_class in retryable:
            if error_class == ErrorClass.RATE_GLOBAL:
                self.state.paused_until = max(
                    self.state.paused_until,
                    self._monotonic()
                    + self._config.sender.backoff_base_seconds,
                )
            if error_class == ErrorClass.SPAM_RESTRICTED:
                logger.critical(
                    "VK spam restriction (984) hit the community sender"
                )

            def _back_to_pending(row: BotOutbox) -> None:
                self._retry(row, code, now)

            await self._write_rows(group, _back_to_pending)
            return

        if error_class == ErrorClass.CONSENT_LOST:
            source = _CONSENT_SOURCES[code]
            reason = "BLOCKED" if code in _BLOCKED_CODES else "NO_CONSENT"

            async def _consent(session: AsyncSession) -> None:
                # Drops the player's other PENDING notifications too.
                await consent_mod.apply_consent_signal(
                    session, group.player_id, "DENIED", source, now=now
                )

            await self._write_rows(
                group,
                lambda r: self._drop(r, reason),
                extra=_consent,
            )
            return

        if error_class == ErrorClass.AUTH:
            self.state.halted_auth = True
            logger.critical(
                "VK access key rejected (code %s) — sender halted until "
                "restart",
                code,
            )

            def _unchanged(row: BotOutbox) -> None:
                row.status = "PENDING"
                row.lease_until = None
                row.lease_token = None
                row.last_error_code = code

            await self._write_rows(group, _unchanged)
            return

        # BAD_REQUEST / TOO_LONG / unreachable default — drop.
        reason = (
            "BAD_REQUEST"
            if error_class == ErrorClass.BAD_REQUEST
            else "TOO_LONG"
        )
        logger.error(
            "messages.send dropped a group: code %s", code
        )
        await self._write_rows(group, lambda r: self._drop(r, reason))
