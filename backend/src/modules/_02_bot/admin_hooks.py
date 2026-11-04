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
- Player delete ``"02_bot.player_delete"``: removes the player's
  ``bot_consents`` row (the consent FSM and the dialog state live on
  it — ``last_plate_at`` included) and all their ``bot_outbox`` rows.
  The ``bot_vk_events`` inbound journal survives: it carries only a
  logical ``vk_user_id`` link (no FK, INV-B11) and is append-only
  history. Runs inside ``PlayerService.delete_player``'s transaction —
  a raise aborts the whole deletion (no per-hook savepoint).
- Player preview ``"02_bot"``: returns ``{"outbox_rows", "consent_rows"}``
  counts for the admin delete-preview; read-only.
- Overview ``"02_bot"``: the three «Бот» tiles of the panel's «Ход и
  мир» board (mockup 25, sorts 87–89 — after the applications tiles,
  before the administrators count): sent per day, undelivered with the
  biggest drop reasons, and the median delivery delay. Every figure
  comes from the module's own ``bot_outbox`` over the last 24 hours —
  no call to VK. Read-only, never commits.

``register_bot_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.hooks import register_player_delete_hook
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
    now = datetime.now(UTC)

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
            oldest_ready = oldest_ready.replace(tzinfo=UTC)
        oldest_ready_age_seconds = round((now - oldest_ready).total_seconds())
    last_digest_turn = (
        await session.execute(select(BotState.last_digest_turn).where(BotState.id == 1))
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
        "last_digest_turn": last_digest_turn if last_digest_turn is not None else 0,
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


async def bot_player_delete_preview(session: AsyncSession, player_id: str) -> dict:
    """Counts of the module's rows the player deletion removes."""
    outbox_rows = (
        await session.execute(
            select(func.count())
            .select_from(BotOutbox)
            .where(BotOutbox.player_id == player_id)
        )
    ).scalar_one()
    consent_rows = (
        await session.execute(
            select(func.count())
            .select_from(BotConsent)
            .where(BotConsent.player_id == player_id)
        )
    ).scalar_one()
    return {"outbox_rows": outbox_rows, "consent_rows": consent_rows}


async def bot_delete_player(session: AsyncSession, player_id: str) -> None:
    """
    Remove the module's rows of one player (admin player deletion).

    Deletes the ``bot_consents`` row — which also holds the dialog
    state (``last_plate_at``) — and every ``bot_outbox`` row. Explicit
    DELETEs, not FK cascade: SQLite may run without enforced foreign
    keys. Inside the caller's transaction; never commits, and a raise
    rolls the whole player deletion back.
    """
    await session.execute(delete(BotOutbox).where(BotOutbox.player_id == player_id))
    await session.execute(delete(BotConsent).where(BotConsent.player_id == player_id))


_OVERVIEW_WINDOW = timedelta(hours=24)
# The delay tile reads at most the 5000 newest sent rows of the window
# — enough for a panel signal, bounded on a busy queue.
_OVERVIEW_DELAY_ROW_CAP = 5000
_UNDELIVERED_STATUSES = ("DROPPED", "FAILED", "EXPIRED")

_DROP_REASON_LABELS = {
    "NO_CONSENT": "нет разрешения",
    "BLOCKED": "заблокирован",
    "ATTEMPTS_EXHAUSTED": "попытки исчерпаны",
    "BAD_REQUEST": "ошибка запроса",
    "NO_NATION": "нет государства",
}
_OTHER_REASON_LABEL = "другое"


def _duration_text(seconds: float) -> str:
    """«2,4 с» under 10 s, «11 с» up to 120 s, «3 мин» above."""
    if seconds < 10:
        return f"{seconds:.1f} с".replace(".", ",")
    if seconds <= 120:
        return f"{round(seconds)} с"
    return f"{round(seconds / 60)} мин"


def _undelivered_note(rows: list) -> str:
    """«нет разрешения 4 · заблокирован 3 · другое 2» — top-3 + tail."""
    reasons: Counter[str] = Counter()
    for status, drop_reason, count in rows:
        if status == "EXPIRED":
            label = "просрочено"
        else:
            label = _DROP_REASON_LABELS.get(drop_reason, _OTHER_REASON_LABEL)
        reasons[label] += count
    ordered = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
    parts: list[str] = []
    tail_total = sum(count for _, count in ordered[3:])
    for label, count in ordered[:3]:
        if label == _OTHER_REASON_LABEL and tail_total:
            # The unknown bucket already reads «другое»: fold the tail
            # in instead of printing the label twice.
            count += tail_total
            tail_total = 0
        parts.append(f"{label} {count}")
    if tail_total:
        parts.append(f"{_OTHER_REASON_LABEL} {tail_total}")
    return " · ".join(parts)


async def bot_overview(session: AsyncSession) -> list[dict]:
    """
    The «Бот сообщества» tiles of the panel's «Ход и мир» board
    (mockup 25, sorts 87–89): «отправлено за сутки», «не доставлено»
    with the biggest reasons and «задержка доставки» — all counted
    from ``bot_outbox`` over the last 24 hours, no call to VK.
    Read-only, never commits.
    """
    since = datetime.now(UTC) - _OVERVIEW_WINDOW

    sent_total = (
        await session.execute(
            select(func.count())
            .select_from(BotOutbox)
            .where(BotOutbox.status == "SENT", BotOutbox.sent_at >= since)
        )
    ).scalar_one()

    undelivered_rows = (
        await session.execute(
            select(BotOutbox.status, BotOutbox.drop_reason, func.count())
            .where(
                BotOutbox.created_at >= since,
                BotOutbox.status.in_(_UNDELIVERED_STATUSES),
                # Our own cancel is not a failure.
                BotOutbox.drop_reason.is_distinct_from("CANCELLED"),
            )
            .group_by(BotOutbox.status, BotOutbox.drop_reason)
        )
    ).all()
    undelivered_total = sum(count for _, _, count in undelivered_rows)

    # The delay is computed in Python from the two timestamps —
    # sent_at minus max(created_at, not_before) — over the newest
    # capped slice (see _OVERVIEW_DELAY_ROW_CAP). SQLite returns
    # naive datetimes; they are UTC here.
    delay_rows = (
        await session.execute(
            select(BotOutbox.sent_at, BotOutbox.created_at, BotOutbox.not_before)
            .where(BotOutbox.status == "SENT", BotOutbox.sent_at >= since)
            .order_by(BotOutbox.sent_at.desc())
            .limit(_OVERVIEW_DELAY_ROW_CAP)
        )
    ).all()
    delays = [
        (sent_at - max(created_at, not_before)).total_seconds()
        for sent_at, created_at, not_before in delay_rows
    ]
    if delays:
        delay_value = _duration_text(statistics.median(delays))
        delay_note = f"медиана за сутки; наибольшая {_duration_text(max(delays))}"
    else:
        delay_value = "—"
        delay_note = "за сутки ничего не отправлено"

    return [
        {
            "key": "bot_sent",
            "label": "Бот · отправлено за сутки",
            "value": str(sent_total),
            "note": "уведомления и ответы",
            "sort": 87,
            "group": "bot",
        },
        {
            "key": "bot_undelivered",
            "label": "Бот · не доставлено",
            "value": str(undelivered_total),
            "note": (
                _undelivered_note(undelivered_rows)
                if undelivered_total
                else "ничего не потеряно"
            ),
            "sort": 88,
            "group": "bot",
        },
        {
            "key": "bot_delivery_delay",
            "label": "Бот · задержка доставки",
            "value": delay_value,
            "note": delay_note,
            "sort": 89,
            "group": "bot",
        },
    ]


def register_bot_admin_hooks() -> None:
    """Register the admin hooks; safe to call on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, bot_state_view)
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, bot_reset)
    if MODULE_SLUG not in AdminRegistry.get_player_preview_hooks():
        AdminRegistry.register_player_preview(MODULE_SLUG, bot_player_delete_preview)
    if MODULE_SLUG not in AdminRegistry.get_overview_hooks():
        AdminRegistry.register_overview(MODULE_SLUG, bot_overview)
    # Player-delete hooks live in the 00_core registry; re-registering
    # the same name simply replaces the entry.
    register_player_delete_hook(f"{MODULE_SLUG}.player_delete", bot_delete_player)
