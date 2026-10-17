"""
Bot notifications of module 04_orders (Spec D9, Appendix C).

The four ORDER_* types are registered with the bot module by
``register_orders_extensions()``. Issue 6 produces the assignment
pair — ``ORDER_JUDGE_ASSIGNED`` to the judge and ``ORDER_DISTRIBUTED``
to the author; Issue 7 adds ``ORDER_VERDICT_READY`` to the author;
Issue 9 adds the ``ORDER_JUDGE_REMINDER`` producer in the worker's
retry pass.

Player privacy (Spec 0, D9): the texts carry the order number, the
author-nation name and the order link — never the player-written title
or summary, and the judge's identity is revealed to no player.
"""

from __future__ import annotations

import logging
import math

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from modules._02_bot.service import BotService, EnqueueResult
from modules._04_orders.models import Order

logger = logging.getLogger(__name__)

ORDER_JUDGE_ASSIGNED = "ORDER_JUDGE_ASSIGNED"
ORDER_JUDGE_REMINDER = "ORDER_JUDGE_REMINDER"
ORDER_DISTRIBUTED = "ORDER_DISTRIBUTED"
ORDER_VERDICT_READY = "ORDER_VERDICT_READY"

# The exact variable set each type promises to provide (Appendix C).
NOTIFICATION_VARIABLES: dict[str, frozenset[str]] = {
    ORDER_JUDGE_ASSIGNED: frozenset({"order_number", "nation_name", "order_link"}),
    ORDER_JUDGE_REMINDER: frozenset({"order_number", "hours_left", "order_link"}),
    ORDER_DISTRIBUTED: frozenset({"order_number", "order_link"}),
    ORDER_VERDICT_READY: frozenset({"order_number", "order_link"}),
}


def order_app_link(order_number: int) -> str | None:
    """The deep link into the order window; ``None`` without VK_APP_ID."""
    return BotService.app_link(f"registry/order-{order_number}")


async def notify_assignment(
    session: AsyncSession,
    *,
    order: Order,
    judge_player_id: str,
    distributed_at: datetime,
) -> None:
    """
    Enqueue the assignment pair (Spec 3.3 step 8): ORDER_JUDGE_ASSIGNED
    to the judge, ORDER_DISTRIBUTED to the author — both stamped with
    ``event_at = distributed_at`` so TTL counts from the assignment.

    Without VK_APP_ID there is no link to send: enqueue nothing and log
    one warning (Appendix C). Skip results are ignored on purpose — an
    unreachable recipient is the bot's business, not the order's.
    """
    link = order_app_link(order.number)
    if link is None:
        logger.warning(
            "order_notification_skipped_no_app_id: order %s assigned to "
            "judge %s — VK_APP_ID is not set, notifications not enqueued",
            order.id,
            judge_player_id,
        )
        return
    await BotService.enqueue(
        session,
        type_key=ORDER_JUDGE_ASSIGNED,
        player_id=judge_player_id,
        event_key=f"order_assigned:{order.id}",
        variables={
            "order_number": order.number,
            "nation_name": order.nation_name,
            "order_link": link,
        },
        event_at=distributed_at,
    )
    await BotService.enqueue(
        session,
        type_key=ORDER_DISTRIBUTED,
        player_id=order.author_player_id,
        event_key=f"order_distributed:{order.id}",
        variables={
            "order_number": order.number,
            "order_link": link,
        },
        event_at=distributed_at,
    )


async def notify_verdict(
    session: AsyncSession,
    *,
    order: Order,
    verdict_at: datetime,
) -> None:
    """
    Enqueue the ORDER_VERDICT_READY announcement to the author
    (Spec 5.1), stamped with ``event_at = verdict_at`` so TTL counts
    from the verdict moment. The text never carries the verdict's
    title or summary — only the number and the link.

    Without VK_APP_ID there is no link to send: enqueue nothing and
    log one warning (Appendix C). Skip results are ignored on
    purpose — an unreachable recipient is the bot's business, not
    the verdict's.
    """
    link = order_app_link(order.number)
    if link is None:
        logger.warning(
            "order_notification_skipped_no_app_id: verdict written on "
            "order %s — VK_APP_ID is not set, notification not enqueued",
            order.id,
        )
        return
    await BotService.enqueue(
        session,
        type_key=ORDER_VERDICT_READY,
        player_id=order.author_player_id,
        event_key=f"order_verdict:{order.id}",
        variables={
            "order_number": order.number,
            "order_link": link,
        },
        event_at=verdict_at,
    )


async def notify_reminder(
    session: AsyncSession,
    *,
    order: Order,
    judge_player_id: str,
    now: datetime,
) -> EnqueueResult | None:
    """
    Enqueue the ORDER_JUDGE_REMINDER for the judge (Spec 2.3 step 2),
    stamped ``event_at = now`` so TTL counts from the reminder pass.
    ``hours_left`` is the Spec 3.4 expression evaluated at ``now`` —
    ``max(1, ceil((deadline_at - now) / 3600 s))``.

    Without VK_APP_ID there is no link to send: enqueue nothing and
    log one warning — the same rule as the assignment pair (Appendix
    C). Returns the enqueue result; ``None`` on the missing-app-id
    skip. ``judge_player_id`` goes into the enqueue call only — never
    into a log line (INV-O5).
    """
    link = order_app_link(order.number)
    if link is None:
        logger.warning(
            "order_notification_skipped_no_app_id: reminder due for "
            "order %s — VK_APP_ID is not set, notification not "
            "enqueued",
            order.id,
        )
        return None
    deadline = order.deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    hours_left = max(1, math.ceil((deadline - now).total_seconds() / 3600))
    return await BotService.enqueue(
        session,
        type_key=ORDER_JUDGE_REMINDER,
        player_id=judge_player_id,
        event_key=f"order_reminder:{order.id}",
        variables={
            "order_number": order.number,
            "hours_left": hours_left,
            "order_link": link,
        },
        event_at=now,
    )
