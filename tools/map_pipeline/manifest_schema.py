"""Strict schema and invariant checks for ``manifest.json`` (MP-3).

The generated manifest is validated *before* anything is written: the
Pydantic model pins the field lists (``extra="forbid"``) and formats, then
:func:`validate_manifest` enforces INV-M1 (unique ids >= 1001), INV-M2
(sorted unique ``(a, b)`` pairs, ``a < b``, valid endpoint kinds), INV-M3
(a single connected component), ``geometry_version`` format, the
``paths``/node-id correspondence and the server ``limits.*``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import (
    MANIFEST_INVALID,
    MANIFEST_TOO_LARGE,
    NODE_DEGREE_LIMIT,
    NODES_LIMIT,
    PipelineError,
    PipelineFailure,
)
from .graph import _TYPE_ENDS
from .models import MIN_NODE_ID

_HEX64 = r"^[0-9a-f]{64}$"
_KEY_RE = r"^[a-z0-9_]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Georef(_Strict):
    projection: Literal["gall_stereographic"]
    x0: float
    k: float
    y0: float
    m: float


class InputsSha256(_Strict):
    source: str = Field(pattern=_HEX64)
    boundary: str = Field(pattern=_HEX64)
    overrides: str = Field(pattern=_HEX64)
    ids_lock: str = Field(pattern=_HEX64)


class ManifestNode(_Strict):
    id: int = Field(ge=MIN_NODE_ID)
    key: str = Field(pattern=_KEY_RE)
    kind: Literal["LAND", "SEA"]
    name: str | None
    name_ru: str | None
    source_name: str | None
    anchor: list[float] = Field(min_length=2, max_length=2)
    bbox: list[float] = Field(min_length=4, max_length=4)
    area: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _kinds(self):
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
    a: int = Field(ge=MIN_NODE_ID)
    b: int = Field(ge=MIN_NODE_ID)
    type: Literal["land", "coast", "sea", "strait"]
    len: float | None = None
    name: str | None = None
    multiplier: float | None = None

    @model_validator(mode="after")
    def _payload(self):
        if self.type == "strait":
            if not self.name:
                raise ValueError("strait edge needs a name")
            if self.len is not None:
                raise ValueError("strait edge must not carry len")
        else:
            if self.name is not None or self.multiplier is not None:
                raise ValueError(
                    f"{self.type} edge must not carry name/multiplier"
                )
        return self


class Manifest(_Strict):
    schema_version: Literal[1]
    geometry_version: str = Field(pattern=r"^[0-9a-f]{12}$")
    borders_version: str = Field(pattern=r"^[0-9a-f]{12}$")
    view_box: list[float] = Field(min_length=4, max_length=4)
    playable_bbox: list[float] = Field(min_length=4, max_length=4)
    georef: Georef
    inputs_sha256: InputsSha256
    nodes: list[ManifestNode]
    edges: list[ManifestEdge]

    @field_validator("nodes")
    @classmethod
    def _sorted_unique_nodes(cls, nodes):
        ids = [n.id for n in nodes]
        if ids != sorted(ids):
            raise ValueError("nodes must be sorted by id")
        if len(set(ids)) != len(ids):
            raise ValueError("node ids must be unique (INV-M1)")
        keys = [n.key for n in nodes]
        if len(set(keys)) != len(keys):
            raise ValueError("node keys must be unique")
        return nodes


def _components(node_ids: list[int], pairs: list[tuple[int, int]]) -> int:
    parent = {i: i for i in node_ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return len({find(i) for i in node_ids})


def validate_manifest(
    doc: dict,
    paths_keys: set[str],
    manifest_bytes: int,
    cfg,
) -> Manifest:
    """Validate the manifest document; raise on any violation.

    Limit breaches carry their own codes (``NODES_LIMIT``,
    ``NODE_DEGREE_LIMIT``, ``MANIFEST_TOO_LARGE``); every other defect is
    ``MANIFEST_INVALID``. Returns the parsed model.
    """
    try:
        m = Manifest.model_validate(doc)
    except ValidationError as exc:
        details = [
            f"{'->'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
        raise PipelineError(
            MANIFEST_INVALID, "manifest failed schema validation", details
        )

    errors: list[PipelineError] = []

    if len(m.nodes) > cfg.limits.max_nodes:
        errors.append(
            PipelineError(
                NODES_LIMIT,
                f"{len(m.nodes)} nodes exceed limits.max_nodes "
                f"{cfg.limits.max_nodes}",
            )
        )

    by_id = {n.id: n for n in m.nodes}
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    degree: dict[int, int] = {n.id: 0 for n in m.nodes}
    for i, e in enumerate(m.edges):
        problems = []
        if not e.a < e.b:
            problems.append("a >= b")
        pair = (e.a, e.b)
        if pair in seen:
            problems.append("duplicate pair")
        seen.add(pair)
        na, nb = by_id.get(e.a), by_id.get(e.b)
        if na is None or nb is None:
            problems.append("endpoint does not exist")
        elif tuple(sorted((na.kind, nb.kind))) != _TYPE_ENDS[e.type]:
            problems.append(
                f"type {e.type!r} joins {na.kind} and {nb.kind}"
            )
        if problems:
            errors.append(
                PipelineError(
                    MANIFEST_INVALID,
                    f"edges[{i}] ({e.a}, {e.b}) violates INV-M2: "
                    + "; ".join(problems),
                )
            )
            continue
        pairs.append(pair)
        degree[e.a] += 1
        degree[e.b] += 1

    if pairs != sorted(pairs):
        errors.append(
            PipelineError(
                MANIFEST_INVALID, "edges are not sorted by (a, b)"
            )
        )

    offenders = sorted(
        (i for i, d in degree.items() if d > cfg.limits.max_edges_per_node),
    )
    if offenders:
        errors.append(
            PipelineError(
                NODE_DEGREE_LIMIT,
                f"degree above limits.max_edges_per_node "
                f"{cfg.limits.max_edges_per_node}: "
                + ", ".join(
                    f"{by_id[i].key} ({degree[i]})" for i in offenders
                ),
            )
        )

    if manifest_bytes > cfg.limits.max_manifest_bytes:
        errors.append(
            PipelineError(
                MANIFEST_TOO_LARGE,
                f"manifest.json is {manifest_bytes} bytes, over "
                f"limits.max_manifest_bytes {cfg.limits.max_manifest_bytes}",
            )
        )

    if {str(n.id) for n in m.nodes} != set(paths_keys):
        missing = sorted(set(str(n.id) for n in m.nodes) - paths_keys)
        extra = sorted(paths_keys - {str(n.id) for n in m.nodes})
        errors.append(
            PipelineError(
                MANIFEST_INVALID,
                "geometry paths and manifest node ids differ",
                ([f"missing paths: {missing}"] if missing else [])
                + ([f"extra paths: {extra}"] if extra else []),
            )
        )

    if errors:
        raise PipelineFailure(errors)

    if _components(sorted(by_id), pairs) != 1:
        errors.append(
            PipelineError(
                MANIFEST_INVALID,
                "INV-M3 violation: the manifest graph is not connected",
            )
        )
        raise PipelineFailure(errors)
    return m
