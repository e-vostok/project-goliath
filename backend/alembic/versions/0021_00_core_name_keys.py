"""
Case- and ё-insensitive nation names (0.14.0 unit 3b).

Until now «Рим», «РИМ» and «рим» were three different names and
«Берёза» differed from «Береза»: every uniqueness check compared the
displayed string. ``nations`` and ``nation_applications`` gain
``name_key`` and ``short_name_key`` — the canonical comparison key
(Unicode NFKC, whitespace collapsed, casefold, «ё» → «е») — while the
displayed name keeps storing exactly what the player typed.

The keys are computed in Python, never in SQL: SQLite ``lower()``
folds ASCII only, so a SQL-side backfill would leave Cyrillic case
pairs distinct. The key function is INLINED below — a migration must
never import application code, because ``modules._00_core.name_keys``
may change or move while a shipped revision must replay identically
forever. Keep the copy in sync with ``name_keys.name_key`` byte for
byte.

Two rows that reduce to the same key abort the upgrade with a
readable message naming both displayed names — the migration never
merges or renames data silently. For ``nation_applications`` the
reserve is scoped to PENDING rows (same as the existing partial
indexes), so only PENDING collisions abort.

Uniqueness is enforced by two new UNIQUE constraints on ``nations``
and two new partial unique indexes on ``nation_applications`` WHERE
``status = 'PENDING'`` — every pre-existing constraint and index
stays. ``batch_alter_table`` keeps SQLite and PostgreSQL on one path.
Downgrade drops the four columns and their constraints.
"""

from __future__ import annotations

import unicodedata
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_PENDING = sa.text("status = 'PENDING'")


def _name_key(value: str) -> str:
    """Inlined copy of ``modules._00_core.name_keys.name_key``.

    Migrations must not import application code: the module may change
    or move, while this revision must replay identically forever.
    """
    normalized = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalized.split())
    return collapsed.casefold().replace("ё", "е")


def _read_name_rows(bind, table: str, *extra_columns: sa.Column):
    """(id, name, short_name[, ...]) of every existing row."""
    tbl = sa.table(
        table,
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("short_name", sa.String),
        *extra_columns,
    )
    return bind.execute(sa.select(*tbl.c)).all()


def _ensure_unique(pairs, table: str, column: str) -> None:
    """Abort naming both displayed names when two rows share a key.

    ``pairs`` yields (key, displayed name) for the constrained
    population only — every row of ``nations``, the PENDING rows of
    ``nation_applications``.
    """
    seen: dict[str, str] = {}
    for key, display in pairs:
        if key in seen:
            raise RuntimeError(
                f"migration 0021 aborted: {table}.{column} collision — "
                f"{seen[key]!r} and {display!r} both produce key "
                f"{key!r}; rename one of the two rows and re-run the "
                "migration"
            )
        seen[key] = display


def _backfill_keys(bind, table: str, rows) -> None:
    """Write the two key columns of every row in ``rows``."""
    update = sa.text(
        f"UPDATE {table} SET name_key = :name_key, "
        "short_name_key = :short_name_key WHERE id = :row_id"
    )
    for row in rows:
        bind.execute(
            update,
            {
                "name_key": _name_key(row.name),
                "short_name_key": _name_key(row.short_name),
                "row_id": row.id,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Compute every key in Python and prove the constrained
    # populations collision-free BEFORE touching the schema — an abort
    # here leaves the database exactly at 0020.
    nations = _read_name_rows(bind, "nations")
    applications = _read_name_rows(
        bind, "nation_applications", sa.column("status", sa.String)
    )
    _ensure_unique(
        ((_name_key(row.name), row.name) for row in nations),
        "nations",
        "name_key",
    )
    _ensure_unique(
        ((_name_key(row.short_name), row.short_name) for row in nations),
        "nations",
        "short_name_key",
    )
    pending = [row for row in applications if row.status == "PENDING"]
    _ensure_unique(
        ((_name_key(row.name), row.name) for row in pending),
        "nation_applications",
        "name_key",
    )
    _ensure_unique(
        ((_name_key(row.short_name), row.short_name) for row in pending),
        "nation_applications",
        "short_name_key",
    )

    for table in ("nations", "nation_applications"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("name_key", sa.String(length=100), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "short_name_key", sa.String(length=100), nullable=True
                )
            )

    _backfill_keys(bind, "nations", nations)
    _backfill_keys(bind, "nation_applications", applications)

    with op.batch_alter_table("nations") as batch_op:
        batch_op.alter_column(
            "name_key", existing_type=sa.String(length=100), nullable=False
        )
        batch_op.alter_column(
            "short_name_key",
            existing_type=sa.String(length=100),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_nations_name_key", ["name_key"])
        batch_op.create_unique_constraint(
            "uq_nations_short_name_key", ["short_name_key"]
        )

    with op.batch_alter_table("nation_applications") as batch_op:
        batch_op.alter_column(
            "name_key", existing_type=sa.String(length=100), nullable=False
        )
        batch_op.alter_column(
            "short_name_key",
            existing_type=sa.String(length=100),
            nullable=False,
        )

    # The PENDING reserve gets a key-based twin of the two existing
    # partial indexes — same shape, same WHERE clause.
    op.create_index(
        "uq_nation_applications_pending_name_key",
        "nation_applications",
        ["name_key"],
        unique=True,
        sqlite_where=_PENDING,
        postgresql_where=_PENDING,
    )
    op.create_index(
        "uq_nation_applications_pending_short_name_key",
        "nation_applications",
        ["short_name_key"],
        unique=True,
        sqlite_where=_PENDING,
        postgresql_where=_PENDING,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_nation_applications_pending_name_key",
        table_name="nation_applications",
    )
    op.drop_index(
        "uq_nation_applications_pending_short_name_key",
        table_name="nation_applications",
    )

    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_constraint("uq_nations_name_key", type_="unique")
        batch_op.drop_constraint("uq_nations_short_name_key", type_="unique")

    for table in ("nations", "nation_applications"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("name_key")
            batch_op.drop_column("short_name_key")
