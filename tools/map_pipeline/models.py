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
    # 1.9: a retired zone still competes for water pixels but produces no
    # node, no edges and no path; its id stays in ids.lock.json.
    retired: bool = False


class TransferPatch(_Strict):
    """``geometry_patches[].transfer`` — land of ``from`` inside ``polygon``
    moves to ``to`` (Spec, Appendix A step 3a)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_key: _KeyStr = Field(alias="from")
    to_key: _KeyStr = Field(alias="to")
    polygon: list[SvgPoint] = Field(min_length=3)


class SplitPatch(_Strict):
    """``geometry_patches[].split`` — a polyline cuts one included province
    into two nodes (map2_2). The part containing ``keep_point`` keeps the
    old key and id; the other becomes a new node ``new_key``/``new_name``.
    """

    key: _KeyStr
    line: list[SvgPoint] = Field(min_length=2)
    keep_point: SvgPoint
    new_key: _KeyStr
    new_name: _NameStr

    @model_validator(mode="after")
    def _key_matches_name(self) -> Self:
        if self.new_key != self.new_name.lower():
            raise ValueError(
                "split.new_key must equal new_name.lower() "
                f"({self.new_key!r} != {self.new_name.lower()!r})"
            )
        return self


class GeometryPatch(_Strict):
    """One ``geometry_patches`` entry: exactly one of ``transfer``/``split``."""

    transfer: TransferPatch | None = None
    split: SplitPatch | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.transfer is None) == (self.split is None):
            raise ValueError(
                "a geometry_patches entry needs exactly one of "
                "'transfer' or 'split'"
            )
        return self


class EdgeAdd(_Strict):
    a: str
    b: str
    type: Literal["land", "coast", "sea", "strait"]


class EdgeRemove(_Strict):
    a: str
    b: str


class LandLink(_Strict):
    """``land_links[]`` — a forced ``land`` edge between two LAND nodes
    whose contours touch below ``min_border_length`` (map2_10). Written
    as a plain ``[a, b]`` pair in the YAML."""

    a: _KeyStr
    b: _KeyStr

    @model_validator(mode="before")
    @classmethod
    def _from_seq(cls, value):
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError("land_links entries are [a, b] pairs")
            return {"a": value[0], "b": value[1]}
        return value

    @model_validator(mode="after")
    def _distinct_ends(self) -> Self:
        if self.a == self.b:
            raise ValueError("land_link endpoints must differ")
        return self


class Rename(_Strict):
    """``renames[]`` — the node keeps its id and geometry while its key
    and display ``name`` change (map2_10). ``from`` is the slug of the
    source province id (never changes); ``to`` is the new node key."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_key: _KeyStr = Field(alias="from")
    to_key: _KeyStr = Field(alias="to")
    name: str = Field(min_length=1)


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
    # map2_10: forced land edges for touching contours below
    # ``geometry.min_border_length``, and key renames that keep the id.
    land_links: list[LandLink] = Field(default_factory=list)
    renames: list[Rename] = Field(default_factory=list)
    water_outside: list[WaterOutside]
    technical_exclude: list[_KeyStr]
    names_ru: dict[str, str]
    geometry_patches: list[GeometryPatch] = Field(default_factory=list)
    # 1.9 (step 5a): small water bodies within ``sea_link_gap`` of zone or
    # unexplored-sea water are bays (sea colour); ``sea_like_water`` points
    # force the bay class, ``lake_force`` points force the lake class.
    sea_like_water: list[SvgPoint] = Field(default_factory=list)
    lake_force: list[SvgPoint] = Field(default_factory=list)
    sea_link_gap: float = Field(default=0.6, ge=0.0, le=50.0)

    @model_validator(mode="after")
    def _check_zone_keys_unique(self) -> Self:
        keys = [z.key for z in self.sea_zones]
        if len(set(keys)) != len(keys):
            raise ValueError("sea_zones keys must be unique")
        return self


