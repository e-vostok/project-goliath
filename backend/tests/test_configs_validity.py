"""
Tests for configuration validity.

Verifies that configs/00_core.yaml validates correctly and that
invalid configurations raise ValidationError.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from modules._00_core.config_schema import CoreConfig


def test_valid_config_loads():
    """Test that the valid configs/00_core.yaml loads successfully."""
    config = CoreConfig.from_yaml("../configs/00_core.yaml")
    
    assert config.tick.tick_interval_hours == 24
    assert config.auth.vk_ts_freshness_window_minutes == 30
    assert config.auth.jwt_ttl_minutes == 60
    assert config.nation.nation_name_min_length == 3
    assert config.nation.nation_name_max_length == 40
    assert config.nation.min_provinces_per_nation == 1
    assert config.nation.max_provinces_per_nation == 5
    assert str(config.calendar.epoch_start_date) == "0001-01-01"
    assert config.calendar.days_per_turn == 7


def test_invalid_tick_interval_too_high():
    """Test that tick_interval_hours > 168 raises ValidationError."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
tick:
  tick_interval_hours: 200
auth:
  vk_ts_freshness_window_minutes: 30
  jwt_ttl_minutes: 60
nation:
  nation_name_min_length: 3
  nation_name_max_length: 40
  min_provinces_per_nation: 1
  max_provinces_per_nation: 5
calendar:
  epoch_start_date: "0001-01-01"
  days_per_turn: 7
""")
        temp_path = f.name
    
    try:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(temp_path)
        
        assert "tick_interval_hours" in str(exc_info.value)
        assert "less than or equal to 168" in str(exc_info.value)
    finally:
        Path(temp_path).unlink()


def test_invalid_tick_interval_too_low():
    """Test that tick_interval_hours < 1 raises ValidationError."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
tick:
  tick_interval_hours: 0
auth:
  vk_ts_freshness_window_minutes: 30
  jwt_ttl_minutes: 60
nation:
  nation_name_min_length: 3
  nation_name_max_length: 40
  min_provinces_per_nation: 1
  max_provinces_per_nation: 5
calendar:
  epoch_start_date: "0001-01-01"
  days_per_turn: 7
""")
        temp_path = f.name
    
    try:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(temp_path)
        
        assert "tick_interval_hours" in str(exc_info.value)
        assert "greater than or equal to 1" in str(exc_info.value)
    finally:
        Path(temp_path).unlink()


def test_invalid_nation_name_range():
    """Test that min > max for nation_name_length raises ValidationError."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
tick:
  tick_interval_hours: 24
auth:
  vk_ts_freshness_window_minutes: 30
  jwt_ttl_minutes: 60
nation:
  nation_name_min_length: 50
  nation_name_max_length: 10
  min_provinces_per_nation: 1
  max_provinces_per_nation: 5
calendar:
  epoch_start_date: "0001-01-01"
  days_per_turn: 7
""")
        temp_path = f.name
    
    try:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(temp_path)
        
        assert "nation_name_min_length" in str(exc_info.value)
    finally:
        Path(temp_path).unlink()


def test_invalid_province_range():
    """Test that min > max for provinces raises ValidationError."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
tick:
  tick_interval_hours: 24
auth:
  vk_ts_freshness_window_minutes: 30
  jwt_ttl_minutes: 60
nation:
  nation_name_min_length: 3
  nation_name_max_length: 40
  min_provinces_per_nation: 10
  max_provinces_per_nation: 5
calendar:
  epoch_start_date: "0001-01-01"
  days_per_turn: 7
""")
        temp_path = f.name
    
    try:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(temp_path)
        
        assert "min_provinces_per_nation" in str(exc_info.value)
        assert "max_provinces_per_nation" in str(exc_info.value)
    finally:
        Path(temp_path).unlink()


def test_missing_required_field():
    """Test that missing required field raises ValidationError."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
tick:
  tick_interval_hours: 24
auth:
  vk_ts_freshness_window_minutes: 30
  jwt_ttl_minutes: 60
nation:
  nation_name_min_length: 3
  nation_name_max_length: 40
  min_provinces_per_nation: 1
  max_provinces_per_nation: 5
calendar:
  epoch_start_date: "0001-01-01"
  # days_per_turn is missing
""")
        temp_path = f.name
    
    try:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(temp_path)
        
        assert "days_per_turn" in str(exc_info.value)
    finally:
        Path(temp_path).unlink()
