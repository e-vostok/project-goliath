"""
Strict Pydantic v2 models of the map data files (Spec 1.6, Part 1).

These schemas mirror what ``tools/map_pipeline`` emits: the pipeline's
``manifest_schema.py`` is the authoritative shape reference, and these
models accept exactly that shape — every key modelled, ``extra="forbid"``,
no ``extra="allow"`` anywhere.

Scope of this layer: *structural* sanity only (types, patterns, ranges,
unknown keys). Cross-entity rules belong to the loader's invariant checks
(INV-M1/M2/M3/M6), so that violations surface under their stable codes
instead of a generic schema error — e.g. ``a < b``, pair uniqueness,
endpoint kinds and multiplier placement are checked as ``INV_M2`` in
``loader.py``, not here.

``boundary.yaml`` and ``overrides.yaml`` are intentionally NOT modelled:
the server never parses them at runtime; they only participate in the
INV-M10 input-hash check (the pipeline validates their structure).
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Literal, Mapping, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

_HEX64 = r"^[0-9a-f]{64}$"
_HEX12 = r"^[0-9a-f]{12}$"
_KEY_RE = r"^[a-z0-9_]+$"
_PATH_KEY_RE = r"^[0-9]+$"

# Conservative SVG path charset: the strings are later inserted into the
# page, so anything outside commands/numbers/separators is refused.
_SVG_PATH_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\-\s]+$")


def _svg_path(value: str) -> str:
    """field_validator body: reject any character outside the SVG charset."""
    if not _SVG_PATH_RE.fullmatch(value):
        raise ValueError("SVG path contains characters outside the allowed charset")
    return value


class _Strict(BaseModel):
    """No unknown keys, no mutation after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Georef(_Strict):
    """``manifest.georef`` — projection parameters (Spec 3.7)."""

    projection: Literal["gall_stereographic"]
    x0: FiniteFloat
    k: FiniteFloat
    y0: FiniteFloat
    m: FiniteFloat


class InputsSha256(_Strict):
    """``manifest.inputs_sha256`` — recorded hashes of the four inputs."""

    source: str = Field(pattern=_HEX64)
    boundary: str = Field(pattern=_HEX64)
    overrides: str = Field(pattern=_HEX64)
    ids_lock: str = Field(pattern=_HEX64)


class ManifestNode(_Strict):
    """One node of ``manifest.nodes`` (a land province or a sea zone)."""

    id: int = Field(ge=1)
    key: str = Field(pattern=_KEY_RE)
    kind: Literal["LAND", "SEA"]
    name: str | None
    name_ru: str | None
    source_name: str | None
    anchor: tuple[FiniteFloat, FiniteFloat]
    bbox: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    area: FiniteFloat = Field(ge=0.0)

    @model_validator(mode="after")
    def _kind_fields(self) -> Self:
        # Same contract the pipeline enforces when emitting the manifest.
        if self.kind == "SEA":
            if self.source_name is not None:
                raise ValueError("SEA node must have source_name null")
            if self.name != self.name_ru:
                raise ValueError("SEA node name must equal name_ru")
        else:
            if not self.name:
                raise ValueError("LAND node needs a name")
            if not self.source_name:
                raise ValueError("LAND node needs a source_name")
        return self


class ManifestEdge(_Strict):
    """
    One edge of ``manifest.edges``.

    Field placement rules (``name``/``multiplier`` only on ``strait``,
    ``len`` never on ``strait``, ``a < b``, pair uniqueness, endpoint
    kinds) are INV-M2 territory and are checked by the loader.
    """

    a: int = Field(ge=1)
    b: int = Field(ge=1)
    type: Literal["land", "coast", "sea", "strait"]
    len: FiniteFloat | None = None
    name: str | None = None
    multiplier: FiniteFloat | None = None


class Manifest(_Strict):
    """``manifest.json`` — nodes, edges, versions and input hashes."""

    schema_version: Literal[1]
    geometry_version: str = Field(pattern=_HEX12)
    view_box: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    playable_bbox: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    georef: Georef
    inputs_sha256: InputsSha256
    nodes: tuple[ManifestNode, ...]
    edges: tuple[ManifestEdge, ...]


class Geometry(_Strict):
    """``geometry.json`` — SVG path per node id, the ``outside`` ring and
    the ``sea_water`` bays path (1.9 step 5a; may be empty)."""

    version: str = Field(pattern=_HEX12)
    paths: Mapping[str, str]
    outside: str
    sea_water: str

    @field_validator("paths")
    @classmethod
    def _paths_strict(cls, paths: Mapping[str, str]) -> Mapping[str, str]:
        out = dict(paths)
        for key, value in out.items():
            if not re.fullmatch(_PATH_KEY_RE, key):
                raise ValueError(
                    f"geometry path key {key!r} is not a node id"
                )
            _svg_path(value)
        return MappingProxyType(out)

    @field_validator("outside")
    @classmethod
    def _outside_charset(cls, value: str) -> str:
        return _svg_path(value)

    @field_validator("sea_water")
    @classmethod
    def _sea_water_charset(cls, value: str) -> str:
        return _svg_path(value) if value else value


class IdsLock(_Strict):
    """
    ``ids.lock.json`` — append-only ``key -> id`` map (INV-M1).

    Uniqueness of the id values and manifest correspondence are INV-M1
    checks in the loader; entries absent from the manifest are legal
    (the lock only grows) and surface as ``MapData.warnings``.
    """

    version: Literal[1]
    ids: Mapping[str, int]

    @field_validator("ids")
    @classmethod
    def _ids_strict(
        cls, ids: Mapping[str, int]
    ) -> Mapping[str, int]:
        out = dict(ids)
        for key, value in out.items():
            if not re.fullmatch(_KEY_RE, key):
                raise ValueError(f"ids.lock key {key!r} is not a key slug")
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"ids.lock id for {key!r} must be a positive int")
        return MappingProxyType(out)
