"""Config-Safe schema for the map pipeline's own configuration.

Every tunable of the tool lives in ``tools/map_pipeline/pipeline_config.yaml``
and is validated here against hard ranges. Unknown keys are forbidden: a typo
in a key name fails the run instead of being silently ignored.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import CONFIG_INVALID, PipelineError

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "pipeline_config.yaml"


class _Strict(BaseModel):
    """Base section model: unknown keys are forbidden."""

    model_config = ConfigDict(extra="forbid")


class CleanConfig(_Strict):
    """Path cleanup: curve sampling and degenerate-part removal (step 2)."""

    sample_points_per_curve: int = Field(ge=2, le=16)
    min_part_area: float = Field(ge=0.0, le=0.1)


class IsolatedConfig(_Strict):
    """Isolated-part detection (step 3): buffer and minimum part area."""

    neighbour_buffer: float = Field(ge=0.05, le=1.0)
    min_part_area: float = Field(ge=0.0, le=0.5)


class GeometryConfig(_Strict):
    """Border metrics for edge detection (MP-2)."""

    border_epsilon: float = Field(ge=0.005, le=0.2)
    min_border_length: float = Field(ge=0.05, le=2.0)


class RasterConfig(_Strict):
    """Rasterisation density for sea-zone construction (MP-2)."""

    pixels_per_unit: int = Field(ge=1, le=16)


class SeaConfig(_Strict):
    """Sea-zone seeds: snapping radius in SVG units (MP-2)."""

    seed_snap_radius: float = Field(ge=0.25, le=3.0)


class ReportConfig(_Strict):
    """graph_report.md thresholds (MP-2)."""

    land_degree_warn: int = Field(ge=6, le=40)
    small_area_warn: float = Field(ge=0.0, le=2.0)
    largest_lakes: int = Field(ge=1, le=50)


class PreviewColors(_Strict):
    """Map preview palette: hard copies of the Spec Part 4 defaults."""

    inland_water: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    outside: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    sea: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    land: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    border: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    sea_border: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class PreviewConfig(_Strict):
    """PNG preview density in pixels per SVG unit."""

    pixels_per_unit: int = Field(ge=2, le=12)
    crop_pixels_per_unit: int = Field(ge=2, le=24)
    colors: PreviewColors


class SimplifyConfig(_Strict):
    """Contour simplification tolerances (MP-3)."""

    tolerance: float = Field(ge=0.0, le=0.2)
    small_part_factor: float = Field(ge=0.0, le=0.2)
    sea_tolerance: float = Field(ge=0.05, le=1.0)


class ViewConfig(_Strict):
    """Source root viewBox the tool expects (MP-3)."""

    width: int = Field(ge=100, le=4000)
    height: int = Field(ge=100, le=4000)


class GeorefConfig(_Strict):
    """Gall-stereographic georeference constants (Spec 3.7)."""

    x0: float
    k: float = Field(gt=0.0)
    y0: float
    m: float = Field(gt=0.0)


class OutputConfig(_Strict):
    """Output coordinate grid in SVG units (MP-3)."""

    grid: float = Field(ge=0.001, le=0.1)


class SeaCutConfig(_Strict):
    """Zone growth into land and leftover-water fill (MP-3, Spec 1.5)."""

    dilate_pixels: int = Field(ge=1, le=4)
    fill_max_area: float = Field(ge=0.0, le=20.0)


class OutsideConfig(_Strict):
    """``outside`` contour: sliver closing, underlap, minimum hole (MP-3)."""

    closing: float = Field(ge=0.01, le=0.5)
    underlap: float = Field(ge=0.0, le=0.2)
    min_hole_area: float = Field(ge=0.0, le=0.5)
    lake_near_land: float = Field(ge=0.0, le=2.0)


class LimitsConfig(_Strict):
    """Server-side size limits mirrored for the tool (Spec Part 4)."""

    max_nodes: int = Field(ge=100, le=20000)
    max_edges_per_node: int = Field(ge=4, le=100)
    max_geometry_bytes: int = Field(ge=100_000, le=20_000_000)
    max_manifest_bytes: int = Field(ge=100_000, le=20_000_000)


class PipelineConfig(_Strict):
    """Root configuration model; every section is required."""

    clean: CleanConfig
    isolated: IsolatedConfig
    geometry: GeometryConfig
    raster: RasterConfig
    sea: SeaConfig
    report: ReportConfig
    preview: PreviewConfig
    simplify: SimplifyConfig
    view: ViewConfig
    georef: GeorefConfig
    output: OutputConfig
    sea_cut: SeaCutConfig
    outside: OutsideConfig
    limits: LimitsConfig


def load_pipeline_config(path: Path = DEFAULT_CONFIG_PATH) -> PipelineConfig:
    """Load and validate ``pipeline_config.yaml``.

    Any failure is a hard error with code ``CONFIG_INVALID``.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineError(CONFIG_INVALID, f"cannot read config {path}: {exc}")
    except yaml.YAMLError as exc:
        raise PipelineError(CONFIG_INVALID, f"cannot parse config {path}: {exc}")
    try:
        return PipelineConfig.model_validate(raw)
    except ValidationError as exc:
        details = [
            f"{'->'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
        raise PipelineError(
            CONFIG_INVALID,
            f"pipeline config {path} failed validation",
            details,
        )
