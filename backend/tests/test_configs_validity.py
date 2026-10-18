"""
Tests for configuration validity.

Verifies that configs/00_core.yaml validates correctly and that
invalid configurations raise ValidationError. All synthetic configs go
through one shared base-config helper, so new keys are added in a
single place instead of every test.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Nation
from modules._00_core.player_stats import JUDGE_RATING_MAX, JUDGE_RATING_MIN
from modules._01_map.config_schema import MapConfig
from modules._02_bot.config_schema import BUILTIN_TYPE_VARIABLES, BotConfig
from modules._03_registry.config_schema import RegistryConfig
import modules._04_orders.config_schema as orders_schema
from modules._04_orders.config_schema import OrdersConfig
from modules._04_orders.models import Order

REPO_ROOT = Path(__file__).resolve().parents[2]


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
            "nation_name_min_length": 2,
            "nation_name_max_length": 40,
            "short_name_min_length": 2,
            "short_name_max_length": 16,
            "min_provinces_per_nation": 5,
            "max_provinces_per_nation": 5,
            "leader_name_min_length": 2,
            "leader_name_max_length": 60,
            "leader_title_min_length": 2,
            "leader_title_max_length": 60,
            "motto_max_length": 60,
            "description_max_length": 100,
            "leader_bio_max_length": 500,
            "capital_name_min_length": 2,
            "capital_name_max_length": 40,
            "history_url_max_length": 200,
            "history_url_allowed_hosts": ["vk.com", "vk.ru"],
            "anthem_url_max_length": 200,
            "anthem_url_allowed_hosts": ["vk.com", "vk.ru"],
        },
        "color": {
            "min_distance_nations": 0.08,
            "min_distance_reserved": 0.08,
            "reserved": [
                {"name": "свободная провинция", "hex": "#8C8C8C"},
                {"name": "море", "hex": "#141E26"},
                {
                    "name": "земли за краем игрового поля",
                    "hex": "#2A2A2A",
                },
                {"name": "подсветка при наведении", "hex": "#FFFFFF"},
            ],
            "palette": ["#6A3446", "#BE1253", "#058D1D", "#0C7CF4"],
        },
        "catalog": {
            "flag_ids": [],
            "portrait_ids": [],
        },
        "calendar": {
            "epoch_start_date": "2040-01-01",
            "months_per_turn": 1,
            "month_names": [
                "январь", "февраль", "март", "апрель", "май", "июнь",
                "июль", "август", "сентябрь", "октябрь", "ноябрь",
                "декабрь",
            ],
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
    assert config.nation.nation_name_min_length == 2
    assert config.nation.nation_name_max_length == 40
    assert config.nation.short_name_min_length == 2
    assert config.nation.short_name_max_length == 16
    assert config.nation.min_provinces_per_nation == 5
    assert config.nation.max_provinces_per_nation == 5
    assert config.nation.leader_name_min_length == 2
    assert config.nation.leader_name_max_length == 60
    assert config.nation.leader_title_min_length == 2
    assert config.nation.leader_title_max_length == 60
    assert config.nation.motto_max_length == 60
    assert config.nation.description_max_length == 100
    assert config.nation.leader_bio_max_length == 500
    assert config.nation.capital_name_min_length == 2
    assert config.nation.capital_name_max_length == 40
    assert config.nation.history_url_max_length == 200
    assert config.nation.history_url_allowed_hosts == [
        "vk.com", "vk.ru", "m.vk.com",
    ]
    assert config.nation.anthem_url_max_length == 200
    assert config.nation.anthem_url_allowed_hosts == [
        "vk.com", "vk.ru", "m.vk.com",
    ]
    assert config.color.min_distance_nations == 0.08
    assert config.color.min_distance_reserved == 0.08
    assert len(config.color.reserved) == 4
    assert len(config.color.palette) == 36
    assert config.catalog.flag_ids == [
        f"flag_placeholder_{i}" for i in range(1, 7)
    ]
    assert config.catalog.portrait_ids == [
        f"portrait_placeholder_{i}" for i in range(1, 7)
    ]
    assert str(config.calendar.epoch_start_date) == "2040-01-01"
    assert config.calendar.months_per_turn == 1
    assert config.calendar.month_names[0] == "январь"
    assert config.calendar.month_names[11] == "декабрь"


# --- Spec 1.3 Part 4: cross-artifact guards --------------------------------


def test_text_bounds_do_not_exceed_column_lengths():
    """Spec 1.3 Part 4: every upper text bound of the shipped config fits
    its ``nations`` column length — any valid value stores without a new
    migration."""
    config = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    )
    columns = Nation.__table__.columns
    bounds = {
        "name": config.nation.nation_name_max_length,
        "short_name": config.nation.short_name_max_length,
        "leader_name": config.nation.leader_name_max_length,
        "leader_title": config.nation.leader_title_max_length,
        "motto": config.nation.motto_max_length,
        "description": config.nation.description_max_length,
        "leader_bio": config.nation.leader_bio_max_length,
        "capital_name": config.nation.capital_name_max_length,
        "history_url": config.nation.history_url_max_length,
        "anthem_url": config.nation.anthem_url_max_length,
    }
    for column_name, bound in bounds.items():
        assert bound <= columns[column_name].type.length, (
            f"nation.{column_name}: config bound {bound} exceeds the "
            f"column length {columns[column_name].type.length}"
        )


def test_map_color_hexes_are_all_reserved():
    """Spec 1.3 Part 4: every nation-visible map color of
    ``configs/01_map.yaml`` is pinned in ``color.reserved``
    (case-insensitive), so no nation may claim a color the map owns."""
    with open("../configs/01_map.yaml", encoding="utf-8") as f:
        map_colors = yaml.safe_load(f)["colors"]
    config = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    )
    reserved = {entry.hex.upper() for entry in config.color.reserved}
    for key in ("neutral_province", "sea", "outside", "hover"):
        assert map_colors[key].upper() in reserved, (
            f"colors.{key}={map_colors[key]} is missing from "
            "color.reserved"
        )


def test_catalog_ids_have_asset_files():
    """Spec 1.3 Part 4: the catalog lists and the files under
    ``frontend/public/assets/nations/`` must be in exact 1:1 sync —
    every listed id resolves to a real PNG (INV-15), and no stray PNG
    sits in the folders unlisted."""
    config = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    )
    assets = (
        REPO_ROOT / "frontend" / "public" / "assets" / "nations"
    )
    for folder_name, ids in (
        ("flags", config.catalog.flag_ids),
        ("portraits", config.catalog.portrait_ids),
    ):
        folder = assets / folder_name
        for item_id in ids:
            assert (folder / f"{item_id}.png").is_file(), (
                f"catalog id '{item_id}' has no file at "
                f"{folder / (item_id + '.png')}"
            )
        stray = sorted(
            p.stem for p in folder.glob("*.png") if p.stem not in ids
        )
        assert not stray, (
            f"{folder}: PNG files not listed in the config: {stray}"
        )


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
    assert config.consent.required_for_registration is True


def test_03_registry_config_loads():
    """configs/03_registry.yaml ↔ RegistryConfig (module 03_registry,
    Issue 1).

    The registration gate proves the real file loads; the gauge scale of
    the ``judge_rating`` column must equal the 00_core scale constants —
    the bounds are model properties the config can only repeat for
    drawing (Spec 03_registry 0/D1)."""
    config = RegistryConfig.from_yaml(
        RegistryConfig.get_default_config_path()
    )

    players = config.table("players")
    gauge = next(c for c in players.columns if c.id == "judge_rating")
    assert gauge.type == "gauge"
    assert gauge.scale_min == JUDGE_RATING_MIN
    assert gauge.scale_max == JUDGE_RATING_MAX


def test_04_orders_config_loads():
    """configs/04_orders.yaml ↔ OrdersConfig (module 04_orders, Issue 1).

    The registration gate proves the real file loads; the schema's
    judge-rating bounds must equal the 00_core scale constants — they
    are model properties the config can only repeat as the allowed
    threshold range (Spec 04_orders 4.1, Appendix T)."""
    config = OrdersConfig.from_yaml(OrdersConfig.get_default_config_path())

    assert config.judge.min_rating == 0
    assert config.judge.max_pending_verdicts == 5
    assert config.judge.require_reachable is True
    assert config.judge.verdict_deadline_hours == 72
    assert config.judge.reminder_percent == 75
    assert config.author.max_unresolved_orders == 5
    assert config.distribution.retry_interval_seconds == 60
    assert config.distribution.batch_size == 50
    assert config.limits.title_min_length == 3
    assert config.limits.title_max_length == 100
    assert config.limits.summary_min_length == 10
    assert config.limits.summary_max_length == 500
    assert config.limits.url_max_length == 200

    # The min_rating Field bounds repeat the 00_core scale exactly.
    assert orders_schema.JUDGE_RATING_MIN == JUDGE_RATING_MIN
    assert orders_schema.JUDGE_RATING_MAX == JUDGE_RATING_MAX
    field_meta = orders_schema.JudgeSettings.model_fields[
        "min_rating"
    ].metadata
    assert any(
        getattr(m, "ge", None) == JUDGE_RATING_MIN for m in field_meta
    )
    assert any(
        getattr(m, "le", None) == JUDGE_RATING_MAX for m in field_meta
    )


def test_04_orders_column_lengths_match_schema():
    """``orders`` column lengths equal the schema constants — any valid
    config limit fits the column without a new migration (Spec 04_orders
    Part 1: «Длины колонок равны верхним границам схемы конфига»)."""
    columns = Order.__table__.columns
    assert columns["title"].type.length == orders_schema.TITLE_COLUMN_LENGTH
    assert (
        columns["verdict_title"].type.length
        == orders_schema.TITLE_COLUMN_LENGTH
    )
    assert (
        columns["summary"].type.length == orders_schema.SUMMARY_COLUMN_LENGTH
    )
    assert (
        columns["verdict_summary"].type.length
        == orders_schema.SUMMARY_COLUMN_LENGTH
    )
    assert (
        columns["article_url"].type.length
        == orders_schema.URL_COLUMN_LENGTH
    )
    assert (
        columns["verdict_url"].type.length == orders_schema.URL_COLUMN_LENGTH
    )


def test_03_registry_accepts_new_types_and_rejects_bad_combos():
    """04_orders Issue 3 (Spec 03_registry 1.2): the schema accepts the
    ``datetime`` and ``action_text`` column types, the ``header_icon``
    key and the ``orders`` table icon — and still rejects an
    ``action_text`` column with ``date_range`` and an unknown
    ``header_icon`` value."""
    with open(
        RegistryConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)

    data["tables"] = [
        {
            "id": "orders",
            "title": "Приказы",
            "icon": "orders",
            "source": "orders",
            "empty_text": "Приказов пока нет",
            "default_sort": {"column": "number", "direction": "desc"},
            "columns": [
                {
                    "id": "number", "title": "№", "type": "index",
                    "source": "number", "width_px": 56, "sortable": True,
                    "filters": [], "searchable": False, "stub": False,
                },
                {
                    "id": "title", "title": "Название",
                    "type": "action_text", "source": "title",
                    "width_px": 236, "sortable": True,
                    "filters": ["text"], "searchable": True, "stub": False,
                },
                {
                    "id": "submitted", "title": "Подача",
                    "header_icon": "stage_submitted", "type": "datetime",
                    "source": "submitted", "width_px": 136,
                    "sortable": True,
                    "filters": ["date_range", "presence"],
                    "searchable": False, "stub": False,
                },
            ],
        }
    ]
    config = RegistryConfig.model_validate(data)
    orders = config.table("orders")
    assert orders.icon == "orders"
    assert orders.columns[1].type == "action_text"
    assert orders.columns[2].type == "datetime"
    assert orders.columns[2].header_icon == "stage_submitted"

    bad_filters = copy.deepcopy(data)
    bad_filters["tables"][0]["columns"][1]["filters"] = ["date_range"]
    with pytest.raises(ValidationError):
        RegistryConfig.model_validate(bad_filters)

    bad_icon = copy.deepcopy(data)
    bad_icon["tables"][0]["columns"][2]["header_icon"] = "stage_magic"
    with pytest.raises(ValidationError):
        RegistryConfig.model_validate(bad_icon)


def test_03_registry_table_over_table_max_width_rejected():
    """03_registry Issue 3b: a table whose ``width_px`` columns sum above
    ``layout.table_max_width_px`` fails validation — the 910 px window
    rule is enforced before the server starts (Spec 03_registry 4.1)."""
    with open(
        RegistryConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)
    data["tables"][0]["columns"][1]["width_px"] = 600

    with pytest.raises(ValidationError) as exc_info:
        RegistryConfig.model_validate(data)

    assert "table_max_width_px" in str(exc_info.value)


def test_02_bot_nation_created_rejects_unknown_placeholder():
    """02_bot Issue 7: ``dialog.texts.nation_created`` allows only
    ``{nation_name}`` — an unknown placeholder must fail config loading
    (the same template check the other dialog texts pass)."""
    with open(
        BotConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)
    data["dialog"]["texts"]["nation_created"] += " {bogus_var}"

    with pytest.raises(ValidationError) as exc_info:
        BotConfig.model_validate(data)

    assert "bogus_var" in str(exc_info.value)


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
    path = _write_config(tmp_path, drop=[("calendar", "months_per_turn")])

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "months_per_turn" in str(exc_info.value)


def test_calendar_epoch_must_be_first_of_month(tmp_path):
    """epoch_start_date with a day other than 1 is rejected (CAL-1)."""
    path = _write_config(
        tmp_path, {"calendar": {"epoch_start_date": "2040-01-15"}}
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "epoch_start_date" in str(exc_info.value)


@pytest.mark.parametrize("bad_months", [0, 13])
def test_calendar_months_per_turn_out_of_bounds_rejected(
    tmp_path, bad_months
):
    """months_per_turn outside [1, 12] raises ValidationError."""
    path = _write_config(
        tmp_path, {"calendar": {"months_per_turn": bad_months}}
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "months_per_turn" in str(exc_info.value)


def test_calendar_legacy_days_per_turn_config_rejected(tmp_path):
    """An old-style calendar with only days_per_turn fails validation."""
    path = _write_config(
        tmp_path,
        {"calendar": {"days_per_turn": 7}},
        drop=[("calendar", "months_per_turn")],
    )

    with pytest.raises(ValidationError) as exc_info:
        CoreConfig.from_yaml(path)

    assert "months_per_turn" in str(exc_info.value)


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


def test_03_registry_select_or_contains_filter():
    """Nation dropdown filter (Spec 03_registry 3.7): the schema accepts
    ``select_or_contains`` on a ``nation`` column, rejects it on other
    types and forbids the redundant ``text`` pairing — the kind already
    includes the «содержит» input."""
    with open(
        RegistryConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)

    # The shipped config already declares it on both nation columns.
    config = RegistryConfig.model_validate(data)
    players_nation = next(
        c for c in config.table("players").columns if c.id == "nation"
    )
    orders_nation = next(
        c for c in config.table("orders").columns if c.id == "nation"
    )
    assert players_nation.filters == ["select_or_contains", "presence"]
    assert orders_nation.filters == ["select_or_contains"]

    # Not a nation type — rejected.
    bad_type = copy.deepcopy(data)
    bad_type["tables"][2]["columns"][2]["filters"] = [
        "select_or_contains"
    ]
    with pytest.raises(ValidationError):
        RegistryConfig.model_validate(bad_type)

    # select_or_contains + text on the same column — redundant, rejected.
    bad_combo = copy.deepcopy(data)
    bad_combo["tables"][2]["columns"][1]["filters"] = [
        "select_or_contains",
        "text",
    ]
    with pytest.raises(ValidationError):
        RegistryConfig.model_validate(bad_combo)
