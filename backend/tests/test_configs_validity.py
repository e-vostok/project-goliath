"""
Tests for configuration validity.

Verifies that configs/00_core.yaml validates correctly and that
invalid configurations raise ValidationError. All synthetic configs go
through one shared base-config helper, so new keys are added in a
single place instead of every test.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from modules._00_core.config_schema import CoreConfig
from modules._01_map.config_schema import MapConfig
from modules._02_bot.config_schema import BUILTIN_TYPE_VARIABLES, BotConfig


def _base_config() -> dict:
    """A fully valid config as a plain dict — the single place where new
    required keys get their valid default."""
    return {
        "tick": {
            "tick_time": "00:00",
            "tick_timezone": "Europe/Moscow",
            "tick_interval_hours": 24,
            "retry_delay_seconds": 60,
            "heartbeat_interval_seconds": 30,
            "health_max_heartbeat_age_seconds": 180,
        },
        "auth": {
            "vk_ts_freshness_window_minutes": 30,
            "jwt_ttl_minutes": 60,
        },
        "nation": {
            "nation_name_min_length": 3,
            "nation_name_max_length": 40,
            "min_provinces_per_nation": 1,
            "max_provinces_per_nation": 5,
            "leader_name_min_length": 2,
            "leader_name_max_length": 60,
            "leader_title_min_length": 2,
            "leader_title_max_length": 60,
            "history_url_max_length": 200,
            "history_url_allowed_hosts": ["vk.com", "vk.ru"],
        },
        "calendar": {
            "epoch_start_date": "0001-01-01",
            "days_per_turn": 7,
        },
    }


def _write_config(
    tmp_path,
    overrides: dict[str, dict] | None = None,
    drop: list[tuple[str, str]] | None = None,
) -> str:
    """Materialize the base config with per-section overrides (or dropped
    keys) as a temp YAML file and return its path."""
    data = _base_config()
    for section, updates in (overrides or {}).items():
        data[section].update(updates)
    for section, key in drop or []:
        del data[section][key]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def test_valid_config_loads():
    """Test that the valid configs/00_core.yaml loads successfully."""
    config = CoreConfig.from_yaml("../configs/00_core.yaml")

    assert config.tick.tick_time == "00:00"
    assert config.tick.tick_timezone == "Europe/Moscow"
    assert config.tick.tick_interval_hours == 24
    assert config.tick.retry_delay_seconds == 60
    assert config.tick.heartbeat_interval_seconds == 30
    assert config.tick.health_max_heartbeat_age_seconds == 180
    assert config.auth.vk_ts_freshness_window_minutes == 30
    assert config.auth.jwt_ttl_minutes == 60
    assert config.nation.nation_name_min_length == 3
    assert config.nation.nation_name_max_length == 40
    assert config.nation.min_provinces_per_nation == 1
    assert config.nation.max_provinces_per_nation == 5
    assert config.nation.leader_name_min_length == 2
    assert config.nation.leader_name_max_length == 60
    assert config.nation.leader_title_min_length == 2
    assert config.nation.leader_title_max_length == 60
    assert config.nation.history_url_max_length == 200
    assert config.nation.history_url_allowed_hosts == ["vk.com", "vk.ru"]
    assert str(config.calendar.epoch_start_date) == "0001-01-01"
    assert config.calendar.days_per_turn == 7


def test_map_config_loads():
    """configs/01_map.yaml ↔ MapConfig (module 01_map, Issue 1).

    The full validation matrix lives in tests/test_01_map_config.py;
    this is the registration gate proving the real file loads."""
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())

    assert config.big_window.enabled is True
    assert config.view.frame.width > 0
    assert config.view.frame.height > 0
    assert config.view.zoom_max > 1.0


def test_02_bot_config_loads():
    """configs/02_bot.yaml ↔ BotConfig (module 02_bot, Issue 1).

    The full validation matrix lives in tests/test_02_bot_config.py;
    this is the registration gate proving the real file loads."""
    config = BotConfig.from_yaml(BotConfig.get_default_config_path())

    assert set(BUILTIN_TYPE_VARIABLES) <= set(config.types)
    assert config.types["DEADLINE_WARNING"].enabled is False
    assert "{group_id}" in config.client.chat_url_template
    assert config.consent.required_for_registration is False


def test_invalid_tick_interval_too_high(tmp_path):
    """Test that tick_interval_hours > 168 raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"tick_interval_hours": 200}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "tick_interval_hours" in str(exc_info.value)
    assert "less than or equal to 168" in str(exc_info.value)


