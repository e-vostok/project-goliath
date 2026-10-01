"""Strict Pydantic models for the pipeline's input data files.

``data/map/boundary.yaml``, ``data/map/overrides.yaml`` and
``data/map/ids.lock.json`` are validated before any processing; every violation
is a hard error (``DATA_INVALID`` / ``IDS_LOCK_INVALID``). Cross-file
reference checks live in :func:`collect_reference_errors`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from .errors import DATA_INVALID, IDS_LOCK_INVALID, PipelineError

# Source-name ids as they appear in map.svg / boundary.yaml.
_NAME_RE = r"^[A-Za-z0-9_]+$"
# Lowercase slug of a node key.
_KEY_RE = r"^[a-z0-9_]+$"
# Sea-zone keys additionally start with ``sea_``.
_SEA_KEY_RE = r"^sea_[a-z0-9_]+$"

# Base coordinate space of the source SVG (viewBox 0 0 1200 680).
VIEW_X_MAX = 1200.0
VIEW_Y_MAX = 680.0

MIN_NODE_ID = 1001

_NameStr = Annotated[str, Field(pattern=_NAME_RE)]
_KeyStr = Annotated[str, Field(pattern=_KEY_RE)]
_SeaKeyStr = Annotated[str, Field(pattern=_SEA_KEY_RE)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SvgPoint(_Strict):
    """A [x, y] pair inside the base SVG space (0..1200, 0..680)."""

    x: float = Field(ge=0.0, le=VIEW_X_MAX)
    y: float = Field(ge=0.0, le=VIEW_Y_MAX)

    @model_validator(mode="before")
    @classmethod
    def _from_seq(cls, value):
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError("point must have exactly two coordinates")
            return {"x": value[0], "y": value[1]}
        return value

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


class Boundary(_Strict):
    """``boundary.yaml``: approved game-field provinces."""

    include: list[_NameStr]
    exclude_explicit: list[str]

    @model_validator(mode="after")
    def _check_lists(self) -> Self:
        errors = []
        if len(set(self.include)) != len(self.include):
            errors.append("include contains duplicate names")
        if len(set(self.exclude_explicit)) != len(self.exclude_explicit):
            errors.append("exclude_explicit contains duplicate names")
        both = sorted(set(self.include) & set(self.exclude_explicit))
        if both:
            errors.append(
                f"names listed in both include and exclude_explicit: {both}"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self


class PartPoint(_Strict):
    """``{key, point}`` entry of ``drop_parts`` / ``keep_parts``."""

    key: _KeyStr
    point: SvgPoint


class SeaZone(_Strict):
    key: _SeaKeyStr
    name_ru: str = Field(min_length=1)
    seeds: list[SvgPoint] = Field(min_length=1)


class EdgeAdd(_Strict):
    a: str
    b: str
    type: Literal["land", "coast", "sea", "strait"]


class EdgeRemove(_Strict):
    a: str
    b: str


class Strait(_Strict):
    a: _KeyStr
    b: _KeyStr
    name: str = Field(min_length=1)
    multiplier: float | None = Field(default=None, ge=0.05, le=1.0)

    @model_validator(mode="after")
    def _distinct_ends(self) -> Self:
        if self.a == self.b:
            raise ValueError("strait endpoints must differ")
        return self


class WaterOutside(_Strict):
    name: str = Field(min_length=1)
    point: SvgPoint


class Overrides(_Strict):
    """``overrides.yaml``: approved manual map data (schema of Spec Part 1)."""

    sea_margin: float = Field(ge=1.0, le=200.0)
    sea_margin_shape: Literal["square", "round"]
    sea_margin_smooth: float = Field(ge=0.0, le=50.0)
    lake_max_area: float = Field(ge=1.0, le=1000.0)
    drop_parts: list[PartPoint]
    keep_parts: list[PartPoint]
    sea_zones: list[SeaZone]
    edges_add: list[EdgeAdd]
    edges_remove: list[EdgeRemove]
    straits: list[Strait]
    water_outside: list[WaterOutside]
    technical_exclude: list[_KeyStr]
    names_ru: dict[str, str]

    @model_validator(mode="after")
    def _check_zone_keys_unique(self) -> Self:
        keys = [z.key for z in self.sea_zones]
        if len(set(keys)) != len(keys):
            raise ValueError("sea_zones keys must be unique")
        return self


class IdsLock(_Strict):
    """``ids.lock.json``: append-only ``key -> id`` mapping (INV-M1)."""

    version: Literal[1]
    ids: dict[_KeyStr, int]

    @field_validator("ids")
    @classmethod
    def _check_ids(cls, ids: dict[str, int]) -> dict[str, int]:
        bad = {k: v for k, v in ids.items() if v < MIN_NODE_ID}
        if bad:
            raise ValueError(f"ids below {MIN_NODE_ID}: {bad}")
        values = list(ids.values())
        if len(set(values)) != len(values):
            raise ValueError("ids must be unique")
        return ids


def _load_yaml(path: Path, model: type[BaseModel], code: str = DATA_INVALID):
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineError(code, f"cannot read {path}: {exc}")
    except yaml.YAMLError as exc:
        raise PipelineError(code, f"cannot parse {path}: {exc}")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        details = [
            f"{'->'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
        raise PipelineError(code, f"{path.name} failed validation", details)


def load_boundary(path: Path) -> Boundary:
    return _load_yaml(path, Boundary)


def load_overrides(path: Path) -> Overrides:
    return _load_yaml(path, Overrides)


def load_ids_lock(path: Path) -> IdsLock:
    """Load ``ids.lock.json``; any defect is ``IDS_LOCK_INVALID``."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineError(IDS_LOCK_INVALID, f"cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise PipelineError(IDS_LOCK_INVALID, f"cannot parse {path}: {exc}")
    try:
        return IdsLock.model_validate(raw)
    except ValidationError as exc:
        details = [
            f"{'->'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
        raise PipelineError(
            IDS_LOCK_INVALID, f"{path.name} failed validation", details
        )


def collect_reference_errors(
    overrides: Overrides, boundary: Boundary
) -> list[PipelineError]:
    """Cross-checks of ``overrides.yaml`` against ``boundary.yaml``.

    Land keys must be lowercase slugs of ``include`` names; endpoints matching
    the sea-key shape must be declared ``sea_zones`` keys.
    """
    errors: list[PipelineError] = []
    land_keys = {name.lower() for name in boundary.include}
    sea_keys = {z.key for z in overrides.sea_zones}
    seen: set[tuple[str, str]] = set()

    def land_ref(key: str, where: str) -> None:
        if key not in land_keys and (where, key) not in seen:
            seen.add((where, key))
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"{where}: key {key!r} is not a slug of a boundary "
                    "include name",
                )
            )

    def sea_ref(key: str, where: str) -> None:
        if key not in sea_keys and (where, key) not in seen:
            seen.add((where, key))
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"{where}: sea key {key!r} is not a sea_zones key",
                )
            )

    def endpoint(key: str, where: str) -> None:
        if re.match(_SEA_KEY_RE, key):
            sea_ref(key, where)
        elif re.match(_KEY_RE, key):
            land_ref(key, where)
        else:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"{where}: endpoint {key!r} is not a valid node key",
                )
            )

    for i, item in enumerate(overrides.drop_parts):
        land_ref(item.key, f"drop_parts[{i}]")
    for i, item in enumerate(overrides.keep_parts):
        land_ref(item.key, f"keep_parts[{i}]")
    for i, s in enumerate(overrides.straits):
        land_ref(s.a, f"straits[{i}].a")
        land_ref(s.b, f"straits[{i}].b")
    for i, e in enumerate(overrides.edges_add):
        endpoint(e.a, f"edges_add[{i}].a")
        endpoint(e.b, f"edges_add[{i}].b")
    for i, e in enumerate(overrides.edges_remove):
        endpoint(e.a, f"edges_remove[{i}].a")
        endpoint(e.b, f"edges_remove[{i}].b")
    return errors
