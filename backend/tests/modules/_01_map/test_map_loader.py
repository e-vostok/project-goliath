"""
Loader tests for module 01_map (Issue 2): the mini fixture under
``tests/fixtures/map_mini/`` is copied into ``tmp_path`` and each negative
test breaks exactly one thing, asserting the stable ``MapDataError.code``.

No mocks: real files, real hashing, the real ``configs/01_map.yaml``
(limits lowered through a ``model_copy`` when a test needs them).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from modules._01_map.config_schema import FrameConfig, MapConfig
from modules._01_map.loader import (
    FILE_MISSING,
    INV_M1,
    INV_M2,
    INV_M3,
    INV_M6,
    INV_M10,
    LIMIT_EXCEEDED,
    SCHEMA_INVALID,
    MapDataError,
    load_map_data,
)

from .conftest import (
    fix_geometry_pin,
    fix_input_hashes,
    load_geometry,
    load_lock,
    load_manifest,
    map_config,
    save_geometry,
    save_lock,
    save_manifest,
)


def _expect(data_dir: Path, code: str, config: MapConfig | None = None):
    with pytest.raises(MapDataError) as exc_info:
        load_map_data(data_dir, config or map_config())
    assert exc_info.value.code == code
    return exc_info.value


def _mutate_manifest(data_dir: Path, mutator) -> None:
    doc = load_manifest(data_dir)
    mutator(doc)
    save_manifest(data_dir, doc)


def _mutate_geometry(data_dir: Path, mutator) -> None:
    doc = load_geometry(data_dir)
    mutator(doc)
    save_geometry(data_dir, doc)


def _mutate_lock(data_dir: Path, mutator) -> None:
    doc = load_lock(data_dir)
    mutator(doc)
    save_lock(data_dir, doc)


# ------------------------------------------------------------- positive


def test_mini_map_loads(mini_dir, config):
    data = load_map_data(mini_dir, config)

    assert len(data.nodes) == 10
    assert len(data.edges) == 10
    assert list(data.nodes) == sorted(data.nodes)  # ascending id order
    assert data.warnings == ()
    assert data.geometry_version == data.geometry.version
    assert len(data.manifest_sha256) == 64
    # validated file models are kept for Issue 4 DTOs
    assert len(data.manifest.nodes) == 10
    assert set(data.geometry.paths) == {str(n.id) for n in data.nodes.values()}
    # adjacency is sorted by the neighbour id
    assert [e.b if e.a == 2001 else e.a for e in data.adjacency[2001]] == [
        1004,
        1008,
        2002,
    ]


def test_lock_extra_entries_become_warnings(mini_dir, config):
    """Append-only lock may list keys the manifest dropped (INV-M1)."""
    _mutate_lock(mini_dir, lambda d: d["ids"].update({"retired": 3001}))
    fix_input_hashes(mini_dir)

    data = load_map_data(mini_dir, config)

    assert data.warnings == (
        "ids.lock.json entry 'retired' (id 3001) has no manifest node",
    )


# --------------------------------------------------------- FILE_MISSING


@pytest.mark.parametrize(
    "missing",
    [
        "manifest.json",
        "geometry.json",
        "ids.lock.json",
        "boundary.yaml",
        "overrides.yaml",
        "source/map.svg",
    ],
)
def test_missing_file(mini_dir, missing):
    (mini_dir / missing).unlink()
    err = _expect(mini_dir, FILE_MISSING)
    assert missing in err.message


# ------------------------------------------------------- LIMIT_EXCEEDED


def test_oversized_manifest_is_not_parsed(mini_dir):
    """Size precedes parsing: a corrupt AND oversized manifest still
    reports LIMIT_EXCEEDED, not SCHEMA_INVALID."""
    (mini_dir / "manifest.json").write_bytes(b"{ not json " + b"x" * 20000)
    _expect(mini_dir, LIMIT_EXCEEDED, map_config(max_manifest_bytes=1000))


def test_oversized_geometry_is_not_parsed(mini_dir):
    (mini_dir / "geometry.json").write_bytes(b"{ not json " + b"x" * 20000)
    _expect(mini_dir, LIMIT_EXCEEDED, map_config(max_geometry_bytes=1000))


def test_max_nodes_limit(mini_dir):
    err = _expect(mini_dir, LIMIT_EXCEEDED, map_config(max_nodes=9))
    assert "max_nodes" in err.message


def test_max_edges_per_node_limit(mini_dir):
    # sea_mini_north (2001) and sea_mini_south (2002) have degree 3.
    err = _expect(mini_dir, LIMIT_EXCEEDED, map_config(max_edges_per_node=2))
    assert "max_edges_per_node" in err.message


# -------------------------------------------------------- SCHEMA_INVALID


def test_wrong_schema_version(mini_dir):
    _mutate_manifest(mini_dir, lambda d: d.update(schema_version=2))
    _expect(mini_dir, SCHEMA_INVALID)


def test_unknown_extra_key(mini_dir):
    _mutate_manifest(mini_dir, lambda d: d.update(bogus=1))
    _expect(mini_dir, SCHEMA_INVALID)


def test_malformed_manifest_json(mini_dir):
    (mini_dir / "manifest.json").write_text("{ not json", encoding="utf-8")
    _expect(mini_dir, SCHEMA_INVALID)


def test_malformed_lock_json(mini_dir):
    (mini_dir / "ids.lock.json").write_text("[1, 2", encoding="utf-8")
    _expect(mini_dir, SCHEMA_INVALID)


def test_wrong_lock_version(mini_dir):
    _mutate_lock(mini_dir, lambda d: d.update(version=2))
    _expect(mini_dir, SCHEMA_INVALID)


def test_frame_outside_view_box_rejected(mini_dir):
    """Cross-rule (Spec 1.9): ``view.frame`` must lie entirely inside
    ``manifest.view_box`` — a config copy with the real map's frame
    (519.1 × 221.3 over a 100 × 80 view_box) must fail startup."""
    base = map_config()
    config = base.model_copy(
        update={
            "view": base.view.model_copy(
                update={
                    "frame": FrameConfig(
                        x=519.1, y=20.9, width=221.3, height=217.3
                    )
                }
            )
        }
    )

    err = _expect(mini_dir, SCHEMA_INVALID, config)

    # The message must print both rectangles.
    assert "view.frame" in str(err)
    assert "view_box" in str(err)
    assert "519.1" in str(err)


def test_bad_node_key_charset(mini_dir):
    _mutate_manifest(
        mini_dir, lambda d: d["nodes"][0].update(key="Bad-Key")
    )
    _expect(mini_dir, SCHEMA_INVALID)


def test_bad_path_characters(mini_dir):
    _mutate_geometry(
        mini_dir,
        lambda d: d["paths"].update({"1001": "M 0 0 <script>alert()</script>"}),
    )
    _expect(mini_dir, SCHEMA_INVALID)


def test_non_numeric_path_key(mini_dir):
    _mutate_geometry(
        mini_dir, lambda d: d["paths"].update({"abc": "M 0 0 Z"})
    )
    _expect(mini_dir, SCHEMA_INVALID)


def test_sea_node_with_source_name(mini_dir):
    def mut(d):
        for n in d["nodes"]:
            if n["kind"] == "SEA":
                n["source_name"] = "Sea_Mini_North"
                return

    _mutate_manifest(mini_dir, mut)
    _expect(mini_dir, SCHEMA_INVALID)


def test_nan_in_anchor_rejected(mini_dir):
    _mutate_manifest(
        mini_dir, lambda d: d["nodes"][0].update(anchor=[float("nan"), 5.0])
    )
    _expect(mini_dir, SCHEMA_INVALID)


# ---------------------------------------------------------------- INV-M1


def test_inv_m1_key_missing_in_lock(mini_dir):
    _mutate_lock(mini_dir, lambda d: d["ids"].pop("mini_beta"))
    err = _expect(mini_dir, INV_M1)
    assert "mini_beta" in err.message


def test_inv_m1_id_mismatch(mini_dir):
    _mutate_lock(mini_dir, lambda d: d["ids"].update({"mini_beta": 1999}))
    err = _expect(mini_dir, INV_M1)
    assert "1999" in err.message


def test_inv_m1_duplicate_key_in_manifest(mini_dir):
    _mutate_manifest(
        mini_dir, lambda d: d["nodes"].append(dict(d["nodes"][1]))
    )
    _expect(mini_dir, INV_M1)


def test_inv_m1_duplicate_id_in_manifest(mini_dir):
    def mut(d):
        dup = dict(d["nodes"][1])
        dup["key"] = "mini_beta_copy"
        d["nodes"].append(dup)

    _mutate_manifest(mini_dir, mut)
    _expect(mini_dir, INV_M1)


def test_inv_m1_duplicate_id_in_lock(mini_dir):
    _mutate_lock(
        mini_dir, lambda d: d["ids"].update({"extra_zone": 1002})
    )
    _expect(mini_dir, INV_M1)


def test_inv_m1_sea_key_without_prefix(mini_dir):
    def mut(d):
        for n in d["nodes"]:
            if n["kind"] == "SEA":
                n["key"] = "mini_north"
                return

    _mutate_manifest(mini_dir, mut)
    _mutate_lock(
        mini_dir,
        lambda d: d["ids"].update(
            {"mini_north": d["ids"].pop("sea_mini_north")}
        ),
    )
    _expect(mini_dir, INV_M1)


def test_inv_m1_land_key_with_sea_prefix(mini_dir):
    def mut(d):
        for n in d["nodes"]:
            if n["key"] == "mini_beta":
                n["key"] = "sea_beta"
                return

    _mutate_manifest(mini_dir, mut)
    _mutate_lock(
        mini_dir,
        lambda d: d["ids"].update(
            {"sea_beta": d["ids"].pop("mini_beta")}
        ),
    )
    _expect(mini_dir, INV_M1)


# ---------------------------------------------------------------- INV-M2


def _edge(doc, a, b):
    return next(
        e for e in doc["edges"] if e["a"] == a and e["b"] == b
    )


def test_inv_m2_edge_a_greater_than_b(mini_dir):
    def mut(d):
        e = _edge(d, 1001, 1002)
        e["a"], e["b"] = e["b"], e["a"]

    _mutate_manifest(mini_dir, mut)
    _expect(mini_dir, INV_M2)


def test_inv_m2_duplicated_pair(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: d["edges"].append(dict(_edge(d, 1001, 1002))),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_duplicated_pair_reversed(mini_dir):
    """The same pair as (a,b) and (b,a): a>b also fires — same code."""
    def mut(d):
        e = dict(_edge(d, 1001, 1002))
        e["a"], e["b"] = e["b"], e["a"]
        d["edges"].append(e)

    _mutate_manifest(mini_dir, mut)
    _expect(mini_dir, INV_M2)


def test_inv_m2_unknown_endpoint(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: d["edges"].append(
            {"a": 1001, "b": 1999, "type": "land", "len": 1.0}
        ),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_loop(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: d["edges"].append(
            {"a": 1001, "b": 1001, "type": "land", "len": 1.0}
        ),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_coast_between_two_land(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: d["edges"].append(
            {"a": 1002, "b": 1004, "type": "coast", "len": 1.0}
        ),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_sea_between_land_and_sea(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: d["edges"].append(
            {"a": 1003, "b": 2001, "type": "sea", "len": 1.0}
        ),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_multiplier_on_non_strait(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: _edge(d, 1001, 1002).update(multiplier=0.5),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_multiplier_out_of_range(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: _edge(d, 1006, 1007).update(multiplier=1.5),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_name_on_non_strait(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: _edge(d, 1001, 1002).update(name="sneaky"),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_strait_carries_len(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: _edge(d, 1005, 1006).update(len=1.0),
    )
    _expect(mini_dir, INV_M2)


def test_inv_m2_strait_without_name(mini_dir):
    _mutate_manifest(
        mini_dir,
        lambda d: _edge(d, 1005, 1006).update(name=None),
    )
    _expect(mini_dir, INV_M2)


# ---------------------------------------------------------------- INV-M3


def test_inv_m3_orphan_node(mini_dir):
    def mut(d):
        d["nodes"].append(
            {
                "id": 1009,
                "key": "mini_iota",
                "kind": "LAND",
                "name": "Mini Iota",
                "name_ru": None,
                "source_name": "Mini_Iota",
                "anchor": [90.0, 70.0],
                "bbox": [85.0, 65.0, 95.0, 75.0],
                "area": 100.0,
            }
        )

    _mutate_manifest(mini_dir, mut)
    _mutate_lock(mini_dir, lambda d: d["ids"].update({"mini_iota": 1009}))
    err = _expect(mini_dir, INV_M3)
    assert "1009" in err.message


# ---------------------------------------------------------------- INV-M6


def test_inv_m6_geometry_changed_without_version_bump(mini_dir):
    def mut(d):
        d["paths"]["1001"] = d["paths"]["1001"].replace("0 20", "0 21", 1)

    _mutate_geometry(mini_dir, mut)
    _expect(mini_dir, INV_M6)


def test_inv_m6_paths_missing_node(mini_dir):
    _mutate_geometry(mini_dir, lambda d: d["paths"].pop("1008"))
    fix_geometry_pin(mini_dir)  # versions stay consistent -> set check fires
    _expect(mini_dir, INV_M6)


def test_inv_m6_extra_path(mini_dir):
    _mutate_geometry(
        mini_dir,
        lambda d: d["paths"].update({"9999": "M 0 0 L 1 0 L 1 1 Z"}),
    )
    fix_geometry_pin(mini_dir)
    _expect(mini_dir, INV_M6)


def test_inv_m6_manifest_version_tampered(mini_dir):
    _mutate_manifest(
        mini_dir, lambda d: d.update(geometry_version="000000000000")
    )
    _expect(mini_dir, INV_M6)


# --------------------------------------------------------------- INV-M10


@pytest.mark.parametrize(
    "input_file,appendix",
    [
        ("boundary.yaml", b"\n# x\n"),
        ("overrides.yaml", b"\n# x\n"),
        # trailing whitespace keeps the JSON valid, only the hash changes
        ("ids.lock.json", b"\n"),
    ],
)
def test_inv_m10_input_changed(mini_dir, input_file, appendix):
    path = mini_dir / input_file
    path.write_bytes(path.read_bytes() + appendix)
    err = _expect(mini_dir, INV_M10)
    assert "re-run the map pipeline" in err.message


def test_inv_m10_source_changed(mini_dir):
    path = mini_dir / "source" / "map.svg"
    path.write_bytes(path.read_bytes() + b"<!--x-->")
    _expect(mini_dir, INV_M10)


# ------------------------------------------------------------------ CRLF


def _to_crlf(path: Path) -> None:
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))


def test_crlf_text_inputs_still_load(mini_dir, config):
    """Windows checkout (core.autocrlf): CRLF in the three TEXT inputs
    must not break INV-M10 — they are hashed CRLF -> LF."""
    for name in ("boundary.yaml", "overrides.yaml", "ids.lock.json"):
        _to_crlf(mini_dir / name)
    data = load_map_data(mini_dir, config)
    assert len(data.nodes) == 10


def test_crlf_source_fails_inv_m10(mini_dir):
    """``source/map.svg`` is hashed raw (``-text`` in .gitattributes —
    its CRLFs are part of the checksum), so converting it to CRLF is a
    real input change and must fail."""
    _to_crlf(mini_dir / "source" / "map.svg")
    _expect(mini_dir, INV_M10)


# ----------------------------------------------------------- immutability


def test_map_data_is_immutable(mini_dir, config):
    data = load_map_data(mini_dir, config)

    with pytest.raises(dataclasses.FrozenInstanceError):
        data.nodes[1001].id = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.geometry_version = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        data.nodes[1001] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        data.nodes_by_key["x"] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        data.edges[(1001, 1002)] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        data.adjacency[1001] = ()  # type: ignore[index]
    with pytest.raises(AttributeError):
        data.adjacency[1001].append(None)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        data.manifest.nodes.append(None)  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        data.geometry.paths["1001"] = "x"  # type: ignore[index]
    with pytest.raises(ValidationError):
        data.manifest.nodes[0].id = 5  # type: ignore[attr-defined]
