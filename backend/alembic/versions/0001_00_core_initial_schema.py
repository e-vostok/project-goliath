"""
Initial schema for module 00_core.

Creates the 6 core tables: players, nations, provinces, scheduled_actions,
game_clock, and tick_log. Seeds 100 provinces and initial game_clock row.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# Add src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = ("00_core",)
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """Create tables and seed initial data."""
    # Import config to get tick_interval_hours for seeding
    from modules._00_core.config_schema import CoreConfig
    from pathlib import Path
    
    config_path = Path(__file__).parent.parent.parent.parent / "configs" / "00_core.yaml"
    config = CoreConfig.from_yaml(str(config_path))
    tick_interval_hours = config.tick.tick_interval_hours
    
    # Create enum types (PostgreSQL-specific, but SQLAlchemy handles it)
    # Note: For SQLite compatibility, we use string enums in the model
    # so we don't need to create native enum types here
    
    # Create players table
    op.create_table(
        "players",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_players_vk_user_id"), "players", ["vk_user_id"], unique=False)
    
    # Create nations table
    op.create_table(
        "nations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_player_id", sa.String(36), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("color_hex", sa.CHAR(7), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_nations_owner_player_id"), "nations", ["owner_player_id"], unique=False)
    
    # Create provinces table
    op.create_table(
        "provinces",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False, primary_key=True),
        sa.Column("nation_id", sa.String(36), nullable=True),
    )
    op.create_index(op.f("ix_provinces_nation_id"), "provinces", ["nation_id"], unique=False)
    
    # Create scheduled_actions table
    op.create_table(
        "scheduled_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("nation_id", sa.String(36), nullable=False),
        sa.Column("module_slug", sa.String(50), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("turn_number", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_scheduled_actions_nation_id"), "scheduled_actions", ["nation_id"], unique=False)
    op.create_index(op.f("ix_scheduled_actions_module_slug"), "scheduled_actions", ["module_slug"], unique=False)
    op.create_index(op.f("ix_scheduled_actions_turn_number"), "scheduled_actions", ["turn_number"], unique=False)
    op.create_index(op.f("ix_scheduled_actions_status"), "scheduled_actions", ["status"], unique=False)
    op.create_index("ix_scheduled_actions_turn_status", "scheduled_actions", ["turn_number", "status"], unique=False)
    
    # Create game_clock table
    op.create_table(
        "game_clock",
        sa.Column("id", sa.SmallInteger(), nullable=False, primary_key=True),
        sa.Column("current_turn", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_tick_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_tick_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="check_game_clock_singleton"),
    )
    
    # Create tick_log table
    op.create_table(
        "tick_log",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("turn_number", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_tick_log_turn_number"), "tick_log", ["turn_number"], unique=False)
    op.create_index(op.f("ix_tick_log_status"), "tick_log", ["status"], unique=False)
    
    # Seed provinces: 100 rows with id=1..100, nation_id=NULL
    from sqlalchemy import insert
    from modules._00_core.models import Province
    from datetime import datetime, timedelta
    
    provinces_data = [
        {"id": i, "nation_id": None}
        for i in range(1, 101)
    ]
    op.execute(insert(Province.__table__).values(provinces_data))
    
    # Seed game_clock: single row with id=1, current_turn=0, next_tick_at calculated from config
    from modules._00_core.models import GameClock
    
    next_tick_at = datetime.utcnow() + timedelta(hours=tick_interval_hours)
    game_clock_data = [
        {
            "id": 1,
            "current_turn": 0,
            "last_tick_at": None,
            "next_tick_at": next_tick_at,
        }
    ]
    op.execute(insert(GameClock.__table__).values(game_clock_data))


def downgrade() -> None:
    """Drop all tables in reverse FK order."""
    # Drop tables in reverse order of creation (respecting FK dependencies)
    op.drop_index("ix_scheduled_actions_turn_status", table_name="scheduled_actions")
    op.drop_index(op.f("ix_scheduled_actions_status"), table_name="scheduled_actions")
    op.drop_index(op.f("ix_scheduled_actions_turn_number"), table_name="scheduled_actions")
    op.drop_index(op.f("ix_scheduled_actions_module_slug"), table_name="scheduled_actions")
    op.drop_index(op.f("ix_scheduled_actions_nation_id"), table_name="scheduled_actions")
    op.drop_table("scheduled_actions")
    
    op.drop_index(op.f("ix_tick_log_status"), table_name="tick_log")
    op.drop_index(op.f("ix_tick_log_turn_number"), table_name="tick_log")
    op.drop_table("tick_log")
    
    op.drop_table("game_clock")
    
    op.drop_index(op.f("ix_provinces_nation_id"), table_name="provinces")
    op.drop_table("provinces")
    
    op.drop_index(op.f("ix_nations_owner_player_id"), table_name="nations")
    op.drop_table("nations")
    
    op.drop_index(op.f("ix_players_vk_user_id"), table_name="players")
    op.drop_table("players")
