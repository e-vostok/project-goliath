"""
Module 03_registry permanent player numbers (0.11.0 unit 11).

Additive only — no existing table is touched:

``registry_player_numbers`` — the permanent public Registry number of
a player; PK/FK is ``player_id`` -> ``players.id`` ON DELETE CASCADE
(the only kind of foreign key the module may have, INV-R1);
``uq_registry_player_numbers_number`` makes a duplicate impossible.

``registry_number_counter`` — the single ``id = 1`` row holding
``last_number``; it only grows so a freed number is never reissued
(``ck_registry_number_counter_singleton``).

Backfill: every player that exists today receives a number equal to
their current position in the (created_at, id) order of ``players`` —
the very ORDER BY ``PlayerService.list_for_registry`` uses — so every
``#registry/player-<N>`` link and «Игрок №N» name keeps addressing the
same person. ``last_number`` is set to the player count (0 when none).

Downgrade drops both tables and nothing else.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "registry_player_numbers",
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="registry_player_numbers_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "player_id", name="pk_registry_player_numbers"
        ),
        sa.UniqueConstraint(
            "number", name="uq_registry_player_numbers_number"
        ),
    )
    op.create_table(
        "registry_number_counter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_number_counter"),
        sa.CheckConstraint(
            "id = 1", name="ck_registry_number_counter_singleton"
        ),
    )

    # The players table is read-only here (data sovereignty): the
    # registry never writes a row of another module.
    bind = op.get_bind()
    player_ids = (
        bind.execute(sa.text("SELECT id FROM players ORDER BY created_at, id"))
        .scalars()
        .all()
    )
    for position, player_id in enumerate(player_ids, start=1):
        bind.execute(
            sa.text(
                "INSERT INTO registry_player_numbers (player_id, number) "
                "VALUES (:player_id, :number)"
            ),
            {"player_id": player_id, "number": position},
        )
    bind.execute(
        sa.text(
            "INSERT INTO registry_number_counter (id, last_number) "
            "VALUES (1, :last_number)"
        ),
        {"last_number": len(player_ids)},
    )


def downgrade() -> None:
    op.drop_table("registry_number_counter")
    op.drop_table("registry_player_numbers")
