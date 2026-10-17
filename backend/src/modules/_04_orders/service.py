"""
Public service API of module 04_orders (Spec 2.5, 3.3, 3.5, 5.1).

``submit`` runs the Spec 5.1 check order: module advisory lock
(PostgreSQL) -> idempotent repeat on ``(author, client_request_id)``
(INV-O9) -> author owns a nation (snapshot source, INV-O6) -> author's
unresolved-orders limit (INV-O15) -> field rules -> insert with the
public number ``1 + max(0, max(number))`` retried under a SAVEPOINT on a
unique violation (Spec 3.5) -> a best-effort distribution attempt under
its own SAVEPOINT, logged and swallowed on failure (INV-O8). The service
never commits — the caller owns the transaction boundary.

``distribute`` runs the Spec 3.3 steps on one order: the same advisory
lock (re-entrant, so ``submit`` can call it), a re-read under the lock,
candidates via ``PlayerService`` and ``BotService``, one aggregating
workload query, the injected selector, a conditional ``UPDATE ... WHERE
judge_player_id IS NULL`` and the two assignment notifications.

``write_verdict`` runs the Spec 5.1 check order on one order: the
advisory lock, existence, the caller-is-judge check — one and the same
``ORDER_VERDICT_FORBIDDEN`` for every other cause (INV-O5) — no
verdict yet, the field rules, then a conditional ``UPDATE ... WHERE
judge_player_id = :caller AND verdict_at IS NULL`` that touches the
four verdict columns and nothing else (INV-O1), and the author's
announcement under its own SAVEPOINT (INV-O8).

``run_retry_pass`` is the worker's step (Spec 2.3): it owns its own
sessions — one to pick the candidates, then one transaction per order
— and returns :class:`RetryPassStats`.

Nothing here exposes the judge: no view carries ``judge_player_id`` or
any player identifier of the judge (INV-O5); ``can_write_verdict`` is
computed per viewer — true only for the assigned judge while no verdict
exists.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import delete, false, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService, PlayerService
from modules._02_bot.service import BotService, EnqueueResult
from modules._04_orders import distribution
from modules._04_orders.distribution import JudgeCandidate
from modules._04_orders.exceptions import (
    OrderAuthorLimitReachedError,
    OrderNationRequiredError,
    OrderNotFoundError,
    OrderNumberConflictError,
    OrderVerdictExistsError,
    OrderVerdictForbiddenError,
)
from modules._04_orders.models import Order, is_overdue
from modules._04_orders.notifications import (
    notify_assignment,
    notify_reminder,
    notify_verdict,
)
from modules._04_orders.rules import (
    validate_article_url,
    validate_summary,
    validate_title,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

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


class DistributeResult(str, Enum):
    """The outcome of one distribution attempt (Spec 2.5, 3.3)."""

    ASSIGNED = "ASSIGNED"
    NO_CANDIDATES = "NO_CANDIDATES"  # приказ остаётся без судьи
    ALREADY_ASSIGNED = "ALREADY_ASSIGNED"


@dataclass(frozen=True)
class AssignedOrderView:
    """
    One order awaiting the caller's verdict (Spec 2.5) — the judge's
    queue. ``deadline_at`` is never NULL: the assignment columns are
    all-or-none (INV-O4). No judge fields (INV-O5).
    """

    number: int
    nation_name: str
    nation_color: str
    title: str
    summary: str
    article_url: str
    deadline_at: datetime
    overdue: bool


@dataclass(frozen=True)
class RetryPassStats:
    """
    The counters of one ``run_retry_pass`` (Spec 2.3).

    ``assigned`` waiting orders got a judge this pass,
    ``still_waiting`` found no candidate, ``reminders_sent`` reminder
    messages were put into the bot outbox, ``reminders_skipped`` due
    reminders produced none (the deadline had already passed, no
    VK_APP_ID, the bot skipped the recipient, or a racing pass marked
    the row first) and ``errors`` per-order transactions failed — each
    is logged and the pass continues with the next order. No judge
    field ever leaves the service (INV-O5).
    """

    assigned: int = 0
    still_waiting: int = 0
    reminders_sent: int = 0
    reminders_skipped: int = 0
    errors: int = 0


def _aware(moment: datetime) -> datetime:
    """Naive datetimes are read as UTC (storage convention)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _detail_view(
    order: Order, *, now: datetime, viewer_player_id: str
) -> OrderDetailView:
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
        # Spec 5.2: the button is offered to the assigned judge alone,
        # and only while no verdict exists (INV-O5 hides who that is).
        can_write_verdict=(
            order.judge_player_id is not None
            and order.judge_player_id == viewer_player_id
            and order.verdict_at is None
        ),
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
        now = datetime.now(UTC)
        if existing is not None:
            return SubmitOutcome(
                _detail_view(existing, now=now, viewer_player_id=player_id),
                False,
            )

        # 3. The author must own a nation; its id/name/colour are stored
        # as the immutable snapshot (INV-O6).
        nation = await NationService.player_nation_summary(session, player_id)
        if nation is None:
            raise OrderNationRequiredError()

        # 4. Author limit: unresolved = any order without a verdict —
        # submitted, distributed and overdue all count (D14, INV-O15).
        unresolved = await OrderService.unresolved_count(session, player_id=player_id)
        if unresolved >= config.author.max_unresolved_orders:
            raise OrderAuthorLimitReachedError(config.author.max_unresolved_orders)

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

        # 7. Distribution attempt under its own SAVEPOINT (Spec 5.1
        # final step): any failure — the order's, the selector's or a
        # notification's — is logged and swallowed; the submission
        # stands on its own (INV-O8).
        try:
            async with session.begin_nested():
                await OrderService.distribute(session, order.id, now=now)
        except Exception:
            logger.exception("distribution attempt failed for order %s", order.id)
        # The stored row is the truth for the response — the attempt may
        # have assigned the judge or rolled its writes back entirely.
        await session.refresh(order)
        return SubmitOutcome(
            _detail_view(order, now=now, viewer_player_id=player_id), True
        )

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
        logger.error("order number assignment exhausted %s attempts", NUMBER_ATTEMPTS)
        raise OrderNumberConflictError()

    @staticmethod
    async def get_detail(
        session: AsyncSession, *, number: int, viewer_player_id: str
    ) -> OrderDetailView:
        """
        The order's public detail by number — 404 ``ORDER_NOT_FOUND``
        when absent. ``viewer_player_id`` selects ``can_write_verdict``:
        true only for the assigned judge while no verdict exists.
        """
        order = (
            await session.execute(select(Order).where(Order.number == number))
        ).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(number)
        return _detail_view(
            order,
            now=datetime.now(UTC),
            viewer_player_id=viewer_player_id,
        )

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
    async def distribute(
        session: AsyncSession,
        order_id: str,
        *,
        now: datetime | None = None,
    ) -> DistributeResult:
        """
        Give one order its anonymous judge, if a candidate exists
        (Spec 3.3, steps 1–8).

        The module advisory lock serializes the attempt with submissions
        and other attempts; ``pg_advisory_xact_lock`` is re-entrant
        inside one transaction, so ``submit`` calling us never
        deadlocks. SQLite's single writer needs no lock. Called inside
        the caller's SAVEPOINT — never commits, and a failure rolls back
        only this attempt (INV-O8): an order without a judge simply
        waits for the next attempt.
        """
        from modules._04_orders.startup import get_orders_config

        judge = get_orders_config().judge

        # 1. Module lock — same key as submit.
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": ORDERS_ADVISORY_LOCK_KEY},
            )

        # 2. Re-read under the lock; a judge already present means the
        # assignment is done — nothing to do.
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one()
        if order.judge_player_id is not None:
            return DistributeResult.ALREADY_ASSIGNED

        # 3. Candidates: every player with rating and nation ownership —
        # through PlayerService only, never a direct read (INV-O7).
        players = await PlayerService.list_for_registry(session)

        # 4. Reachability (only when the config asks for it): a nation
        # counts on its own; players without one must have consented to
        # bot messages — otherwise the judge could never be told.
        consented: set[str] = set()
        if judge.require_reachable:
            consented = await BotService.consented_player_ids(
                session,
                [r.player_id for r in players if r.nation_id is None],
            )

        # 5. One aggregating query — pending verdicts P and the latest
        # assignment τ for every judge (Spec 3.1).
        stats = await session.execute(
            select(
                Order.judge_player_id,
                func.count().filter(Order.verdict_at.is_(None)),
                func.max(Order.distributed_at),
            )
            .where(Order.judge_player_id.is_not(None))
            .group_by(Order.judge_player_id)
        )
        pending_by: dict[str, int] = {}
        last_by: dict[str, datetime] = {}
        for judge_id, pending, last_at in stats.all():
            pending_by[judge_id] = pending
            last_by[judge_id] = last_at

        # 6. Build candidates and let the selector pick (the module-
        # level reference is the injection point for tests).
        candidates = [
            JudgeCandidate(
                player_id=row.player_id,
                rating=row.judge_rating,
                has_nation=row.nation_id is not None,
                consented=row.player_id in consented,
                pending=pending_by.get(row.player_id, 0),
                last_assigned_at=last_by.get(row.player_id),
            )
            for row in players
        ]
        judge_player_id = distribution.judge_selector(
            order.author_player_id, candidates, judge
        )
        if judge_player_id is None:
            return DistributeResult.NO_CANDIDATES

        # 7. Conditional assignment (INV-O1): the row is only claimed
        # while judge_player_id IS NULL. The deadline and reminder
        # timestamps are fixed now by integer arithmetic (Spec 3.4) and
        # never move, whatever the config becomes later.
        distributed_at = now if now is not None else datetime.now(UTC)
        result = await session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                Order.judge_player_id.is_(None),
            )
            .values(
                judge_player_id=judge_player_id,
                distributed_at=distributed_at,
                deadline_at=distributed_at + timedelta(seconds=judge.deadline_seconds),
                reminder_at=distributed_at + timedelta(seconds=judge.reminder_seconds),
            )
        )
        if result.rowcount == 0:
            # A racing attempt claimed the row between the re-read and
            # the update — treat it like an already-assigned order.
            return DistributeResult.ALREADY_ASSIGNED

        # 8. The assignment pair — judge and author — stamped with the
        # assignment moment, not the enqueue moment (Spec 3.3 step 8).
        # The texts never carry the player-written title or summary.
        await notify_assignment(
            session,
            order=order,
            judge_player_id=judge_player_id,
            distributed_at=distributed_at,
        )
        return DistributeResult.ASSIGNED

    @staticmethod
    async def run_retry_pass(
        session_factory: SessionFactory,
        *,
        now: datetime | None = None,
    ) -> RetryPassStats:
        """
        One background pass of Spec 2.3 — the worker's step and a
        standalone testable unit.

        Part A, distribution retry: up to ``distribution.batch_size``
        judge-less orders, oldest ``(submitted_at, number)`` first; each
        retried in its own session and transaction with ``distribute``
        under a SAVEPOINT, then committed. A failure of one order is
        logged, counted and never stops the pass.

        Part B, reminders: orders with ``reminder_at <= now``,
        ``reminder_sent_at IS NULL`` and no verdict — the same per-order
        transaction pattern. A conditional ``UPDATE`` claims the row
        (rowcount 0 = another pass beat us to it, or a verdict landed
        between the candidate read and the claim); ``now < deadline_at``
        enqueues ``ORDER_JUDGE_REMINDER`` to the judge stamped
        ``event_at = now``, a deadline already passed logs INFO and
        enqueues nothing — either way the claim marks
        ``reminder_sent_at = now`` so a reminder is handled once.

        Each part reads its candidates in one session and works every
        order in a fresh one: correct under concurrent passes (the
        advisory lock serializes ``distribute``, the conditional UPDATE
        serializes the reminder claim) and a slow order never holds a
        transaction open across the whole batch. Never raises for a
        single bad order.
        """
        from modules._04_orders.startup import get_orders_config

        batch_size = get_orders_config().distribution.batch_size
        moment = now if now is not None else datetime.now(UTC)
        assigned = still_waiting = 0
        reminders_sent = reminders_skipped = errors = 0

        # Part A — retry the judge-less orders in submission order.
        async with session_factory() as session:
            waiting_ids = (
                (
                    await session.execute(
                        select(Order.id)
                        .where(Order.judge_player_id.is_(None))
                        .order_by(Order.submitted_at, Order.number)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )

        for order_id in waiting_ids:
            try:
                async with session_factory() as session:
                    async with session.begin():
                        result = await OrderService._distribute_guarded(
                            session, order_id, now=moment
                        )
            except Exception:
                errors += 1
                logger.exception(
                    "04_orders retry pass: distribute failed for order %s",
                    order_id,
                )
                continue
            if result is DistributeResult.ASSIGNED:
                assigned += 1
            elif result is DistributeResult.NO_CANDIDATES:
                still_waiting += 1

        # Part B — the reminder sweep over due, unclaimed, undecided
        # orders, oldest reminder first.
        async with session_factory() as session:
            due = (
                (
                    await session.execute(
                        select(Order)
                        .where(
                            Order.reminder_at <= moment,
                            Order.reminder_sent_at.is_(None),
                            Order.verdict_at.is_(None),
                        )
                        .order_by(Order.reminder_at)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )

        for order in due:
            try:
                async with session_factory() as session:
                    async with session.begin():
                        outcome = await OrderService._remind_guarded(
                            session, order, now=moment
                        )
            except Exception:
                errors += 1
                logger.exception(
                    "04_orders retry pass: reminder failed for order %s",
                    order.id,
                )
                continue
            if outcome == "sent":
                reminders_sent += 1
            else:
                reminders_skipped += 1

        return RetryPassStats(
            assigned=assigned,
            still_waiting=still_waiting,
            reminders_sent=reminders_sent,
            reminders_skipped=reminders_skipped,
            errors=errors,
        )

    @staticmethod
    async def _distribute_guarded(
        session: AsyncSession, order_id: str, *, now: datetime
    ) -> DistributeResult:
        """
        One ``distribute`` attempt inside the caller's transaction,
        wrapped in a SAVEPOINT so its failure rolls back only this
        order's writes. The SQLite guard is the same as in
        ``BotService.enqueue``: the driver opens the connection-level
        transaction lazily on the first DML, so a SAVEPOINT issued
        before any statement would escape the transaction (its
        RELEASE commits) — a no-op DELETE forces it open.
        """
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(Order).where(false()))
        async with session.begin_nested():
            return await OrderService.distribute(session, order_id, now=now)

    @staticmethod
    async def _remind_guarded(
        session: AsyncSession, order: Order, *, now: datetime
    ) -> str:
        """
        One reminder inside the caller's transaction under a SAVEPOINT
        (Spec 2.3 step 2). Returns ``"sent"`` only when a reminder row
        went into the bot outbox — every other claimed-or-lost outcome
        is a skip the caller counts.

        The conditional UPDATE is the multi-process guard: it claims
        the row only while ``reminder_sent_at IS NULL`` and no verdict
        exists, so two racing passes cannot remind twice — and a
        verdict written between the pass's candidate read and this
        claim wins the row (rowcount 0, no reminder for a decided
        order). ``judge_player_id`` leaves this method only into
        ``BotService.enqueue`` — never into a log line (INV-O5).
        """
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(Order).where(false()))
        async with session.begin_nested():
            claimed = await session.execute(
                update(Order)
                .where(
                    Order.id == order.id,
                    Order.reminder_sent_at.is_(None),
                    Order.verdict_at.is_(None),
                )
                .values(reminder_sent_at=now)
            )
            if claimed.rowcount == 0:
                # Another pass marked the row first — or a verdict
                # landed after the candidate read: either way the
                # reminder is not ours to send.
                return "skipped"
            if _aware(order.deadline_at) <= now:
                logger.info(
                    "order %s reminder skipped: the verdict deadline "
                    "has already passed",
                    order.id,
                )
                return "skipped"
            result = await notify_reminder(
                session,
                order=order,
                judge_player_id=order.judge_player_id,
                now=now,
            )
        return "sent" if result is EnqueueResult.QUEUED else "skipped"

    @staticmethod
    async def list_assigned(
        session: AsyncSession, *, player_id: str
    ) -> list[AssignedOrderView]:
        """
        The caller's orders still awaiting a verdict, soonest deadline
        first — the judge's queue (Spec 5.2). No judge fields are ever
        read out; the judge is the caller. Read-only, never commits.
        """
        result = await session.execute(
            select(Order)
            .where(
                Order.judge_player_id == player_id,
                Order.verdict_at.is_(None),
            )
            .order_by(Order.deadline_at)
        )
        now = datetime.now(UTC)
        return [
            AssignedOrderView(
                number=order.number,
                nation_name=order.nation_name,
                nation_color=order.nation_color,
                title=order.title,
                summary=order.summary,
                article_url=order.article_url,
                deadline_at=order.deadline_at,
                overdue=is_overdue(order, now),
            )
            for order in result.scalars()
        ]

    @staticmethod
    async def write_verdict(
        session: AsyncSession,
        *,
        player_id: str,
        number: int,
        title: str,
        summary: str,
        article_url: str,
    ) -> OrderDetailView:
        """
        Write the verdict of an order (Spec 5.1 check order).

        The module advisory lock serializes the verdict with
        submissions and other verdict attempts on PostgreSQL — two
        racing writes cannot both land (INV-O1). The refusal for a
        non-judge caller is one and the same for every cause — no
        judge yet, the author, a stranger — so nothing about the
        assignment leaks (INV-O5). Never commits; the caller owns the
        transaction boundary. Returns the detail as the judge sees it.
        """
        from modules._04_orders.startup import (
            get_orders_allowed_hosts,
            get_orders_config,
        )

        config = get_orders_config()

        # 1. Module lock — same key as submit and distribute.
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": ORDERS_ADVISORY_LOCK_KEY},
            )

        # 2. The order exists.
        order = (
            await session.execute(select(Order).where(Order.number == number))
        ).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(number)

        # 3. The caller is the assigned judge — otherwise one and the
        # same refusal, whatever the true cause (INV-O5).
        if order.judge_player_id != player_id:
            raise OrderVerdictForbiddenError()

        # 4. No verdict yet.
        if order.verdict_at is not None:
            raise OrderVerdictExistsError(number)

        # 5. Field rules (Spec 2.5) — the same limits as an order.
        title = validate_title(title, config)
        summary = validate_summary(summary, config)
        article_url = validate_article_url(
            article_url, config, allowed_hosts=get_orders_allowed_hosts()
        )

        # 6. Conditional write (INV-O1): the four verdict columns and
        # nothing else, only while the row is still this judge's to
        # decide.
        verdict_at = datetime.now(UTC)
        result = await session.execute(
            update(Order)
            .where(
                Order.id == order.id,
                Order.judge_player_id == player_id,
                Order.verdict_at.is_(None),
            )
            .values(
                verdict_title=title,
                verdict_summary=summary,
                verdict_url=article_url,
                verdict_at=verdict_at,
            )
        )
        if result.rowcount == 0:
            # The row changed between the read and the update — re-read
            # and answer for the state that actually won.
            fresh = (
                await session.execute(select(Order).where(Order.id == order.id))
            ).scalar_one()
            if fresh.verdict_at is not None:
                raise OrderVerdictExistsError(number)
            raise OrderVerdictForbiddenError()
        await session.refresh(order)

        # 7. The author's announcement under its own SAVEPOINT (INV-O8):
        # a failure or a skip must never undo the verdict.
        try:
            async with session.begin_nested():
                await notify_verdict(session, order=order, verdict_at=verdict_at)
        except Exception:
            logger.exception("verdict notification failed for order %s", order.id)

        return _detail_view(order, now=verdict_at, viewer_player_id=player_id)

    @staticmethod
    async def unresolved_count(session: AsyncSession, *, player_id: str) -> int:
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
