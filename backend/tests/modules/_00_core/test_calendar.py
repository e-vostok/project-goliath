"""
Tests for the month-based game calendar (Spec 00_core Part 3, CAL-1).

Turn 1 — including right after a world reset — is always January 2040;
one turn advances the game date by ``calendar.months_per_turn`` months.
"""

from __future__ import annotations

from datetime import date

import pytest

from modules._00_core.calendar import compute_game_date, format_game_date
from modules._00_core.config_schema import CoreConfig

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


def test_first_turn_is_january_2040():
    """current_turn = 1 (also right after a world reset) -> 2040-01-01."""
    assert compute_game_date(1, CORE_CONFIG) == date(2040, 1, 1)


def test_turn_advances_by_months_per_turn():
    """One turn = one game month; the sequence crosses the year."""
    assert compute_game_date(2, CORE_CONFIG) == date(2040, 2, 1)
    assert compute_game_date(12, CORE_CONFIG) == date(2040, 12, 1)
    assert compute_game_date(13, CORE_CONFIG) == date(2041, 1, 1)


def test_format_game_date_renders_month_year():
    """«Месяц Год» for the shipped calendar: turns 1, 2 and 13."""
    assert (
        format_game_date(compute_game_date(1, CORE_CONFIG), CORE_CONFIG)
        == "Январь 2040"
    )
    assert (
        format_game_date(compute_game_date(2, CORE_CONFIG), CORE_CONFIG)
        == "Февраль 2040"
    )
    assert (
        format_game_date(compute_game_date(13, CORE_CONFIG), CORE_CONFIG)
        == "Январь 2041"
    )


def test_format_game_date_renders_october():
    """Turn 10 lands on October — «Октябрь 2040»."""
    assert (
        format_game_date(compute_game_date(10, CORE_CONFIG), CORE_CONFIG)
        == "Октябрь 2040"
    )


def test_format_game_date_year_has_no_leading_zeros():
    """A short year stays short: «Январь 1», not «Январь 0001»."""
    assert format_game_date(date(1, 1, 1), CORE_CONFIG) == "Январь 1"


def test_far_future_turn_clamps_to_date_max():
    """Absurd turn numbers clamp to 9999-12-01 instead of raising."""
    assert compute_game_date(10**9, CORE_CONFIG) == date(9999, 12, 1)


def test_zero_and_negative_turns_rejected():
    """Turns count from 1: 0 and negatives raise."""
    for bad_turn in (0, -1):
        with pytest.raises(ValueError):
            compute_game_date(bad_turn, CORE_CONFIG)