def test_invalid_tick_interval_too_low(tmp_path):
    """Test that tick_interval_hours < 1 raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"tick_interval_hours": 0}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "tick_interval_hours" in str(exc_info.value)
    assert "greater than or equal to 1" in str(exc_info.value)


@pytest.mark.parametrize("bad_time", ["24:00", "0:00", "abc"])
def test_invalid_tick_time(tmp_path, bad_time):
    """tick_time outside the strict 24h HH:MM pattern raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"tick_time": bad_time}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "tick_time" in str(exc_info.value)


def test_invalid_tick_timezone(tmp_path):
    """A tick_timezone that zoneinfo cannot resolve raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"tick_timezone": "Mars/Base"}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "tick_timezone" in str(exc_info.value)


def test_invalid_nation_name_range(tmp_path):
    """Test that min > max for nation_name_length raises ValidationError."""
    path = _write_config(
        tmp_path,
        {"nation": {"nation_name_min_length": 5, "nation_name_max_length": 4}},
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "nation_name_min_length" in str(exc_info.value)


def test_invalid_province_range(tmp_path):
    """Test that min > max for provinces raises ValidationError."""
    path = _write_config(
        tmp_path,
        {
            "nation": {
                "min_provinces_per_nation": 10,
                "max_provinces_per_nation": 5,
            }
        },
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "min_provinces_per_nation" in str(exc_info.value)
    assert "max_provinces_per_nation" in str(exc_info.value)


def test_invalid_retry_delay_too_low(tmp_path):
    """Test that retry_delay_seconds < 1 raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"retry_delay_seconds": 0}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "retry_delay_seconds" in str(exc_info.value)
    assert "greater than or equal to 1" in str(exc_info.value)


