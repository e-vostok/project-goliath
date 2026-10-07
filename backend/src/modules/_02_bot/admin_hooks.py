"""
Admin hooks of module 02_bot (Spec 5.4).

- State view ``"02_bot"``: a JSON-able snapshot — mode, consent counts
  per state, outbox counts per status, age of the oldest ready row,
  ``last_digest_turn``, the live sender status (RUNNING /
  BREAKER_OPEN / HALF_OPEN / HALTED_AUTH, ``NOT_STARTED`` without a
  runtime) and each task's last successful pass. Never exposes env
  values or secrets (INV-B9).
- Reset ``"02_bot"``: wipes the whole ``bot_outbox`` queue and zeroes
  ``bot_state.last_digest_turn`` (INV-B14); consents and the
  ``bot_vk_events`` journal survive. The hook never commits — the admin
  panel owns the transaction.

``register_bot_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._02_bot.models import BotConsent, BotOutbox, BotState
from modules._02_bot.settings import (
    MODULE_SLUG,
    get_active_runtime,
    get_bot_mode,
)

logger = logging.getLogger(__name__)

_TASK_NAMES = ("sender", "digest_watcher", "consent_reconciler", "janitor")


async def bot_state_view(session: AsyncSession) -> dict:
    """Read-only snapshot of the module for the admin panel (Spec 5.4)."""
    now = datetime.now(timezone.utc)

    consent_rows = await session.execute(
        select(BotConsent.state, func.count()).group_by(BotConsent.state)
    )
    outbox_rows = await session.execute(
        select(BotOutbox.status, func.count()).group_by(BotOutbox.status)
    )
    oldest_ready = (
        await session.execute(
            select(BotOutbox.created_at)
            .where(
                BotOutbox.status == "PENDING",
                BotOutbox.not_before <= now,
                BotOutbox.next_attempt_at <= now,
            )
            .order_by(BotOutbox.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    oldest_ready_age_seconds = None
    if oldest_ready is not None:
        # SQLite returns naive datetimes even for timezone=True columns.
        if oldest_ready.tzinfo is None:
            oldest_ready = oldest_ready.replace(tzinfo=timezone.utc)
        oldest_ready_age_seconds = round(
            (now - oldest_ready).total_seconds()
        )
    last_digest_turn = (
        await session.execute(
            select(BotState.last_digest_turn).where(BotState.id == 1)
        )
    ).scalar_one_or_none()

    # The live runtime's sender state and task heartbeats; no secrets.
    runtime = get_active_runtime()
    if runtime is not None:
        sender = runtime.sender_state()
        tasks = runtime.task_last_pass()
    else:
        sender = "NOT_STARTED"
        tasks = {name: None for name in _TASK_NAMES}

    return {
        "bot_mode": get_bot_mode().value,
        "consents": dict(consent_rows.all()),
        "outbox": dict(outbox_rows.all()),
        "oldest_ready_age_seconds": oldest_ready_age_seconds,
        "last_digest_turn": last_digest_turn
        if last_digest_turn is not None
        else 0,
        "sender": sender,
        "tasks": tasks,
    }


async def bot_reset(session: AsyncSession) -> None:
    """World reset (INV-B14): empty queue, zero digest marker. No commit."""
    await session.execute(delete(BotOutbox))
    state = (
        await session.execute(select(BotState).where(BotState.id == 1))
    ).scalar_one_or_none()
    if state is None:
        # Bare test schemas lack the migration-seeded singleton.
        session.add(BotState(id=1, last_digest_turn=0))
    else:
        state.last_digest_turn = 0
    await session.flush()


def register_bot_admin_hooks() -> None:
    """Register the admin hooks; safe to call on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, bot_state_view)
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, bot_reset)
