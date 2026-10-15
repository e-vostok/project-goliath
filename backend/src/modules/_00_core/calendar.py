"""
Game calendar for module 00_core.

The game date is derived from game_clock.current_turn on read and is
never stored (Spec Part 3):
    total_months = epoch.year * 12 + (epoch.month - 1) + N_turn * R_months
    D_game = date(total_months // 12, total_months % 12 + 1, 1)
"""

from __future__ import annotations

from datetime import date

from modules._00_core.config_schema import CoreConfig

_MAX_DATE = date(9999, 12, 1)


def compute_game_date(current_turn: int, config: CoreConfig) -> date:
    """
    Compute the in-game date for a given turn number.

    Args:
        current_turn: The current turn from game_clock.current_turn.
        config: The core configuration (calendar.epoch_start_date,
            calendar.months_per_turn).

    Returns:
        The game date for the given turn — always the first day of a
        month; results beyond year 9999 are clamped to 9999-12-01.

    Raises:
        ValueError: If current_turn is negative.
    """
    if current_turn < 0:
        raise ValueError("current_turn must not be negative")
    epoch = config.calendar.epoch_start_date
    total = (
        epoch.year * 12 + (epoch.month - 1)
        + current_turn * config.calendar.months_per_turn
    )
    year, month0 = divmod(total, 12)
    if year > 9999:
        return _MAX_DATE
    return date(year, month0 + 1, 1)
