"""
Consent FSM of module 02_bot (Spec 2.3) — pure DB logic, no VK calls.

States UNKNOWN/ALLOWED/DENIED live in ``bot_consents``; the four legal
transitions are UNKNOWN->ALLOWED, UNKNOWN->DENIED, ALLOWED->DENIED and
DENIED->ALLOWED. Every DENIED signal — including a repeated one —
drops the player's PENDING NOTIFICATION rows: ``BLOCKED`` when the
signal came from VK errors 900/901/902, else ``NO_CONSENT``. ALLOWED
never resurrects dropped rows.

All functions take the caller's AsyncSession and never commit (INV-B1);
``now`` is injectable so tests are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules._02_bot.models import BotConsent, BotOutbox

# Sources ordered by trust in Spec 2.3; the set is what
# apply_consent_signal accepts.
CONSENT_SOURCES = frozenset(
    {
        "VK_EVENT",
        "VK_CHECK",
        "VK_ERROR_900",
        "VK_ERROR_901",
        "VK_ERROR_902",
        "VK_ERROR_1021",
    }
)

# VK send errors meaning the player blocked/never allowed the bot —
# pending rows drop as BLOCKED rather than NO_CONSENT (Spec 2.7).
_BLOCKED_DROP_SOURCES = frozenset(
    {"VK_ERROR_900", "VK_ERROR_901", "VK_ERROR_902"}
)


@dataclass(frozen=True)
class ConsentTransition:
    """Outcome of one consent signal: previous state, new state, and
    whether the state actually moved."""

    old: str
    new: str
    changed: bool


async def get_or_create_consent(
    session: AsyncSession,
    player_id: str,
    now: datetime | None = None,
) -> BotConsent:
    """The player's consent row, created as UNKNOWN/INIT on first use."""
    result = await session.execute(
        select(BotConsent).where(BotConsent.player_id == player_id)
    )
    consent = result.scalar_one_or_none()
    if consent is None:
        t = now if now is not None else datetime.now(timezone.utc)
        consent = BotConsent(
            player_id=player_id,
            state="UNKNOWN",
            state_source="INIT",
            state_changed_at=t,
            created_at=t,
        )
        session.add(consent)
        await session.flush()
    return consent


async def apply_consent_signal(
    session: AsyncSession,
    player_id: str,
    new_state: str,
    source: str,
    now: datetime | None = None,
) -> ConsentTransition:
    """
    Apply one consent signal (Spec 2.3).

    ``new_state`` must be ALLOWED or DENIED — UNKNOWN is never a
    signal's target. ``source`` must be one of CONSENT_SOURCES.
    ``state_changed_at``/``state_source`` move only when the state
    changes; a VK_CHECK source always refreshes ``last_checked_at``.
    Every DENIED signal drops the player's PENDING NOTIFICATION rows.
    """
    if new_state not in ("ALLOWED", "DENIED"):
        raise ValueError(
            f"new_state must be 'ALLOWED' or 'DENIED', got {new_state!r}"
        )
    if source not in CONSENT_SOURCES:
        raise ValueError(f"unknown consent signal source {source!r}")
    t = now if now is not None else datetime.now(timezone.utc)

    consent = await get_or_create_consent(session, player_id, now=t)
    old = consent.state
    if source == "VK_CHECK":
        consent.last_checked_at = t
    changed = old != new_state
    if changed:
        consent.state = new_state
        consent.state_source = source
        consent.state_changed_at = t
    await session.flush()

    if new_state == "DENIED":
        drop_reason = (
            "BLOCKED" if source in _BLOCKED_DROP_SOURCES else "NO_CONSENT"
        )
        await session.execute(
            update(BotOutbox)
            .where(
                BotOutbox.player_id == player_id,
                BotOutbox.status == "PENDING",
                BotOutbox.kind == "NOTIFICATION",
            )
            .values(status="DROPPED", drop_reason=drop_reason)
        )

    return ConsentTransition(old=old, new=new_state, changed=changed)


async def record_vk_check(
    session: AsyncSession,
    player_id: str,
    is_allowed: bool | None,
    now: datetime | None = None,
) -> ConsentTransition | None:
    """
    Fold one ``isMessagesFromGroupAllowed`` answer into the FSM.

    ``is_allowed=None`` means the check failed (network/timeout) and
    changes nothing — not even ``last_checked_at``. True/False apply
    an ALLOWED/DENIED signal with source VK_CHECK.
    """
    if is_allowed is None:
        return None
    return await apply_consent_signal(
        session,
        player_id,
        "ALLOWED" if is_allowed else "DENIED",
        "VK_CHECK",
        now=now,
    )


async def is_allowed(session: AsyncSession, player_id: str) -> bool:
    """True only when the stored consent state is ALLOWED."""
    result = await session.execute(
        select(BotConsent.state).where(BotConsent.player_id == player_id)
    )
    return result.scalar_one_or_none() == "ALLOWED"
