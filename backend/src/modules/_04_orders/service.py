"""
Public service API of module 04_orders (Spec 2.5, 3.5, 5.1).

``submit`` runs the Spec 5.1 check order: module advisory lock
(PostgreSQL) -> idempotent repeat on ``(author, client_request_id)``
(INV-O9) -> author owns a nation (snapshot source, INV-O6) -> author's
unresolved-orders limit (INV-O15) -> field rules -> insert with the
public number ``1 + max(0, max(number))`` retried under a SAVEPOINT on a
unique violation (Spec 3.5). The service never commits — the caller owns
the transaction boundary.

Nothing here exposes the judge: no view carries ``judge_player_id`` or
any player identifier of the judge (INV-O5); ``can_write_verdict`` is
computed per viewer and stays ``False`` until the verdict endpoint
exists (Issue 7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService
from modules._04_orders.exceptions import (
    OrderAuthorLimitReachedError,
    OrderNationRequiredError,
    OrderNotFoundError,
    OrderNumberConflictError,
)
from modules._04_orders.models import Order, is_overdue
from modules._04_orders.rules import (
    validate_article_url,
    validate_summary,
    validate_title,
)

logger = logging.getLogger(__name__)

# PostgreSQL advisory-lock key serializing submissions (and, from
# Issue 6 on, distribution) across every process sharing the database
# ('ORDERS' as ASCII hex). Must fit bigint; no-op dialects skip it.
ORDERS_ADVISORY_LOCK_KEY = 0x4F5244455253

# Spec 3.5: attempts to assign the public number on a UNIQUE collision.
NUMBER_ATTEMPTS = 5


@dataclass(frozen=True)
class OrderDetailView:
    """One order as a viewer sees it (Spec 5.2 ``OrderDetailDTO``)."""

    number: int
    nation_name: str
    nation_color: str
    title: str
    summary: str
    article_url: str
    distributed: bool
    verdict_title: str | None
    verdict_summary: str | None
    verdict_url: str | None
    overdue: bool
    can_write_verdict: bool


@dataclass(frozen=True)
class SubmitOutcome:
    """
    ``submit`` result: the order view plus whether it was just created
    — an idempotent repeat (same ``client_request_id``) returns the
    stored order with ``created=False`` (INV-O9).
    """

    view: OrderDetailView
    created: bool


@dataclass(frozen=True)
class RegistryOrderView:
    """
    One orders-table row for the Registry source (Spec Appendix A):
    the public number, the nation snapshot, the title and the three
    stage timestamps. ``deadline_at`` rides along for the overdue mark —
    no judge field, ever (INV-O5).
    """

    number: int
    nation_name: str
    nation_color: str
    title: str
    submitted_at: datetime
    distributed_at: datetime | None
    deadline_at: datetime | None
    verdict_at: datetime | None


def _detail_view(order: Order, *, now: datetime) -> OrderDetailView:
    """The detail DTO payload for a loaded row."""
    return OrderDetailView(
        number=order.number,
        nation_name=order.nation_name,
        nation_color=order.nation_color,
        title=order.title,
        summary=order.summary,
        article_url=order.article_url,
        distributed=order.judge_player_id is not None,
        verdict_title=order.verdict_title,
        verdict_summary=order.verdict_summary,
        verdict_url=order.verdict_url,
        overdue=is_overdue(order, now),
        # Issue 4 scope: nobody can write a verdict yet (INV-O5 keeps
        # the judge invisible; the real check arrives with Issue 7).
        can_write_verdict=False,
    )


def _is_number_conflict(exc: IntegrityError) -> bool:
    """
    True when the failed insert violated ``uq_orders_number``.

    asyncpg exposes ``constraint_name`` on the driver error; drivers
    without it fall back to the message — sqlite3 names the
    ``orders.number`` column list, PostgreSQL names the
    ``uq_orders_number`` constraint. A violation of any other
    constraint (e.g. the idempotency key) is re-raised by the caller.
    """
    orig = exc.orig
    constraint = getattr(orig, "constraint_name", None)
    if constraint is not None:
        return constraint == "uq_orders_number"
    # Message fallback: sqlite3 names the column list ("orders.number"),
    # PostgreSQL drivers without ``constraint_name`` name the constraint
    # itself ("uq_orders_number") — both markers identify the same
    # unique-number violation.
    return "orders.number" in str(orig) or "uq_orders_number" in str(orig)


class OrderService:
    """Public operations on the ``orders`` table."""

    @staticmethod
    async def submit(
        session: AsyncSession,
        *,
        player_id: str,
        client_request_id: str,
        title: str,
        summary: str,
        article_url: str,
    ) -> SubmitOutcome:
        """
        Accept an order from a nation owner (Spec 5.1 check order).

        The module advisory lock serializes the idempotency probe, the
        author-limit count and the number assignment on PostgreSQL —
        two concurrent submissions of one author with a single free slot
        cannot both pass (INV-O15); on SQLite the single writer needs no
        lock. Never commits.
        """
        from modules._04_orders.startup import (
            get_orders_allowed_hosts,
            get_orders_config,
        )

        config = get_orders_config()

        # 1. Module lock — the whole check-then-insert sequence is
        # serialized per database, so counts and numbers are stable.
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": ORDERS_ADVISORY_LOCK_KEY},
            )

        # 2. Idempotent repeat: same (author, client_request_id) returns
        # the stored order and creates nothing (INV-O9). Runs before the
        # author-limit check — a repeat at the limit still answers 200.
        existing = (
            await session.execute(
                select(Order).where(
                    Order.author_player_id == player_id,
                    Order.client_request_id == client_request_id,
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is not None:
            return SubmitOutcome(_detail_view(existing, now=now), False)

        # 3. The author must own a nation; its id/name/colour are stored
        # as the immutable snapshot (INV-O6).
        nation = await NationService.player_nation_summary(
            session, player_id
        )
        if nation is None:
            raise OrderNationRequiredError()

        # 4. Author limit: unresolved = any order without a verdict —
        # submitted, distributed and overdue all count (D14, INV-O15).
        unresolved = await OrderService.unresolved_count(
            session, player_id=player_id
        )
        if unresolved >= config.author.max_unresolved_orders:
            raise OrderAuthorLimitReachedError(
                config.author.max_unresolved_orders
            )

        # 5. Field rules (Spec 2.5) — normalized values get stored.
        title = validate_title(title, config)
        summary = validate_summary(summary, config)
        article_url = validate_article_url(
            article_url, config, allowed_hosts=get_orders_allowed_hosts()
        )

        # 6. Insert, assigning the public number in this transaction
        # (Spec 3.5): 1 + max(0, max(number)), retried under a SAVEPOINT
        # on a unique violation so a racing insert costs a retry, not
        # the whole submission.
        order = await OrderService._insert_numbered(
            session,
            player_id=player_id,
            client_request_id=client_request_id,
            nation=nation,
            title=title,
            summary=summary,
            article_url=article_url,
            submitted_at=now,
        )
        # The distribution attempt under its own SAVEPOINT arrives with
        # Issue 6 (Spec 5.1 final step); a submission always succeeds or
        # fails on the order itself (INV-O8).
        return SubmitOutcome(_detail_view(order, now=now), True)

    @staticmethod
    async def _insert_numbered(
        session: AsyncSession,
        *,
        player_id: str,
        client_request_id: str,
        nation,
        title: str,
        summary: str,
        article_url: str,
        submitted_at: datetime,
    ) -> Order:
        """Insert with ``number = 1 + max(0, max(number))``; retry on
        ``uq_orders_number`` collisions up to ``NUMBER_ATTEMPTS``."""
        for _ in range(NUMBER_ATTEMPTS):
            number = await session.scalar(
                select(func.coalesce(func.max(Order.number), 0) + 1)
            )
            try:
                async with session.begin_nested():
                    order = Order(
                        number=number,
                        author_player_id=player_id,
                        client_request_id=client_request_id,
                        nation_id=nation.nation_id,
                        nation_name=nation.name,
                        nation_color=nation.color_hex,
                        title=title,
                        summary=summary,
                        article_url=article_url,
                        submitted_at=submitted_at,
                    )
                    session.add(order)
                    await session.flush()
                return order
            except IntegrityError as exc:
                if not _is_number_conflict(exc):
                    raise
        logger.error("order number assignment exhausted %s attempts",
                     NUMBER_ATTEMPTS)
        raise OrderNumberConflictError()

    @staticmethod
    async def get_detail(
        session: AsyncSession, *, number: int, viewer_player_id: str
    ) -> OrderDetailView:
        """
        The order's public detail by number — 404 ``ORDER_NOT_FOUND``
        when absent. ``viewer_player_id`` selects ``can_write_verdict``;
        until the verdict endpoint exists it is always ``False``.
        """
        order = (
            await session.execute(
                select(Order).where(Order.number == number)
            )
        ).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(number)
        return _detail_view(order, now=datetime.now(timezone.utc))

    @staticmethod
    async def list_for_registry(
        session: AsyncSession,
    ) -> list[RegistryOrderView]:
        """
        Every order for the Registry source (Spec Appendix A), newest
        first. No judge fields — the view cannot leak them (INV-O5).
        Read-only, never commits.
        """
        result = await session.execute(
            select(
                Order.number,
                Order.nation_name,
                Order.nation_color,
                Order.title,
                Order.submitted_at,
                Order.distributed_at,
                Order.deadline_at,
                Order.verdict_at,
            ).order_by(Order.number.desc())
        )
        return [
            RegistryOrderView(
                number=row[0],
                nation_name=row[1],
                nation_color=row[2],
                title=row[3],
                submitted_at=row[4],
                distributed_at=row[5],
                deadline_at=row[6],
                verdict_at=row[7],
            )
            for row in result.all()
        ]

    @staticmethod
    async def unresolved_count(
        session: AsyncSession, *, player_id: str
    ) -> int:
        """
        The author's orders without a verdict — the ``unresolved_orders``
        counter of ``GET /orders/rules`` and the submit limit (INV-O15).
        """
        result = await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.author_player_id == player_id,
                Order.verdict_at.is_(None),
            )
        )
        return result.scalar_one()
