"""
Model/migration drift guard.

Runs ``alembic upgrade head`` on a fresh SQLite file, then asserts
``compare_metadata`` reports no differences between the migrated schema
and ``Base.metadata`` — excluding two documented equivalences that no
migration can ever reconcile:

- ``SQLEnum(native_enum=False)`` is stored as ``VARCHAR`` by design;
  reflection can never produce a Python ``Enum`` type back.
- SQLite ``TIMESTAMP``/``DATETIME`` columns cannot reflect timezone
  awareness, so ``DateTime(timezone=True)`` always reads back as a
  plain datetime type.

Any other difference — missing or extra columns, tables, indexes,
constraints, foreign keys — fails the suite. This test exists because
migrations 0001-0003 shipped FK and PK drift that only a real
comparison could see.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from core.db import Base
import modules._00_core.models  # noqa: F401 — registers all ORM tables
import modules._01_map.models  # noqa: F401 — registers all ORM tables

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _is_known_equivalent(diff) -> bool:
    """
    True only when EVERY op in the diff is a documented reflection
    artifact — a diff list containing anything else fails the guard.
    """
    ops = diff if isinstance(diff, list) else [diff]
    return bool(ops) and all(_op_is_known_equivalent(op) for op in ops)


def _op_is_known_equivalent(op) -> bool:
    if not isinstance(op, tuple) or op[0] != "modify_type" or len(op) < 2:
        return False
    inspected_type, metadata_type = op[-2], op[-1]

    # SQLEnum(native_enum=False) stores as VARCHAR by design.
    if isinstance(metadata_type, sa.Enum) and not metadata_type.native_enum:
        return isinstance(inspected_type, sa.String)

    # This guard runs on SQLite only, where tz-aware datetimes can never
    # reflect their timezone flag. (On Postgres such a diff is real and
    # must not be suppressed.)
    return isinstance(metadata_type, sa.DateTime) and isinstance(
        inspected_type, sa.DateTime
    )


def test_no_model_migration_drift(tmp_path, monkeypatch):
    """A freshly migrated DB must structurally match Base.metadata."""
    db_url = f"sqlite:///{(tmp_path / 'drift_guard.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            diffs = compare_metadata(
                MigrationContext.configure(conn), Base.metadata
            )
    finally:
        engine.dispose()

    unexpected = [d for d in diffs if not _is_known_equivalent(d)]
    assert unexpected == [], f"model/migration drift detected: {unexpected}"
