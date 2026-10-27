"""
Module 04_orders data-layer tests (Spec Part 1, Appendix T «Модель и
миграция»).

Two halves against real databases — no mocks (Anti-Mock Guard):

- the ``orders`` CHECK groups reject violating rows on the in-memory
  test database while ``make_order``'s default order inserts cleanly;
- migration 0010 creates only ``orders`` with its constraints and
  indexes on a real SQLite file, ``downgrade -1`` drops exactly that
  table and a re-upgrade restores it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from alembic import command
from modules._04_orders.models import OrderStage, is_overdue, stage_of
from tests.fixtures.factories import PlayerFactory, make_order, utcnow

BACKEND_DIR = Path(__file__).resolve().parents[1]

ORDERS_CHECKS = {
    "ck_orders_number_positive",
    "ck_orders_judge_not_author",
    "ck_orders_distribution_all_or_none",
    "ck_orders_distribution_order",
    "ck_orders_verdict_all_or_none",
    "ck_orders_verdict_needs_judge",
    "ck_orders_verdict_after_distribution",
    "ck_orders_reminder_needs_judge",
}

ORDERS_INDEXES = {
    "ix_orders_author_player_id",
    "ix_orders_judge_player_id",
    "ix_orders_pending_by_judge",
    "ix_orders_unassigned",
    "ix_orders_reminders_due",
}


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "judge_is_author",
        "distribution_halfway",
        "verdict_without_judge",
    ],
)
async def test_order_check_groups(test_db_session, case):
    """Each CHECK group rejects its violating row; the default
    ``make_order`` row inserts as a valid SUBMITTED order (INV-O2)."""
    player = PlayerFactory.build(nations=[])
    test_db_session.add(player)
    await test_db_session.flush()

    now = utcnow()
    overrides = {
        "valid": {},
        # ck_orders_judge_not_author: the judge equals the author.
        "judge_is_author": {"judge": player},
        # ck_orders_distribution_all_or_none: a distribution timestamp
        # is set while the judge column group stays empty.
        "distribution_halfway": {"distributed_at": now},
        # ck_orders_verdict_needs_judge: a verdict without a judge.
        "verdict_without_judge": {"verdict_at": now},
    }[case]

    if case == "valid":
        order = await make_order(test_db_session, player, **overrides)
        assert order.judge_player_id is None
        assert stage_of(order) == OrderStage.SUBMITTED
        assert is_overdue(order, now + timedelta(days=365)) is False
    else:
        with pytest.raises(IntegrityError):
            await make_order(test_db_session, player, **overrides)


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


def test_migration_0010_up_down_up(tmp_path, monkeypatch):
    """0010 creates only ``orders``; downgrading past it drops exactly
    that table and a re-upgrade restores it (Spec Part 1 «Миграция»).
    The explicit ``0009`` target steps over 0011 (its columns live on
    ``nations``, not on a table of their own)."""
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    command.upgrade(cfg, "head")
    before = _tables(url)
    assert "orders" in before

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            checks = {c["name"] for c in insp.get_check_constraints("orders")}
            indexes = {i["name"] for i in insp.get_indexes("orders")}
    finally:
        engine.dispose()
    assert ORDERS_CHECKS <= checks
    assert ORDERS_INDEXES <= indexes

    command.downgrade(cfg, "0009")
    # 0015's admin tables ride the same downgrade path.
    assert _tables(url) == before - {"orders", "admin_grants", "admin_audit_log", "registry_player_numbers", "registry_number_counter"}

    command.upgrade(cfg, "head")
    assert "orders" in _tables(url)
