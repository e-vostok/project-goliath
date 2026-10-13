"""
Consent gate on nation registration of module 02_bot (Spec 3.10).

Registered at ``STAGE_BEFORE_ALL`` during ``startup_bot()`` — always
registered; the function itself gates on bot mode and
``consent.required_for_registration``. It runs before any write of the
registration path, so the only rows it can touch are its own consent
row.

Fail-open (INV-B15): a VK outage, a timeout, an open breaker,
``HALTED_AUTH``, a missing runtime or any error inside the check logs a
WARNING (no secrets) and lets registration proceed — only an explicit
VK «not allowed» blocks with :class:`ConsentRequiredError`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import PlayerService
from modules._02_bot import consent as consent_mod
from modules._02_bot.exceptions import ConsentRequiredError
from modules._02_bot.settings import is_bot_active

logger = logging.getLogger(__name__)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes for ``timezone=True`` columns."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def check_registration_consent(
    session: AsyncSession, player_id: str
) -> None:
    """Spec 3.10 steps 1–5 — ``(session, player_id)`` stage signature."""
    # Step 1: bot off or the feature disabled — pass without VK/writes.
    if not is_bot_active():
        return
    # Imported lazily: runtime -> watcher -> service -> startup would
    # otherwise close an import cycle back into this module.
    from modules._02_bot.runtime import get_runtime
    from modules._02_bot.startup import get_bot_config

    config = get_bot_config()
    if not config.consent.required_for_registration:
        return

    now = datetime.now(timezone.utc)
    try:
        row = await consent_mod.get_or_create_consent(
            session, player_id, now=now
        )
        # Step 2: already allowed — pass.
        if row.state == "ALLOWED":
            return
        # Step 3: a fresh check is within the minimum interval — trust
        # it (a fresh ALLOWED was already returned above, so a stored
        # fresh non-allowed state blocks without a new VK call).
        last = _aware(row.last_checked_at)
        if (
            last is not None
            and (now - last)
            < timedelta(
                seconds=config.consent.refresh_min_interval_seconds
            )
        ):
            raise ConsentRequiredError()
        # Step 4: one on-demand VK check through the live runtime.
        runtime = get_runtime()
        vk_user_id = (
            await PlayerService.vk_user_ids(session, [player_id])
        ).get(player_id)
        allowed = (
            await runtime.check_allowed(vk_user_id)
            if runtime is not None and vk_user_id is not None
            else None
        )
        if allowed is None:
            logger.warning("registration_consent_check_skipped")
            return
        await consent_mod.record_vk_check(
            session, player_id, allowed, now=now
        )
        if not allowed:
            # Commit BEFORE raising: this stage runs before any
            # registration write, so the caller's rollback discards
            # nothing else — the commit is what keeps the new DENIED
            # state and last_checked_at durable (Spec 3.10 step 4).
            await session.commit()
            raise ConsentRequiredError()
    except ConsentRequiredError:
        raise
    except Exception:
        # Step 5 / INV-B15: any failure of the check itself fails open.
        logger.warning("registration_consent_check_skipped")
