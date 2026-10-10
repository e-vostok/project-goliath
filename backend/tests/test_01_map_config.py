"""
Tests for the 01_map configuration contract (Spec Part 4, Issue 1).

The pair ``configs/01_map.yaml`` ↔ ``MapConfig`` must be config-safe:
strict ranges, ``extra="forbid"`` on every section, and cross-field
rules. A bad value must fail here — in CI — before the server starts.

Pattern follows tests/test_configs_validity.py: every synthetic config
goes through one shared base dict, so a new required key is added in a
single place.
"""

from __future__ import annotations

import os

import pytest
import yaml
from pydantic import ValidationError

from modules._01_map.config_schema import FrameConfig, MapConfig


def _base_config() -> dict:
    """A fully valid 01_map config as a plain dict — the single place
    where new required keys get their valid value."""
    return {
        "view": {
            "frame": {
                "x": 519.1,
                "y": 20.9,
                "width": 221.3,
                "height": 217.3,
            },
            "zoom_max": 16.0,
            "pan_margin_fraction": 0.0,
            "label_min_width_px": 48,
            "search_min_chars": 2,
            "search_max_results": 20,
        },
        "refresh": {
            "tick_refresh_delay_seconds": 5,
            "tick_refresh_jitter_seconds": 30,
            "retry_delay_seconds": 10,
            "max_retries": 3,
            "stale_after_seconds": 900,
        },
        "colors": {
            "neutral_province": "#8C8C8C",
            "sea": "#1E3547",
            "outside": "#2A2A2A",
            "inland_water": "#1E3547",
            "province_border": "#3A3A3A",
            "land_underlay": "#8C8C8C",
            "hover": "#FFFFFF",
        },
        "hover": {"fill_opacity": 0.14, "stroke_enabled": False},
        "borders": {
            "internal_width": 0.7,
            "internal_opacity": 0.55,
            "internal_color": "#3A3A3A",
            "state_width": 1.8,
            "state_color": "#101014",
            "coast_width": 0.9,
            "coast_color": "#24262B",
        },
        "selection": {
            "pulse_min_opacity": 0.10,
            "pulse_max_opacity": 0.32,
            "pulse_period_s": 2.4,
            "picked_opacity": 0.28,
        },
        "strait": {"default_crossing_multiplier": 0.5},
        "starting_group": {"require_connected": True},
        "big_window": {"enabled": True},
        "limits": {
            "max_nodes": 3000,
            "max_edges_per_node": 60,
            "max_geometry_bytes": 5_000_000,
            "max_manifest_bytes": 3_000_000,
            "max_borders_bytes": 2_000_000,
        },
        "attribution": {"text": "Карта: MapChart.net, лицензия CC BY-SA 4.0"},
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
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


class TestRealConfig:
    def test_real_yaml_loads(self):
        config = MapConfig.from_yaml(MapConfig.get_default_config_path())

        assert config.big_window.enabled is True
        assert config.view.frame.width > 0
        assert config.view.frame.height > 0
        assert config.view.zoom_max > 1.0
        assert config.limits.max_nodes >= 1067  # map2_11 node count

    @pytest.mark.parametrize(
        "cwd_name",
        [
            os.path.join("backend", "src"),
            os.path.join("backend", "tests"),
        ],
    )
    def test_default_path_resolves_from_any_cwd(
        self, tmp_path, monkeypatch, cwd_name
    ):
        """get_default_config_path is resolved relative to the schema
        file, so loading works from src/ and tests/ alike."""
        from pathlib import Path

        repo_root = Path(MapConfig.get_default_config_path()).parents[1]
        monkeypatch.chdir(repo_root / cwd_name)

        config = MapConfig.from_yaml(MapConfig.get_default_config_path())
        assert config.big_window.enabled is True


class TestUnknownKeys:
    def test_unknown_top_level_key_rejected(self, tmp_path):
        data = _base_config()
        data["typo_section"] = {"x": 1}
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")

        with pytest.raises(ValidationError):
            MapConfig.from_yaml(str(path))

    def test_unknown_nested_key_rejected(self, tmp_path):
        path = _write_config(
            tmp_path, {"big_window": {"surprise": 1}}
        )

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert "surprise" in str(exc_info.value)

    def test_removed_big_window_method_key_rejected(self, tmp_path):
        """The pre-1.6 big_window.method key must be rejected — strict
        extra='forbid' is exactly what guards removed keys."""
        path = _write_config(
            tmp_path, {"big_window": {"method": "fullscreen"}}
        )

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert "method" in str(exc_info.value)


class TestRanges:
    @pytest.mark.parametrize(
        "section,key,value",
        [
            ("view", "zoom_max", 40.01),
            ("view", "zoom_max", 41),
            ("strait", "default_crossing_multiplier", 0),
            ("strait", "default_crossing_multiplier", 1.01),
            ("limits", "max_edges_per_node", 3),
            ("limits", "max_edges_per_node", 101),
            ("limits", "max_nodes", 99),
            ("limits", "max_nodes", 20001),
            ("attribution", "text", ""),
        ],
    )
    def test_out_of_range_rejected(self, tmp_path, section, key, value):
        path = _write_config(tmp_path, {section: {key: value}})

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert key in str(exc_info.value)


class TestFrame:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("x", -0.1),
            ("y", -0.1),
            ("width", 0.0),
            ("width", -1.0),
            ("height", 0.0),
            ("height", -1.0),
        ],
    )
    def test_frame_bounds_rejected(self, tmp_path, field, value):
        """FrameConfig: x/y are >= 0, width/height are > 0."""
        frame = {
            "x": 519.1,
            "y": 20.9,
            "width": 221.3,
            "height": 217.3,
            field: value,
        }
        path = _write_config(tmp_path, {"view": {"frame": frame}})

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert field in str(exc_info.value)


