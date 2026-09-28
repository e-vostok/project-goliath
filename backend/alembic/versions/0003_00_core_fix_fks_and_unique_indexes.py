"""
Converge migrated schema with model metadata (drift repair).

Two classes of real drift left behind by migration 0001:

1. Missing foreign keys. The models declare referential integrity that
   was never migrated:
     nations.owner_player_id          -> players.id
     provinces.nation_id              -> nations.id
     scheduled_actions.nation_id      -> nations.id

2. UNIQUE constraint + plain index pairs where the models declare a
   single UNIQUE index (unique=True + index=True):
     players.vk_user_id, nations.owner_player_id.
   The constraint is dropped and the plain index replaced by a UNIQUE
   index of the same name — functionally equivalent, matching metadata.

Two remaining compare_metadata modify_type classes are intentionally
unfixed: SQLEnum(native_enum=False) is stored as VARCHAR by design (no
database can reflect a Python Enum type back), and SQLite TIMESTAMP
columns cannot reflect timezone awareness. The drift guard test filters
exactly those two equivalences — everything else must diff to zero.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_UQ_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

# (table, column, referenced_table)
_FKS = [
    ("nations", "owner_player_id", "players"),
    ("provinces", "nation_id", "nations"),
    ("scheduled_actions", "nation_id", "nations"),
]

# (table, column, index_name)
_UNIQUE_TO_UNIQUE_INDEX = [
    ("players", "vk_user_id", "ix_players_vk_user_id"),
    ("nations", "owner_player_id", "ix_nations_owner_player_id"),
]


def _unique_constraint_name(table: str, column: str) -> str | None:
    """Resolve the unique constraint's real name, or the convention name."""
    inspector = sa.inspect(op.get_bind())
    for uq in inspector.get_unique_constraints(table):
        if uq.get("column_names") == [column]:
            return uq.get("name") or f"uq_{table}_{column}"
    return None


def upgrade() -> None:
    for table, column, referenced in _FKS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                f"{table}_{column}_fkey", referenced, [column], ["id"]
            )

    for table, column, index_name in _UNIQUE_TO_UNIQUE_INDEX:
        constraint_name = _unique_constraint_name(table, column)
        with op.batch_alter_table(
            table, naming_convention=_UQ_NAMING
        ) as batch_op:
            batch_op.drop_index(index_name)
            if constraint_name is not None:
                batch_op.drop_constraint(constraint_name, type_="unique")
            batch_op.create_index(index_name, [column], unique=True)


def downgrade() -> None:
    for table, column, index_name in _UNIQUE_TO_UNIQUE_INDEX:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(index_name)
            batch_op.create_index(index_name, [column], unique=False)
            batch_op.create_unique_constraint(
                f"uq_{table}_{column}", [column]
            )

    for table, column, _referenced in _FKS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(
                f"{table}_{column}_fkey", type_="foreignkey"
            )
