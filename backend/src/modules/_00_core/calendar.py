"""
Game calendar for module 00_core.

The game date is derived from game_clock.current_turn on read and is
never stored (Spec Part 3):
    D_game = D_epoch + floor(N_turn * R_days)
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from modules._00_core.config_schema import CoreConfig


def compute_game_date(current_turn: int, config: CoreConfig) -> date:
    """
    Compute the in-game date for a given turn number.

    Args:
        current_turn: The current turn from game_clock.current_turn.
        config: The core configuration (calendar.epoch_start_date,
            calendar.days_per_turn).

    Returns:
        The game date for the given turn.
    """
    days_elapsed = math.floor(current_turn * config.calendar.days_per_turn)
    return config.calendar.epoch_start_date + timedelta(days=days_elapsed)