class TestHover:
    def test_fill_opacity_range(self, tmp_path):
        """map2_0: hover.fill_opacity stays inside [0.0, 0.6] — the fill
        must never fully hide the owner colour nor vanish unnoticed."""
        for bad in (-0.01, 0.61):
            path = _write_config(
                tmp_path, {"hover": {"fill_opacity": bad}}
            )
            with pytest.raises(ValidationError) as exc_info:
                MapConfig.from_yaml(path)
            assert "fill_opacity" in str(exc_info.value)
        for edge in (0.0, 0.6):
            path = _write_config(
                tmp_path, {"hover": {"fill_opacity": edge}}
            )
            assert MapConfig.from_yaml(path).hover.fill_opacity == edge


class TestCrossFieldRules:

    @pytest.mark.parametrize(
        "field,value",
        [
            ("neutral_province", "#1E3547"),  # collides with sea
            ("sea", "#8C8C8C"),               # collides with neutral_province
            ("outside", "#8C8C8C"),           # collides with neutral_province
        ],
    )
    def test_equal_base_colors_rejected(self, tmp_path, field, value):
        path = _write_config(tmp_path, {"colors": {field: value}})

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert "distinct" in str(exc_info.value)

    @pytest.mark.parametrize(
        "section,key,bad",
        [
            ("colors", "sea", "1E3547"),       # missing '#'
            ("colors", "hover", "#FFF"),       # too short
            ("colors", "outside", "#GGGGGG"),  # not hex
            ("borders", "state_color", "#FF00000"),  # too long
        ],
    )
    def test_invalid_hex_color_rejected(self, tmp_path, section, key, bad):
        path = _write_config(tmp_path, {section: {key: bad}})

        with pytest.raises(ValidationError) as exc_info:
            MapConfig.from_yaml(path)

        assert key in str(exc_info.value)


class TestSchemaYamlParity:
    """Every YAML key maps to a schema field and every schema field is
    present in the YAML — no silent defaults (Spec Part 4)."""

    @staticmethod
    def _flatten_yaml(data: dict, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for key, value in data.items():
            path = f"{prefix}{key}"
            keys.add(path)
            if isinstance(value, dict):
                keys |= TestSchemaYamlParity._flatten_yaml(
                    value, path + "."
                )
        return keys

    @staticmethod
    def _flatten_model(model, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for name, field in model.model_fields.items():
            path = f"{prefix}{name}"
            keys.add(path)
            annotation = field.annotation
            if hasattr(annotation, "model_fields"):
                keys |= TestSchemaYamlParity._flatten_model(
                    annotation, path + "."
                )
        return keys

    def test_yaml_keys_and_schema_fields_match(self):
        yaml_path = MapConfig.get_default_config_path()
        with open(yaml_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        yaml_keys = self._flatten_yaml(raw)
        schema_keys = self._flatten_model(MapConfig)

        assert yaml_keys == schema_keys
