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
    assert cfg.simplify.tolerance == 0.03


def _committed() -> dict:
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def test_out_of_range_rejected(tmp_path):
    doc = _committed()
    doc["clean"]["sample_points_per_curve"] = 99
    path = tmp_path / "pipeline_config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(PipelineError) as ei:
        load_pipeline_config(path)
    assert ei.value.code == "CONFIG_INVALID"


def test_missing_key_rejected(tmp_path):
    doc = _committed()
    del doc["raster"]
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
