"""Strict schema checks for data/map/boundary.yaml and overrides.yaml."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tools.map_pipeline.models import (
    Boundary,
    Overrides,
    collect_reference_errors,
    load_boundary,
    load_overrides,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "map"


def _commited(name: str) -> dict:
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


def test_committed_boundary_and_overrides_validate():
    boundary = load_boundary(DATA_DIR / "boundary.yaml")
    overrides = load_overrides(DATA_DIR / "overrides.yaml")
    assert len(boundary.include) == 1030
    assert len(boundary.exclude_explicit) == 194
    assert len(overrides.sea_zones) == 37
    # map2_10: 15 legacy straits + 30 workbook-approved crossings.
    assert len(overrides.straits) == 45
    assert len(overrides.land_links) == 3
    assert len(overrides.renames) == 4
    assert len(overrides.drop_parts) == 1
    assert {z.key for z in overrides.sea_zones if z.retired} == {
        "sea_atl_africa",
        "sea_iceland",
    }
    # map2_11: alexandria split + seam seam_repair + 7 transfer_part
    # + 1 detach.
    assert len(overrides.geometry_patches) == 10
    assert len(overrides.seam_repair) == 8
    assert overrides.names_ru.get("faroe_islands") == "Фареры"
    assert collect_reference_errors(overrides, boundary) == []


def _mini_boundary() -> Boundary:
    return Boundary.model_validate(
        {"include": ["Kent", "Ponthieu"], "exclude_explicit": []}
    )


def _mini_overrides(**kw) -> dict:
    doc = dict(
        sea_margin=30.0,
        sea_margin_shape="square",
        sea_margin_smooth=10.0,
        lake_max_area=70.0,
        sea_like_water=[],
        lake_force=[],
        sea_link_gap=0.6,
        drop_parts=[],
        keep_parts=[],
        sea_zones=[],
        edges_add=[],
        edges_remove=[],
        straits=[],
        water_outside=[],
        technical_exclude=[],
        names_ru={},
    )
    doc.update(kw)
    return doc


def test_seed_outside_view_rejected():
    doc = _mini_overrides(
        sea_zones=[
            {"key": "sea_x", "name_ru": "X", "seeds": [[1300.0, 10.0]]}
        ]
    )
    with pytest.raises(ValidationError):
        Overrides.model_validate(doc)


def test_duplicate_zone_key_rejected():
    zone = {"key": "sea_x", "name_ru": "X", "seeds": [[10.0, 10.0]]}
    doc = _mini_overrides(sea_zones=[zone, dict(zone)])
    with pytest.raises(ValidationError):
        Overrides.model_validate(doc)


def test_zone_key_without_sea_prefix_rejected():
    doc = _mini_overrides(
        sea_zones=[
            {"key": "ocean_x", "name_ru": "X", "seeds": [[10.0, 10.0]]}
        ]
    )
    with pytest.raises(ValidationError):
        Overrides.model_validate(doc)


def test_strait_same_ends_rejected():
    doc = _mini_overrides(
        straits=[{"a": "kent", "b": "kent", "name": "X", "multiplier": None}]
    )
    with pytest.raises(ValidationError):
        Overrides.model_validate(doc)


def test_unknown_strait_key_rejected():
    boundary = _mini_boundary()
    overrides = Overrides.model_validate(
        _mini_overrides(
            straits=[
                {
                    "a": "kent",
                    "b": "nowhere",
                    "name": "X",
                    "multiplier": None,
                }
            ]
        )
    )
    errors = collect_reference_errors(overrides, boundary)
    assert errors and all(e.code == "DATA_INVALID" for e in errors)


def test_edges_add_sea_endpoint_must_be_zone():
    boundary = _mini_boundary()
    overrides = Overrides.model_validate(
        _mini_overrides(
            edges_add=[{"a": "sea_unknown", "b": "kent", "type": "sea"}]
        )
    )
    errors = collect_reference_errors(overrides, boundary)
    assert errors and "sea_unknown" in errors[0].message


def test_edges_add_known_zone_ok():
    boundary = _mini_boundary()
    overrides = Overrides.model_validate(
        _mini_overrides(
            sea_zones=[
                {"key": "sea_x", "name_ru": "X", "seeds": [[10.0, 10.0]]}
            ],
            edges_add=[{"a": "sea_x", "b": "kent", "type": "sea"}],
        )
    )
    assert collect_reference_errors(overrides, boundary) == []


def test_boundary_duplicate_include_rejected():
    with pytest.raises(ValidationError):
        Boundary.model_validate(
            {"include": ["Alpha", "Alpha"], "exclude_explicit": []}
        )


def test_boundary_include_exclude_overlap_rejected():
    with pytest.raises(ValidationError):
        Boundary.model_validate(
            {"include": ["Alpha"], "exclude_explicit": ["Alpha"]}
        )
