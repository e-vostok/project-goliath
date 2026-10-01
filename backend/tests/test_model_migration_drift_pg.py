"""
Model/migration drift guard — PostgreSQL edition.

Same contract as test_model_migration_drift.py but against real
PostgreSQL: ``pg_schema`` wipes the *_test database and applies Alembic
migrations, then ``compare_metadata`` must report no differences between
the migrated schema and ``Base.metadata``.

Only ONE diff class is tolerated: ``SQLEnum(native_enum=False)`` is
stored as ``VARCHAR`` by design, and no database can reflect a Python
Enum type back. Unlike the SQLite guard, DateTime/timezone diffs are NOT
suppressed here — PostgreSQL reflects ``timestamp with time zone``
faithfully, so a tz diff would be real drift.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine.url import make_url

from core.db import Base
import modules._00_core.models  # noqa: F401 — registers all ORM tables
from tests.fixtures.postgres import (
    pg_schema,  # noqa: F401 — session fixture: wipe + alembic upgrade
    pg_url,  # noqa: F401 — resolved through the fixture chain
)

pytestmark = pytest.mark.postgres


def _is_known_equivalent(diff) -> bool:
    """True only when EVERY op is the documented Enum→VARCHAR artifact."""
    ops = diff if isinstance(diff, list) else [diff]
    return bool(ops) and all(_op_is_known_equivalent(op) for op in ops)


def _op_is_known_equivalent(op) -> bool:
    if not isinstance(op, tuple) or op[0] != "modify_type" or len(op) < 2:
        return False
    inspected_type, metadata_type = op[-2], op[-1]
    # SQLEnum(native_enum=False) stores as VARCHAR by design. No
    # DateTime suppression: on PostgreSQL a timezone diff is real.
    return (
        isinstance(metadata_type, sa.Enum)
        and not metadata_type.native_enum
        and isinstance(inspected_type, sa.String)
    )


def test_no_model_migration_drift_on_postgres(pg_schema):
    """The migrated PostgreSQL schema must structurally match Base.metadata."""
    sync_url = make_url(pg_schema).set(
        drivername="postgresql+psycopg2"
    ).render_as_string(hide_password=False)
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            diffs = compare_metadata(
                MigrationContext.configure(conn), Base.metadata
            )
    finally:
        engine.dispose()

    unexpected = [d for d in diffs if not _is_known_equivalent(d)]
    assert unexpected == [], (
        f"model/migration drift detected on PostgreSQL: {unexpected}"
    )