class IdsLock(_Strict):
    """``ids.lock.json``: append-only ``key -> id`` mapping (INV-M1).

    ``previous_keys`` records key renames (map2_10): for every current
    key that replaced an earlier slug, the ordered list of its former
    keys — the id never changes, the history is kept so the lock stays
    append-only in spirit.
    """

    version: Literal[1]
    ids: dict[_KeyStr, int]
    previous_keys: dict[_KeyStr, list[_KeyStr]] = Field(
        default_factory=dict
    )

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

    @model_validator(mode="after")
    def _check_previous_keys(self) -> Self:
        for key, chain in self.previous_keys.items():
            if key not in self.ids:
                raise ValueError(
                    f"previous_keys entry {key!r} is not an ids.lock key"
                )
            if not chain:
                raise ValueError(
                    f"previous_keys entry {key!r} has an empty chain"
                )
            if len(set(chain)) != len(chain):
                raise ValueError(
                    f"previous_keys entry {key!r} repeats a key"
                )
            dead = [k for k in chain if k in self.ids]
            if dead:
                raise ValueError(
                    f"previous_keys entry {key!r} lists live keys: {dead}"
                )
        return self


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
    excluded_keys = {name.lower() for name in boundary.exclude_explicit}
    # geometry_patches apply to the source geometry before the boundary
    # filter, so a ``from`` key may name an excluded province.
    patch_names = land_keys | excluded_keys
    sea_keys = {z.key for z in overrides.sea_zones}
    split_new_keys = {
        p.split.new_key
        for p in overrides.geometry_patches
        if p.split is not None
    }
    seen: set[tuple[str, str]] = set()

    # map2_10: ``renames`` rewrite the key AFTER selection, so every
    # downstream section (straits, edges, names_ru, land_links,
    # drop_parts/keep_parts) addresses nodes by their NEW key, while
    # ``geometry_patches`` keep working on source keys.
    renamed: dict[str, str] = {}
    seen_to: set[str] = set()
    for i, r in enumerate(overrides.renames):
        if r.from_key in renamed:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"renames[{i}].from: key {r.from_key!r} is renamed "
                    "twice",
                )
            )
        renamed[r.from_key] = r.to_key
        if r.from_key not in land_keys:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"renames[{i}].from: key {r.from_key!r} is not a "
                    "slug of a boundary include name",
                )
            )
        elif r.from_key in set(overrides.technical_exclude):
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"renames[{i}].from: key {r.from_key!r} is "
                    "technically excluded — there is no node to rename",
                )
            )
        if re.match(_SEA_KEY_RE, r.to_key):
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"renames[{i}].to: {r.to_key!r} looks like a "
                    "sea-zone key; land keys must not start with 'sea_'",
                )
            )
        elif (
            r.to_key in patch_names
            or r.to_key in sea_keys
            or r.to_key in split_new_keys
            or r.to_key in seen_to
        ):
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"renames[{i}].to: key {r.to_key!r} collides with "
                    "an existing node or an earlier rename",
                )
            )
        seen_to.add(r.to_key)
    node_keys = (
        (land_keys - set(renamed)) | set(renamed.values()) | split_new_keys
    )

    def land_ref(key: str, where: str) -> None:
        if key in renamed and (where, key) not in seen:
            seen.add((where, key))
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"{where}: key {key!r} was renamed to "
                    f"{renamed[key]!r} — use the new key",
                )
            )
        elif key not in node_keys and (where, key) not in seen:
            seen.add((where, key))
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"{where}: key {key!r} is not a node key",
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
        # Sea keys are well-formed references here; the graph layer then
        # rejects them as EDGE_TYPE_MISMATCH (straits join LAND only).
        endpoint(s.a, f"straits[{i}].a")
        endpoint(s.b, f"straits[{i}].b")
    for i, e in enumerate(overrides.edges_add):
        endpoint(e.a, f"edges_add[{i}].a")
        endpoint(e.b, f"edges_add[{i}].b")
    for i, e in enumerate(overrides.edges_remove):
        endpoint(e.a, f"edges_remove[{i}].a")
        endpoint(e.b, f"edges_remove[{i}].b")
    seen_links: set[tuple[str, str]] = set()
    for i, e in enumerate(overrides.land_links):
        endpoint(e.a, f"land_links[{i}].a")
        endpoint(e.b, f"land_links[{i}].b")
        pair = tuple(sorted((e.a, e.b)))
        if pair in seen_links:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"land_links[{i}]: pair {e.a!r}-{e.b!r} is listed "
                    "twice",
                )
            )
        seen_links.add(pair)
    for key in overrides.names_ru:
        land_ref(key, "names_ru")
    seen_new_keys: set[str] = set()
    for i, patch in enumerate(overrides.geometry_patches):
        t = patch.transfer
        if t is not None:
            for key, side in ((t.from_key, "from"), (t.to_key, "to")):
                if key not in patch_names:
                    errors.append(
                        PipelineError(
                            DATA_INVALID,
                            f"geometry_patches[{i}].transfer.{side}: key "
                            f"{key!r} is not a slug of a boundary name",
                        )
                    )
                elif side == "to" and key not in land_keys:
                    errors.append(
                        PipelineError(
                            DATA_INVALID,
                            f"geometry_patches[{i}].transfer.to: key {key!r} "
                            "names an excluded province — the receiving side "
                            "must stay in the game",
                        )
                    )
            continue
        s = patch.split
        if s.key not in land_keys:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"geometry_patches[{i}].split.key: key {s.key!r} is not "
                    "a slug of a boundary include name — a split target "
                    "must be in the game",
                )
            )
        if re.match(_SEA_KEY_RE, s.new_key):
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"geometry_patches[{i}].split.new_key: {s.new_key!r} "
                    "looks like a sea-zone key; new land keys must not "
                    "start with 'sea_'",
                )
            )
        if s.new_key in patch_names or s.new_key in seen_new_keys:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"geometry_patches[{i}].split.new_key: key "
                    f"{s.new_key!r} collides with an existing province or "
                    "an earlier split",
                )
            )
        seen_new_keys.add(s.new_key)
    return errors
