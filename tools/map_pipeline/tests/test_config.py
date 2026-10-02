"""Config-Safe checks for pipeline_config.yaml."""
from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from tools.map_pipeline.errors import PipelineError
from tools.map_pipeline.pipeline_config_schema import (
    DEFAULT_CONFIG_PATH,
    PipelineConfig,
    load_pipeline_config,
)


def test_committed_config_validates():
    cfg = load_pipeline_config()
    assert cfg.clean.sample_points_per_curve == 4
    assert cfg.clean.min_part_area == 0.001
    assert cfg.isolated.neighbour_buffer == 0.3
    assert cfg.isolated.min_part_area == 0.01
    assert cfg.geometry.border_epsilon == 0.04
    assert cfg.geometry.min_border_length == 0.3
    assert cfg.raster.pixels_per_unit == 4
    assert cfg.sea.seed_snap_radius == 1.0
    assert cfg.report.land_degree_warn == 12
    assert cfg.report.small_area_warn == 0.1
    assert cfg.report.largest_lakes == 10
    assert cfg.preview.pixels_per_unit == 6
    assert cfg.preview.crop_pixels_per_unit == 12
    assert cfg.preview.colors.inland_water == "#3E6B84"
    assert cfg.preview.colors.outside == "#2A2A2A"
    assert cfg.preview.colors.sea == "#1E3547"
    assert cfg.preview.colors.land == "#8C8C8C"
    assert cfg.preview.colors.border == "#3A3A3A"
    assert cfg.preview.colors.sea_border == "#2C4A62"
    assert cfg.simplify.tolerance == 0.03
    assert cfg.simplify.sea_tolerance == 0.3
    assert cfg.view.width == 1200
    assert cfg.view.height == 680
    assert cfg.georef.x0 == 562.53
    assert cfg.georef.k == 3.339
    assert cfg.georef.y0 == 353.34
    assert cfg.georef.m == 459.3
    assert cfg.output.grid == 0.01
    assert cfg.sea_cut.dilate_pixels == 2
    assert cfg.sea_cut.fill_max_area == 3.0
    assert cfg.outside.closing == 0.3
    assert cfg.outside.underlap == 0.05
    assert cfg.outside.min_hole_area == 0.02
    assert cfg.outside.lake_near_land == 0.2
    assert cfg.limits.max_nodes == 3000
    assert cfg.limits.max_edges_per_node == 60
    assert cfg.limits.max_geometry_bytes == 5_000_000
    assert cfg.limits.max_manifest_bytes == 3_000_000


def _committed() -> dict:
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "section, key, value",
    [
        ("clean", "sample_points_per_curve", 99),
        ("sea", "seed_snap_radius", 0.1),
        ("sea", "seed_snap_radius", 9.0),
        ("report", "land_degree_warn", 3),
        ("report", "small_area_warn", -1.0),
        ("report", "largest_lakes", 0),
        ("preview", "pixels_per_unit", 13),
        ("simplify", "sea_tolerance", 0.01),
        ("simplify", "sea_tolerance", 1.5),
        ("view", "width", 50),
        ("georef", "k", 0.0),
        ("georef", "m", -1.0),
        ("output", "grid", 0.0001),
        ("output", "grid", 0.5),
        ("sea_cut", "dilate_pixels", 0),
        ("sea_cut", "dilate_pixels", 9),
        ("sea_cut", "fill_max_area", -0.5),
        ("sea_cut", "fill_max_area", 25.0),
        ("outside", "closing", 0.001),
        ("outside", "underlap", 0.5),
        ("outside", "min_hole_area", 1.0),
        ("outside", "lake_near_land", -0.1),
        ("outside", "lake_near_land", 3.0),
        ("limits", "max_nodes", 50),
        ("limits", "max_edges_per_node", 3),
        ("limits", "max_geometry_bytes", 10),
        ("limits", "max_manifest_bytes", 99_000_000),
    ],
)
def test_out_of_range_rejected(tmp_path, section, key, value):
    doc = _committed()
    doc[section][key] = value
    path = tmp_path / "pipeline_config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(PipelineError) as ei:
        load_pipeline_config(path)
    assert ei.value.code == "CONFIG_INVALID"


@pytest.mark.parametrize(
    "section",
    ["raster", "sea", "report", "preview", "simplify", "view", "georef",
     "output", "sea_cut", "outside", "limits"],
)
def test_missing_key_rejected(tmp_path, section):
    doc = _committed()
    del doc[section]
    path = tmp_path / "pipeline_config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(PipelineError) as ei:
        load_pipeline_config(path)
    assert ei.value.code == "CONFIG_INVALID"


def test_missing_subkey_rejected(tmp_path):
    doc = _committed()
    del doc["sea"]["seed_snap_radius"]
    path = tmp_path / "pipeline_config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(PipelineError) as ei:
        load_pipeline_config(path)
    assert ei.value.code == "CONFIG_INVALID"


def test_unknown_key_rejected():
    doc = _committed()
    doc["clean"]["bogus"] = 1
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(doc)
    doc = _committed()
    doc["bogus_section"] = {}
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate(doc)
