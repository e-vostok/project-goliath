"""
Janitor of module 02_bot (Spec 2.5 — hourly sweep).

Two duties per pass:

- delete terminal ``bot_outbox`` rows (SENT/EXPIRED/DROPPED/FAILED)
  and ``bot_vk_events`` journal entries older than
  ``sender.purge_after_days``;
- return ``LEASED`` rows whose lease expired back to ``PENDING`` so a
  worker that died mid-send never strands the queue (the claim step
  also picks these up directly — the janitor just normalises early).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules._02_bot.config_schema import BotConfig
from modules._02_bot.models import BotOutbox, BotVkEvent

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_TERMINAL_STATUSES = ("SENT", "EXPIRED", "DROPPED", "FAILED")


async def janitor_step(
    session_factory: SessionFactory,
    config: BotConfig,
    now: datetime | None = None,
) -> None:
    """One sweep: purge old terminal rows + journal, unstick leases."""
    t = now if now is not None else datetime.now(timezone.utc)
    cutoff = t - timedelta(days=config.sender.purge_after_days)
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(BotOutbox).where(
                    BotOutbox.status.in_(_TERMINAL_STATUSES),
                    BotOutbox.created_at <= cutoff,
                )
            )
            await session.execute(
                delete(BotVkEvent).where(
                    BotVkEvent.received_at <= cutoff
                )
            )
            await session.execute(
                update(BotOutbox)
                .where(
                    BotOutbox.status == "LEASED",
                    or_(
                        BotOutbox.lease_until <= t,
                        BotOutbox.lease_until.is_(None),
                    ),
                )
                .values(
                    status="PENDING",
                    lease_until=None,
                    lease_token=None,
                )
            )
