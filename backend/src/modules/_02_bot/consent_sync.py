"""
On-demand consent synchronisation of module 02_bot (Spec 3.7).

Used by ``GET /bot/status`` (lazy, ``force=False``) and
``POST /bot/consent/refresh`` (``force=True``). The VK call goes
through the installed runtime's shared VK gate; the result is recorded
with ``consent.record_vk_check``. No row locks are held while VK is
polled — the consent row is read before the call and the check result
is written after it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Player
from modules._00_core.service import PlayerService
from modules._02_bot import consent as consent_mod
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.runtime import get_runtime

logger = logging.getLogger(__name__)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes for ``timezone=True`` columns."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def sync_consent_with_vk(
    session: AsyncSession,
    config: BotConfig,
    player: Player,
    *,
    force: bool,
    now: datetime | None = None,
) -> tuple[str, bool, bool]:
    """
    Maybe refresh the player's consent state from VK.

    ``force=False`` (GET): the VK check runs only when the state is
    UNKNOWN, was never checked, or ``consent.recheck_after_seconds``
    has passed — but never within ``consent.refresh_min_interval_seconds``
    of the last check. ``force=True`` (POST): the check runs unless the
    last one is within the minimum interval, which returns
    ``throttled=True``. Returns ``(state, stale, throttled)``.
    """
    t = now if now is not None else datetime.now(timezone.utc)
    row = await consent_mod.get_or_create_consent(
        session, player.id, now=t
    )
    last = _aware(row.last_checked_at)

    within_min_interval = (
        last is not None
        and (t - last)
        < timedelta(seconds=config.consent.refresh_min_interval_seconds)
    )
    if force:
        if within_min_interval:
            return row.state, False, True
    else:
        needs_check = (
            row.state == "UNKNOWN"
            or last is None
            or (t - last)
            > timedelta(seconds=config.consent.recheck_after_seconds)
        )
        if not needs_check or within_min_interval:
            return row.state, False, False

    runtime = get_runtime()
    vk_user_id = (
        await PlayerService.vk_user_ids(session, [player.id])
    ).get(player.id)
    allowed = None
    if runtime is not None and vk_user_id is not None:
        allowed = await runtime.check_allowed(vk_user_id)
    if allowed is None:
        # VK unreachable, breaker open or no runtime: keep the stored
        # state and flag it stale (Spec 3.7).
        return row.state, True, False
    transition = await consent_mod.record_vk_check(
        session, player.id, allowed, now=t
    )
    return transition.new, False, False
