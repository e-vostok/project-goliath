"""
Tests for the month-based game calendar (Spec 00_core Part 3, CAL-1).

Turn 0 — including right after a world reset — is always January 2040;
one turn advances the game date by ``calendar.months_per_turn`` months.
"""

from __future__ import annotations

from datetime import date

import pytest

from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


def test_first_turn_is_january_2040():
    """current_turn = 0 (also right after a world reset) -> 2040-01-01."""
    assert compute_game_date(0, CORE_CONFIG) == date(2040, 1, 1)


def test_turn_advances_by_months_per_turn():
    """One turn = three game months; the sequence crosses the year."""
    assert compute_game_date(1, CORE_CONFIG) == date(2040, 4, 1)
    assert compute_game_date(3, CORE_CONFIG) == date(2040, 10, 1)
    assert compute_game_date(4, CORE_CONFIG) == date(2041, 1, 1)


def test_far_future_turn_clamps_to_date_max():
    """Absurd turn numbers clamp to 9999-12-01 instead of raising."""
    assert compute_game_date(10**9, CORE_CONFIG) == date(9999, 12, 1)


def test_negative_turn_rejected():
    with pytest.raises(ValueError):
        compute_game_date(-1, CORE_CONFIG)
