"""
ORM models for module 04_orders.

Defines the module's single table of Spec Part 1:

- ``orders`` — one row per submitted order. The verdict is a column
  group of the same row (D1), the public number is stored (D2), and
  the order stage is derived from column fill, never stored (D4):
  ``SUBMITTED`` (no judge) -> ``DISTRIBUTED`` (judge, no verdict) ->
  ``VERDICT`` (verdict). Column-group consistency is enforced by the
  named CHECK constraints (INV-O2), not only by the service.

Data layer only: no business logic and no config access — balance lives
in ``configs/04_orders.yaml`` behind ``config_schema.py``. Foreign keys
point exclusively at ``players.id`` (INV-O7); ``nation_*`` is an
immutable snapshot taken at submission (INV-O6) and deliberately has no
FK. ``stage_of`` / ``is_overdue`` are pure functions over a loaded row.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CHAR,
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from modules._04_orders.config_schema import (
    SUMMARY_COLUMN_LENGTH,
    TITLE_COLUMN_LENGTH,
    URL_COLUMN_LENGTH,
)


class OrderStage(enum.StrEnum):
    """The derived stage of an order (Spec Part 1, D4) — not a column."""

    SUBMITTED = "SUBMITTED"
    DISTRIBUTED = "DISTRIBUTED"
    VERDICT = "VERDICT"


class Order(Base):
    """One player order with its judge assignment and verdict."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    author_player_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Snapshot of the author's nation at submission (INV-O6) — no FK.
    nation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    nation_name: Mapped[str] = mapped_column(String(100), nullable=False)
    nation_color: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    nation_short_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(TITLE_COLUMN_LENGTH), nullable=False)
    summary: Mapped[str] = mapped_column(String(SUMMARY_COLUMN_LENGTH), nullable=False)
    article_url: Mapped[str] = mapped_column(String(URL_COLUMN_LENGTH), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    judge_player_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    distributed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verdict_title: Mapped[str | None] = mapped_column(
        String(TITLE_COLUMN_LENGTH), nullable=True
    )
    verdict_summary: Mapped[str | None] = mapped_column(
        String(SUMMARY_COLUMN_LENGTH), nullable=True
    )
    verdict_url: Mapped[str | None] = mapped_column(
        String(URL_COLUMN_LENGTH), nullable=True
    )
    # Reserved for structured verdict effects — always NULL in v1
    # (INV-O13).
    verdict_effects: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verdict_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Player ids of the judges who refused this order (0.14.0 unit 7a)
    # — a plain JSON list of id strings, no FK: the automatic selector
    # only filters them out, and a deleted player stays listed.
    refused_judge_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    # The 1-based number of the current judge assignment: refusal bumps
    # it and the judge-facing bot event keys carry it from 2 on, so the
    # outbox dedupe never swallows the next judge's rows.
    assignment_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Term exemption (0.14.0 unit 7b): the verdict term is not
    # enforced for this order — no overdue mark, no refusal, no
    # seizure; a verdict is accepted at any time. Set by the seizure
    # itself (the order lands with an administrator) and by
    # ``admin_assign_judge`` — a manually assigned judge was never
    # told the term and must never be fined for it. The distribution
    # timestamps stay filled (the CHECKs demand them) but are no
    # longer enforced.
    term_exempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("number", name="uq_orders_number"),
        UniqueConstraint(
            "author_player_id",
            "client_request_id",
            name="uq_orders_author_client_request",
        ),
        CheckConstraint("number >= 1", name="ck_orders_number_positive"),
        CheckConstraint(
            "judge_player_id IS NULL OR judge_player_id <> author_player_id",
            name="ck_orders_judge_not_author",
        ),
        CheckConstraint(
            "(judge_player_id IS NULL AND distributed_at IS NULL "
            "AND deadline_at IS NULL AND reminder_at IS NULL) OR "
            "(judge_player_id IS NOT NULL AND distributed_at IS NOT NULL "
            "AND deadline_at IS NOT NULL AND reminder_at IS NOT NULL)",
            name="ck_orders_distribution_all_or_none",
        ),
        CheckConstraint(
            "deadline_at IS NULL OR "
            "(distributed_at < reminder_at AND reminder_at < deadline_at)",
            name="ck_orders_distribution_order",
        ),
        CheckConstraint(
            "(verdict_title IS NULL AND verdict_summary IS NULL "
            "AND verdict_url IS NULL AND verdict_at IS NULL) OR "
            "(verdict_title IS NOT NULL AND verdict_summary IS NOT NULL "
            "AND verdict_url IS NOT NULL AND verdict_at IS NOT NULL)",
            name="ck_orders_verdict_all_or_none",
        ),
        CheckConstraint(
            "verdict_at IS NULL OR judge_player_id IS NOT NULL",
            name="ck_orders_verdict_needs_judge",
        ),
        CheckConstraint(
            "verdict_at IS NULL OR verdict_at >= distributed_at",
            name="ck_orders_verdict_after_distribution",
        ),
        CheckConstraint(
            "reminder_sent_at IS NULL OR judge_player_id IS NOT NULL",
            name="ck_orders_reminder_needs_judge",
        ),
        CheckConstraint(
            "assignment_no >= 1", name="ck_orders_assignment_no_positive"
        ),
        # Judge's pending workload (INV-O4).
        Index(
            "ix_orders_pending_by_judge",
            "judge_player_id",
            postgresql_where=text("verdict_at IS NULL"),
            sqlite_where=text("verdict_at IS NULL"),
        ),
        # Distribution retry queue (Spec 2.3).
        Index(
            "ix_orders_unassigned",
            "submitted_at",
            postgresql_where=text("judge_player_id IS NULL"),
            sqlite_where=text("judge_player_id IS NULL"),
        ),
        # Reminder sweep (Spec 2.3).
        Index(
            "ix_orders_reminders_due",
            "reminder_at",
            postgresql_where=text("reminder_sent_at IS NULL AND verdict_at IS NULL"),
            sqlite_where=text("reminder_sent_at IS NULL AND verdict_at IS NULL"),
        ),
    )


def stage_of(order: Order) -> OrderStage:
    """Derived stage (Spec Part 1, D4): column fill decides."""
    if order.verdict_at is not None:
        return OrderStage.VERDICT
    if order.judge_player_id is not None:
        return OrderStage.DISTRIBUTED
    return OrderStage.SUBMITTED


def is_overdue(order: Order, now: datetime) -> bool:
    """Deadline passed and no verdict written yet (Spec Part 1).

    A term-exempt order is never overdue: its ``deadline_at`` exists
    for the CHECK group alone and is not enforced (0.14.0 unit 7b).
    Naive datetimes are read as UTC — the storage convention; SQLite
    returns naive values even for timezone=True columns, so a refreshed
    row must compare cleanly against an aware ``now``.
    """
    if order.term_exempt:
        return False
    deadline_at = order.deadline_at
    if deadline_at is not None and deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=UTC)
    return order.verdict_at is None and deadline_at is not None and now > deadline_at