def test_invalid_heartbeat_interval_too_high(tmp_path):
    """Test that heartbeat_interval_seconds > 300 raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"heartbeat_interval_seconds": 301}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "heartbeat_interval_seconds" in str(exc_info.value)
    assert "less than or equal to 300" in str(exc_info.value)


def test_invalid_heartbeat_interval_too_low(tmp_path):
    """Test that heartbeat_interval_seconds < 1 raises ValidationError."""
    path = _write_config(tmp_path, {"tick": {"heartbeat_interval_seconds": 0}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "heartbeat_interval_seconds" in str(exc_info.value)
    assert "greater than or equal to 1" in str(exc_info.value)


def test_health_max_heartbeat_age_out_of_bounds_rejected(tmp_path):
    """health_max_heartbeat_age_seconds outside [60, 3600] is rejected."""
    for bad_value in (59, 3601):
        path = _write_config(
            tmp_path, {"tick": {"health_max_heartbeat_age_seconds": bad_value}}
        )
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.from_yaml(path)
        assert "health_max_heartbeat_age_seconds" in str(exc_info.value)


def test_health_max_heartbeat_age_must_exceed_retry_plus_interval(tmp_path):
    """The stale threshold must exceed retry_delay + heartbeat_interval.

    During a DB outage the heartbeat can lag by ~retry_delay_seconds, so
    a threshold at or below that sum would flap /api/v1/health to
    "stale" on a recoverable transient."""
    # 60 + 30 = 90; exactly at the sum is already too tight.
    path = _write_config(
        tmp_path, {"tick": {"health_max_heartbeat_age_seconds": 90}}
    )
    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)
    assert "health_max_heartbeat_age_seconds" in str(exc_info.value)

    # One second above the sum is the tightest valid value.
    path = _write_config(
        tmp_path, {"tick": {"health_max_heartbeat_age_seconds": 91}}
    )
    assert (
        CoreConfig.from_yaml(path).tick.health_max_heartbeat_age_seconds
        == 91
    )


def test_missing_required_field(tmp_path):
    """Test that missing required field raises ValidationError."""
    path = _write_config(tmp_path, drop=[("calendar", "days_per_turn")])

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "days_per_turn" in str(exc_info.value)


# --- Nation profile keys (Spec 1.1) ---------------------------------------


@pytest.mark.parametrize(
    "key,value",
    [
        # Schema bounds accepted (cross-field min<=max kept satisfied).
        ("leader_name_min_length", 1),
        ("leader_name_min_length", 10),
        ("leader_name_max_length", 2),
        ("leader_name_max_length", 100),
        ("leader_title_min_length", 1),
        ("leader_title_min_length", 10),
        ("leader_title_max_length", 2),
        ("leader_title_max_length", 100),
        ("history_url_max_length", 30),
        ("history_url_max_length", 2000),
        ("history_url_allowed_hosts", ["vk.com"]),
        ("history_url_allowed_hosts", [f"h{i}.io" for i in range(10)]),
    ],
)
def test_nation_profile_keys_at_bounds_load(tmp_path, key, value):
    """Each profile key validates at its schema min and max."""
    path = _write_config(tmp_path, {"nation": {key: value}})

    assert CoreConfig.from_yaml(path).nation is not None


@pytest.mark.parametrize(
    "key,value",
    [
        ("leader_name_min_length", 0),
        ("leader_name_min_length", 11),
        ("leader_name_max_length", 0),
        ("leader_name_max_length", 101),
        ("leader_title_min_length", 0),
        ("leader_title_min_length", 11),
        ("leader_title_max_length", 0),
        ("leader_title_max_length", 101),
        ("history_url_max_length", 29),
        ("history_url_max_length", 2001),
        ("history_url_allowed_hosts", []),
        ("history_url_allowed_hosts", ["a.io"] * 11),
    ],
)
def test_nation_profile_keys_out_of_bounds_rejected(tmp_path, key, value):
    """Each profile key just outside its schema bounds is rejected."""
    path = _write_config(tmp_path, {"nation": {key: value}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert key in str(exc_info.value)


@pytest.mark.parametrize(
    "min_key,max_key",
    [
        ("leader_name_min_length", "leader_name_max_length"),
        ("leader_title_min_length", "leader_title_max_length"),
    ],
)
def test_profile_min_above_max_rejected(tmp_path, min_key, max_key):
    """The cross-field min<=max rule covers leader name and title."""
    path = _write_config(tmp_path, {"nation": {min_key: 5, max_key: 4}})

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert min_key in str(exc_info.value)
    assert max_key in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_host",
    [
        "https://vk.com",  # scheme included
        "vk.com/history",  # path included
        "vk.com:443",  # port included
        "VK.COM",  # uppercase
        "vk_com",  # not a hostname
        "-vk.com",  # leading hyphen
    ],
)
def test_history_url_allowed_hosts_rejects_bad_host(tmp_path, bad_host):
    """Hosts must be lowercase hostnames without scheme, port or path."""
    path = _write_config(
        tmp_path,
        {"nation": {"history_url_allowed_hosts": [bad_host]}},
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "history_url_allowed_hosts" in str(exc_info.value)


def test_history_url_allowed_hosts_rejects_duplicates(tmp_path):
    """Duplicate hostnames in the allow list are rejected."""
    path = _write_config(
        tmp_path,
        {"nation": {"history_url_allowed_hosts": ["vk.com", "vk.com"]}},
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "history_url_allowed_hosts" in str(exc_info.value)


@pytest.mark.parametrize(
    "key",
    [
        "leader_name_min_length",
        "leader_name_max_length",
        "leader_title_min_length",
        "leader_title_max_length",
        "history_url_max_length",
        "history_url_allowed_hosts",
    ],
)
def test_missing_profile_key_rejected(tmp_path, key):
    """Every new profile key is required — no schema defaults (Spec 1.1)."""
    path = _write_config(tmp_path, drop=[("nation", key)])

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert key in str(exc_info.value)
