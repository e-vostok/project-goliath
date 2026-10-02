"""
Module 01_map data layer: provinces.kind and map_ownership_log.

Spec 01_map Part 1 / Appendix B item 1:

1. provinces gains ``kind`` ('LAND'/'SEA', NOT NULL, default 'LAND')
   plus CHECK ``ck_provinces_kind`` and ``ck_provinces_sea_unowned``
   (INV-M4: a sea zone can never belong to a nation). Done via
   batch_alter_table so SQLite and PostgreSQL take the same path.
2. The placeholder rows ``id 1..100`` seeded by migration 0001 are
   deleted — real node ids start at 1001. The delete is guarded: if any
   of them is still owned by a nation, the upgrade aborts with a world-
   reset instruction and changes nothing. It also refuses to run when
   another table holds a foreign key into provinces.id (that would make
   the delete unsafe); no such table exists at head today.
3. map_ownership_log (owner: 01_map) is created — the append-only
   ownership journal: BIGINT PK (INTEGER variant on SQLite so
   autoincrement works, the tick_log.id lesson from migration 0002),
   FK only to provinces.id, logical (FK-less) references to nations,
   the ck_log_new_nation_consistent CHECK and both indexes.

Downgrade restores the schema and re-inserts the 100 placeholder rows
exactly as migration 0001 created them (nation_id NULL).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_PLACEHOLDER_IDS = "id BETWEEN 1 AND 100"


def _assert_no_external_fk_to_provinces(bind) -> None:
    """
    Refuse the placeholder delete if another table references
    provinces.id — its rows could point at 1..100 and the delete would
    leave dangling references (or fail on Postgres). Nothing at head
    today does; report instead of guessing a cascade policy.
    """
    inspector = sa.inspect(bind)
    offenders = []
    for table in inspector.get_table_names():
        if table == "provinces":
            continue
        for fk in inspector.get_foreign_keys(table):
            if fk.get("referred_table") == "provinces":
                offenders.append(f"{table}.{', '.join(fk['constrained_columns'])}")
    if offenders:
        raise RuntimeError(
            "Refusing to delete placeholder provinces 1..100: foreign keys "
            f"to provinces.id exist in: {', '.join(sorted(offenders))}. "
            "Resolve or report this before re-running the migration."
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Guard 1: no placeholder may be owned by a nation.
    owned = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM provinces "
            f"WHERE {_PLACEHOLDER_IDS} AND nation_id IS NOT NULL"
        )
    ).scalar_one()
    if owned:
        raise RuntimeError(
            "Сначала выполните сброс мира: провинции 1..100 закреплены "
            "за государствами"
        )

    # Guard 2: no other table may hold FK references into provinces.
    _assert_no_external_fk_to_provinces(bind)

    # Data change first, before any DDL.
    op.execute(
        sa.text(f"DELETE FROM provinces WHERE {_PLACEHOLDER_IDS}")
    )

    with op.batch_alter_table("provinces") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=4),
                nullable=False,
                server_default="LAND",
            )
        )
        batch_op.create_check_constraint(
            "ck_provinces_kind", "kind IN ('LAND','SEA')"
        )
        batch_op.create_check_constraint(
            "ck_provinces_sea_unowned", "kind = 'LAND' OR nation_id IS NULL"
        )

    op.create_table(
        "map_ownership_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("province_id", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.BigInteger(), nullable=False),
        sa.Column("prev_nation_id", sa.String(length=36), nullable=True),
        sa.Column("new_nation_id", sa.String(length=36), nullable=True),
        sa.Column("new_nation_name", sa.String(length=100), nullable=True),
        sa.Column("new_nation_color", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["province_id"],
            ["provinces.id"],
            name="map_ownership_log_province_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_map_ownership_log"),
        sa.CheckConstraint(
            "(new_nation_id IS NULL AND new_nation_name IS NULL "
            "AND new_nation_color IS NULL) OR "
            "(new_nation_id IS NOT NULL AND new_nation_name IS NOT NULL "
            "AND new_nation_color IS NOT NULL)",
            name="ck_log_new_nation_consistent",
        ),
    )
    op.create_index(
        "ix_map_log_province_turn",
        "map_ownership_log",
        ["province_id", "turn_number", "id"],
        unique=False,
    )
    op.create_index(
        "ix_map_log_turn",
        "map_ownership_log",
        ["turn_number"],
        unique=False,
    )


def downgrade() -> None:
    # Drop the journal first — it holds the FK into provinces.
    op.drop_index("ix_map_log_turn", table_name="map_ownership_log")
    op.drop_index(
        "ix_map_log_province_turn", table_name="map_ownership_log"
    )
    op.drop_table("map_ownership_log")

    with op.batch_alter_table("provinces") as batch_op:
        batch_op.drop_constraint("ck_provinces_sea_unowned", type_="check")
        batch_op.drop_constraint("ck_provinces_kind", type_="check")
        batch_op.drop_column("kind")

    # Restore the placeholders exactly as migration 0001 seeded them.
    # provinces.kind no longer exists at this point, so the insert goes
    # through a plain table construct, not the current ORM model.
    provinces = sa.table(
        "provinces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nation_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        provinces.insert().values(
            [{"id": i, "nation_id": None} for i in range(1, 101)]
        )
    )
