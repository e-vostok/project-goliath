"""
The «nation created» hook of module 02_bot (Spec 3.11, Issue 7).

Registered as ``02_bot.nation_created`` during ``startup_bot()`` —
always registered; the function itself gates on the bot mode and on
the player's stored consent, so an OFF bot queues nothing. It runs
inside ``NationService.create`` after all creation writes, under its
own SAVEPOINT in the caller's transaction: any unexpected exception
propagates to the core's SAVEPOINT handling, which isolates it — the
hook never raises for the expected cases (bot off, no consent).

The queued ``REPLY`` row rides the normal sender path; at send time the
nation already exists, so the ``AUTO`` keyboard resolves to ``MEMBER``
and the player's panel switches away from «Создать государство» with
this very message.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService
from modules._02_bot import consent as consent_mod
from modules._02_bot.settings import is_bot_active

logger = logging.getLogger(__name__)


async def nation_created_hook(
    session: AsyncSession, player_id: str, nation_id: str
) -> None:
    """Spec 3.11 steps 1–3 — the ``(session, player_id, nation_id)`` signature."""
    # Step 1: bot off or misconfigured — nothing.
    if not is_bot_active():
        return
    # Step 2: only a stored ALLOWED consent earns the message; a
    # missing row means "no consent yet" — the hook never creates
    # consent rows.
    if not await consent_mod.is_allowed(session, player_id):
        return
    # Step 3: the nation name through the public core read — no direct
    # core SQL. The hook fires inside create's transaction, so the
    # nation is guaranteed to exist; the mismatch guard stays defensive.
    nation = await NationService.player_nation_summary(session, player_id)
    if nation is None or nation.nation_id != nation_id:
        return
    # Imported lazily: service -> startup would otherwise close an
    # import cycle back into this module (same shape as
    # registration_check -> runtime/startup).
    from modules._02_bot.service import BotService

    # Duplicate event_key is a silent no-op (dedup UNIQUE). The name
    # passes through the renderer's sanitization at send time.
    await BotService.enqueue_reply(
        session,
        player_id=player_id,
        template="nation_created",
        variables={"nation_name": nation.name},
        keyboard="AUTO",
        event_key=f"nation_created:{nation_id}",
    )
