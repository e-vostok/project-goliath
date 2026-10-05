"""
Consent reconciler of module 02_bot (Spec 3.7).

Every ``consent.reconcile_sweep_interval_seconds`` the task takes up
to ``consent.reconcile_batch_size`` players still in ``UNKNOWN``
(oldest first) and asks VK ``isMessagesFromGroupAllowed`` for each —
under the same rate limiter as sends. Answers fold into the consent
FSM via ``record_vk_check``; a failed check (None) changes nothing,
not even ``last_checked_at``.

VK calls happen between transactions: the UNKNOWN set is read, the
checks run, and the results are written in a fresh transaction —
no database transaction is held over the network (INV-B7 spirit).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import PlayerService
from modules._02_bot import consent as consent_mod
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.limiter import TokenBucket
from modules._02_bot.models import BotConsent
from modules._02_bot.settings import BotEnv
from modules._02_bot.vk_client import VkClient

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def reconcile_step(
    session_factory: SessionFactory,
    config: BotConfig,
    env: BotEnv,
    vk_client: VkClient,
    limiter: TokenBucket,
    now: datetime | None = None,
) -> int:
    """
    One background reconciliation pass; returns the number of VK
    checks performed (0 when nobody is UNKNOWN or every check failed
    to resolve a vk id).
    """
    t = now if now is not None else datetime.now(timezone.utc)
    if not env.group_id or not env.group_id.isdigit():
        return 0
    async with session_factory() as session:
        player_ids = (
            (
                await session.execute(
                    select(BotConsent.player_id)
                    .where(BotConsent.state == "UNKNOWN")
                    .order_by(BotConsent.created_at)
                    .limit(config.consent.reconcile_batch_size)
                )
            )
            .scalars()
            .all()
        )
    if not player_ids:
        return 0

    async with session_factory() as session:
        vk_ids = await PlayerService.vk_user_ids(session, player_ids)

    answers: dict[str, bool | None] = {}
    for player_id in player_ids:
        vk_user_id = vk_ids.get(player_id)
        if vk_user_id is None:
            continue
        await limiter.acquire()
        answers[player_id] = (
            await vk_client.is_messages_from_group_allowed(
                int(env.group_id), vk_user_id
            )
        )

    async with session_factory() as session:
        async with session.begin():
            for player_id, allowed in answers.items():
                await consent_mod.record_vk_check(
                    session, player_id, allowed, now=t
                )
    return len(answers)
