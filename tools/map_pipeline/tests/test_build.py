"""Appendix A steps 7-10: geometry.json, manifest.json, preview, --check.

Small real fixtures through the full ``build`` command — no mocks.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest
import yaml
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from conftest import base_overrides, graph_overrides, run_build, square
from tools.map_pipeline.pipeline_config_schema import load_pipeline_config
from tools.map_pipeline.svgpath import (
    _signed_area,
    canonical_json,
    dumps,
    geometry_version,
    parse_path,
)

CFG = load_pipeline_config()
GRID = CFG.output.grid
BOUND = CFG.simplify.tolerance + GRID


def _ring(prefix, hx, hy, cell=8):
    return [
        square(f"{prefix}{i}{j}", hx - cell + i * cell, hy - cell + j * cell,
               cell)
        for i in (0, 1, 2)
        for j in (0, 1, 2)
        if (i, j) != (1, 1)
    ]


def _ring_keys(prefix):
    return [f"{prefix}{i}{j}" for i in (0, 1, 2) for j in (0, 1, 2)
            if (i, j) != (1, 1)]


def _two_lands(**ov):
    """Two land squares flanking a strait, plus an enclosed pond ring.

    ``sea_margin=30`` merges all band water into one component so a single
    seed reaches it; the ring's pond stays enclosed and becomes a lake.
    """
    elems = (
        [square("Alpha", 10, 10, 12), square("Beta", 30, 10, 12)]
        + _ring("W", 60, 30, cell=6)
    )
    return dict(
        svg_elems=elems,
        include=["Alpha", "Beta"] + _ring_keys("W"),
        overrides=base_overrides(
            sea_margin=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[24.0, 16.0]]}],
        ),
        **ov,
    )


def _geom_doc(data_dir):
    return json.loads(
        (data_dir / "geometry.json").read_text(encoding="utf-8")
    )


def _manifest(data_dir):
    return json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )


def _node_paths(geom, mani):
    return {n["key"]: parse_path(geom["paths"][str(n["id"])])
            for n in mani["nodes"]}


# ------------------------------------------------------------ path format


def test_path_format_roundtrip():
    poly = Polygon(
        [(10.0, 10.0), (20.5, 10.0), (20.5, 20.0), (10.0, 20.0)],
        [[(12.0, 12.0), (12.0, 13.25), (13.25, 13.25), (13.25, 12.0)]],
    )
    small = Polygon([(30.0, 30.0), (30.01, 30.0), (30.0, 30.01)])
    multi = MultiPolygon([poly, small])
    d = dumps(multi)

    parts = parse_path(d)
    assert len(parts) == 2
    assert abs(unary_union(parts).area - multi.area) < 1e-6

    # formatting rules: no trailing zeros, no -0, no sci-notation,
    # single spaces, closing vertex not repeated
    assert "  " not in d
    assert not re.search(r"\d\.\d*0[ Z]", d)
    assert "-0" not in d
    assert not re.search(r"[eE][+-]?\d", d)
    assert re.fullmatch(r"(M (\d+(\.\d+)? \d+(\.\d+)? )+Z)+", d)

    # orientation: exterior CCW (positive signed area), holes CW
    for m in re.finditer(r"M ([^Z]+) Z", d):
        nums = m.group(1).split()
        it = iter(nums)
        ring = [(float(x), float(y)) for x, y in zip(it, it)]
        assert ring[0] != ring[-1]  # no repeated closing vertex

    big = max(parts, key=lambda p: p.area)
    assert len(big.interiors) == 1


def test_parse_path_rejects_junk():
    with pytest.raises(ValueError):
        parse_path("M 0 0 1 0 1 1 Z garbage")
    with pytest.raises(ValueError):
        parse_path("M 0 0 1 0 Z")  # too few pairs
    with pytest.raises(ValueError):
        parse_path("L 0 0 1 1")


# ------------------------------------------------------------ land


def test_build_two_lands_and_sea(make_data_dir, tmp_path):
    data_dir = make_data_dir(**_two_lands())
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0

    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    kinds = {n["key"]: n["kind"] for n in mani["nodes"]}
    assert kinds["alpha"] == "LAND"
    assert kinds["beta"] == "LAND"
    assert kinds["sea_a"] == "SEA"
    assert set(geom["paths"]) == {str(n["id"]) for n in mani["nodes"]}
    assert geom["version"] == mani["geometry_version"]

    # anchors inside their own polygons
    paths = _node_paths(geom, mani)
    for n in mani["nodes"]:
        g = unary_union(paths[n["key"]])
        assert g.covers(Point(*n["anchor"])), n["key"]

    # land and sea do not overlap measurably
    land = unary_union(
        [p for n in mani["nodes"] if n["kind"] == "LAND"
         for p in paths[n["key"]]]
    )
    sea = unary_union(paths["sea_a"])
    assert land.intersection(sea).area < 0.01

    # outside exists and does not cover the land
    outside = unary_union(parse_path(geom["outside"]))
    assert outside.area > 0
    assert outside.intersection(land).area < 0.05 * land.area


def test_land_deviation_and_simplification(make_data_dir, tmp_path):
    """A noisy-border square: valid, fewer vertices, bounded deviation."""
    pts = ["M 10 10"]
    x, y = 10.0, 10.0
    import math

    # noisy top edge: small zigzags
    for i in range(1, 21):
        pts.append(f"L {10 + i * 0.5:.2f} {10 + (0.04 if i % 2 else 0):.2f}")
    pts += ["L 20 20", "L 10 20", "Z"]
    elems = [f'<path id="Alpha" d="{" ".join(pts)}"/>',
             square("Beta", 30, 10, 12)]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[21.5, 15.0], [44.0, 15.0]]}]
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0

    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    alpha = next(n for n in mani["nodes"] if n["key"] == "alpha")
    parts = parse_path(geom["paths"][str(alpha["id"])])
    g = unary_union(parts)
    assert g.is_valid
    orig = Polygon(
        [(10, 10)] + [(10 + i * 0.5, 10 + (0.04 if i % 2 else 0))
                      for i in range(1, 21)] + [(20, 20), (10, 20)]
    )
    dev = orig.hausdorff_distance(g)
    assert dev <= BOUND + 1e-9
    total_v = sum(len(p.exterior.coords) for p in parts)
    assert total_v < len(orig.exterior.coords)
    assert abs(g.area - orig.area) < 0.5


def test_land_collapse_is_empty_error(make_data_dir, tmp_path, capsys):
    """A sub-grid province collapses under snapping -> GEOMETRY_EMPTY."""
    elems = [
        '<path id="Tiny" d="M 10 10 l 0.004 0 l 0 0.004 l -0.004 0 z"/>',
        square("Beta", 30, 10, 12),
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Tiny", "Beta"],
        overrides=graph_overrides(
            edges_add=[{"a": "tiny", "b": "beta", "type": "land"}],
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[28.5, 15.0], [44.0, 15.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "GEOMETRY_EMPTY" in err


def test_neighbour_slivers_do_not_raise(make_data_dir, tmp_path):
    """Overlapping-source neighbours still build (Spec 1.4)."""
    elems = [
        '<path id="Alpha" d="M 10 10 L 20 10 L 20.05 20 L 10 20 Z"/>',
        '<path id="Beta" d="M 20 10 L 30 10 L 30 20 L 19.98 20 Z"/>',
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[8.5, 15.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0


# ------------------------------------------------------------ sea coverage


def test_sea_shared_border_and_no_gap(make_data_dir, tmp_path):
    """Two zones sharing a staircase border: identical shared edge,
    no overlap, no gap after the land cut."""
    elems = [square("Alpha", 10, 10, 10)]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"],
        overrides=graph_overrides(
            sea_margin=8.0,
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[16.0, 5.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[22.0, 5.0]]},
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0

    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    za = unary_union(paths["sea_a"])
    zb = unary_union(paths["sea_b"])
    assert za.intersection(zb).area < 1e-6

    # the two zones together leave no internal gap where they touch
    union_ab = unary_union([za, zb])
    gap = union_ab.area - za.area - zb.area
    assert abs(gap) < 1e-6

    # shared boundary is nontrivial
    shared = za.boundary.intersection(zb.boundary)
    assert shared.length > 0.5


def test_sea_land_seam(make_data_dir, tmp_path):
    """Zone next to land: no measurable overlap or visible seam."""
    elems = [square("Alpha", 10, 10, 10)]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[22.0, 15.0]]}]
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    land = unary_union(paths["alpha"])
    sea = unary_union(paths["sea_a"])
    assert land.intersection(sea).area < 0.01


def test_excluded_land_blocks_zone(make_data_dir, tmp_path):
    """A source province excluded from the game still masks the zone."""
    elems = [
        square("Alpha", 10, 10, 8),
        square("Ghost", 26, 10, 8),   # excluded: not in include
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"],
        overrides=graph_overrides(
            sea_margin=12.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[20.0, 14.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    sea = unary_union(paths["sea_a"])
    ghost = box(26, 10, 34, 18)
    assert sea.intersection(ghost).area < 0.5


# ------------------------------------------------------------ metrics


def test_anchor_cshape(make_data_dir, tmp_path):
    """C-shaped province: anchor inside (a centroid would be outside)."""
    elems = [
        '<path id="Alpha" d="M 10 10 L 30 10 L 30 14 L 14 14 L 14 26 '
        'L 30 26 L 30 30 L 10 30 Z"/>',
        square("Beta", 40, 10, 10),
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[15.5, 20.0], [51.5, 15.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    mani = _manifest(data_dir)
    geom = _geom_doc(data_dir)
    paths = _node_paths(geom, mani)
    alpha = next(n for n in mani["nodes"] if n["key"] == "alpha")
    g = unary_union(paths["alpha"])
    assert g.covers(Point(*alpha["anchor"]))


def test_anchor_multipart_in_largest(make_data_dir, tmp_path):
    elems = [
        '<path id="Alpha" d="M 10 10 h 20 v 20 h -20 z '
        'M 50 10 h 2 v 2 h -2 z"/>',
        square("Beta", 40, 40, 10),
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[31.5, 15.0], [51.5, 45.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    mani = _manifest(data_dir)
    geom = _geom_doc(data_dir)
    parts = parse_path(
        geom["paths"][str(next(n["id"] for n in mani["nodes"]
                              if n["key"] == "alpha"))]
    )
    alpha = next(n for n in mani["nodes"] if n["key"] == "alpha")
    largest = max(parts, key=lambda p: p.area)
    assert largest.covers(Point(*alpha["anchor"]))


def test_bbox_and_area(make_data_dir, tmp_path):
    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    mani = _manifest(data_dir)
    geom = _geom_doc(data_dir)
    paths = _node_paths(geom, mani)
    for n in mani["nodes"]:
        g = unary_union(paths[n["key"]])
        x0, y0, x1, y1 = n["bbox"]
        gx0, gy0, gx1, gy1 = g.bounds
        assert x0 <= gx0 + 1e-9 and y0 <= gy0 + 1e-9
        assert x1 >= gx1 - 1e-9 and y1 >= gy1 - 1e-9
        assert abs(n["area"] - round(g.area, 2)) < 0.011


# ------------------------------------------------------------ outside


def test_outside_lakes_and_invariants(make_data_dir, tmp_path):
    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    outside_parts = parse_path(geom["outside"])
    outside = unary_union(outside_parts)
    assert outside.is_valid

    # the pond inside the ring is a lake window (hole or notch of outside)
    pond = Point(62.0, 32.0)   # centre of the ring hole
    assert not outside.covers(pond)

    # outside never pokes deeper than 0.2 into the closed node union
    allparts = [p for n in mani["nodes"] for p in paths[n["key"]]]
    n_union = unary_union(allparts).buffer(
        CFG.outside.closing).buffer(-CFG.outside.closing)
    deep = n_union.buffer(-0.2)
    assert outside.intersection(deep).area < 1e-6


# -------------------------------------------- version, hashes, manifest


def test_version_and_input_hashes(make_data_dir, tmp_path):
    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)

    g = {
        "outside": geom["outside"],
        "paths": geom["paths"],
        "sea_water": geom["sea_water"],
    }
    assert geometry_version(g) == geom["version"]
    assert mani["geometry_version"] == geom["version"]

    src = data_dir / "source" / "map.svg"
    assert mani["inputs_sha256"]["source"] == hashlib.sha256(
        src.read_bytes()).hexdigest()

    # flipping one input byte must change the matching hash -> --check exits 1
    ov = data_dir / "overrides.yaml"
    text = ov.read_text(encoding="utf-8")
    ov.write_text(text + "\n# x\n", encoding="utf-8")
    assert run_build(data_dir, tmp_path / "out2", check=True) == 1


def test_manifest_schema_invariants(make_data_dir, tmp_path):
    from tools.map_pipeline.manifest_schema import validate_manifest
    from tools.map_pipeline.errors import (
        MANIFEST_INVALID, NODE_DEGREE_LIMIT, NODES_LIMIT,
        MANIFEST_TOO_LARGE,
    )

    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    mani = _manifest(data_dir)
    geom = _geom_doc(data_dir)
    paths_keys = set(geom["paths"])
    size = len(
        (data_dir / "manifest.json").read_bytes())

    # a valid manifest passes
    m = validate_manifest(mani, paths_keys, size, CFG)
    assert len(m.nodes) == len(mani["nodes"])

    def fails(mutator, code):
        import copy
        doc = copy.deepcopy(mani)
        mutator(doc)
        with pytest.raises(Exception) as ei:
            validate_manifest(doc, paths_keys, size, CFG)
        err = ei.value
        codes = [e.code for e in getattr(err, "errors", [err])]
        assert code in codes, (code, codes)

    fails(lambda d: d["nodes"][0].update(bogus=1), MANIFEST_INVALID)
    fails(lambda d: d["edges"].reverse(), MANIFEST_INVALID)
    fails(lambda d: d["edges"][0].update(a=d["edges"][0]["b"],
                                         b=d["edges"][0]["a"]),
          MANIFEST_INVALID)
    fails(lambda d: d["edges"].append(dict(d["edges"][0])),
          MANIFEST_INVALID)
    fails(lambda d: d.pop("nodes"), MANIFEST_INVALID)
    fails(lambda d: d.update(geometry_version="zzzzzzzzzzzz"),
          MANIFEST_INVALID)


def test_manifest_limits(make_data_dir, tmp_path):
    import copy
    from tools.map_pipeline.manifest_schema import validate_manifest
    from tools.map_pipeline.errors import (
        MANIFEST_TOO_LARGE, NODE_DEGREE_LIMIT, NODES_LIMIT,
    )

    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    mani = _manifest(data_dir)
    geom = _geom_doc(data_dir)
    paths_keys = set(geom["paths"])
    size = len((data_dir / "manifest.json").read_bytes())

    class FakeLimits:
        pass

    cfg = copy.deepcopy(CFG)

    cfg.limits.max_nodes = 5
    with pytest.raises(Exception) as ei:
        validate_manifest(mani, paths_keys, size, cfg)
    codes = [e.code for e in ei.value.errors]
    assert NODES_LIMIT in codes
    cfg.limits.max_nodes = 3000

    cfg.limits.max_edges_per_node = 1
    with pytest.raises(Exception) as ei:
        validate_manifest(mani, paths_keys, size, cfg)
    assert NODE_DEGREE_LIMIT in [e.code for e in ei.value.errors]
    cfg.limits.max_edges_per_node = 60

    cfg.limits.max_manifest_bytes = size - 1
    with pytest.raises(Exception) as ei:
        validate_manifest(mani, paths_keys, size, cfg)
    assert MANIFEST_TOO_LARGE in [e.code for e in ei.value.errors]


def test_viewbox_mismatch(make_data_dir, tmp_path, capsys):
    """Source viewBox != view config -> VIEWBOX_MISMATCH."""
    data_dir = make_data_dir(**_two_lands())
    svg = data_dir / "source" / "map.svg"
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            'viewBox="0 0 1200 680"', 'viewBox="0 0 999 680"'
        ),
        encoding="utf-8",
    )
    assert run_build(data_dir, tmp_path / "out") == 1
    assert "VIEWBOX_MISMATCH" in capsys.readouterr().err


# ------------------------------------------------ determinism & --check


def test_determinism_and_check(make_data_dir, tmp_path):
    data_dir = make_data_dir(**_two_lands())
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir, preview=True,
                     crops=["bay=15,8,30,25"]) == 0

    finals = {
        name: (data_dir / name).read_bytes()
        for name in ("manifest.json", "geometry.json", "ids.lock.json")
    }
    report_b = (out_dir / "build_report.md").read_bytes()
    pngs = {
        p.name: p.read_bytes()
        for p in (data_dir / "preview").iterdir()
    }
    assert "map_preview.png" in pngs
    assert "map_crop_bay.png" in pngs

    # --check writes nothing and passes
    assert run_build(data_dir, out_dir, check=True) == 0
    for name, blob in finals.items():
        assert (data_dir / name).read_bytes() == blob

    # second full build is byte-identical, previews included
    out_dir2 = tmp_path / "out2"
    assert run_build(data_dir, out_dir2, preview=True,
                     crops=["bay=15,8,30,25"]) == 0
    for name, blob in finals.items():
        assert (data_dir / name).read_bytes() == blob
    assert (out_dir2 / "build_report.md").read_bytes() == report_b
    for name, blob in pngs.items():
        assert (data_dir / "preview" / name).read_bytes() == blob


def test_failing_build_writes_nothing(make_data_dir, tmp_path):
    """A bad input must leave the final files untouched."""
    data_dir = make_data_dir(**_two_lands())
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0
    before = {
        name: (data_dir / name).read_bytes()
        for name in ("manifest.json", "geometry.json", "ids.lock.json")
    }
    svg = data_dir / "source" / "map.svg"
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            'viewBox="0 0 1200 680"', 'viewBox="0 0 999 680"'
        ),
        encoding="utf-8",
    )
    assert run_build(data_dir, out_dir) == 1
    for name, blob in before.items():
        assert (data_dir / name).read_bytes() == blob


# ---------------------------------------------------- Spec 1.5: preview


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    return tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))


def test_preview_outline_scale():
    """Outlines share the fill transform (Spec 1.5 review fix).

    Regression: the outline pass reused mask-local coordinates, so every
    border line was shifted by the part's tile offset toward the top-left
    corner while fills rendered correctly.
    """
    from tools.map_pipeline.preview import render_map_preview

    colors = CFG.preview.colors
    border = _rgb(colors.border)
    land_c = _rgb(colors.land)
    a = box(300, 300, 310, 310)
    b = box(310, 300, 320, 310)
    paths = {"1001": [a], "1002": [b]}
    outside = [box(0, 0, 1200, 680).difference(unary_union([a, b]))]

    for window, ppu in (
        ((0.0, 0.0, 1200.0, 680.0), CFG.preview.pixels_per_unit),
        ((290.0, 290.0, 340.0, 330.0), CFG.preview.crop_pixels_per_unit),
    ):
        img = render_map_preview(paths, outside, window, ppu, colors)
        # shared edge x=310, mid-height y=305 -> image column/row
        edge_x = round((310 - window[0]) * ppu)
        mid_y = round((305 - window[1]) * ppu)
        strip = [img.getpixel((edge_x + dx, mid_y)) for dx in (-1, 0, 1)]
        assert border in strip, (window, ppu)

        # centres carry the land fill colour
        for cx, cy in ((305, 305), (315, 305)):
            px = (round((cx - window[0]) * ppu),
                  round((cy - window[1]) * ppu))
            assert img.getpixel(px) == land_c, (window, ppu, px)

        # no border pixels tangled in the top-left corner
        for x in range(10):
            for y in range(10):
                assert img.getpixel((x, y)) != border, (window, ppu, x, y)


# ------------------------------------------- Spec 1.5: fjord fill (3.2)


def _mini_sea() -> "object":
    """A real SeaRaster on a small synthetic frame for _fill_leftover."""
    import numpy as np

    from tools.map_pipeline.seas import (
        KIND_LAND,
        RasterFrame,
        SeaRaster,
    )

    frame = RasterFrame(0.0, 0.0, 40.0, 40.0, 4, 160, 160)
    kinds = np.full((160, 160), KIND_LAND, dtype=np.uint8)
    zeros = np.zeros((160, 160), dtype=bool)
    return SeaRaster(
        frame=frame, zone_keys=["sea_a", "sea_b"],
        zone_name_ru=["A", "B"], water=zeros, band=zeros,
        working=zeros, land=zeros.copy(), playable=zeros,
        labels=np.zeros((160, 160), dtype=np.int16), kinds=kinds,
        zone_areas=[0.0, 0.0],
    )


def _fill_setup():
    """Land bar with a 0.1-wide x 5-deep inlet over a sea zone."""
    mask = box(0, 0, 20, 10).difference(box(9.95, 5, 10.05, 10))
    zones = {"sea_a": box(0, 10, 20, 16)}
    clip = box(0, 0, 20, 20)
    return zones, mask, clip


def test_fjord_fill_merges_small_inlet():
    import copy

    from tools.map_pipeline.geometry import _fill_leftover

    zones, mask, clip = _fill_setup()
    sea = _mini_sea()
    cfg = copy.deepcopy(CFG)
    merged, marea, left, larea = _fill_leftover(
        zones, mask, clip, sea, cfg, {"sea_a": 1001},
    )
    assert merged == 1 and 0.4 < marea < 0.6
    assert zones["sea_a"].covers(Point(10.0, 7.5))
    # merged piece is gone from the leftover accounting
    assert left == 0 and larea == 0.0


def test_fjord_fill_respects_area_limit():
    import copy

    from tools.map_pipeline.geometry import _fill_leftover

    zones, mask, clip = _fill_setup()
    sea = _mini_sea()
    cfg = copy.deepcopy(CFG)
    cfg.sea_cut.fill_max_area = 0.4   # inlet piece is ~0.5 sq. units
    merged, _a, left, _b = _fill_leftover(
        zones, mask, clip, sea, cfg, {"sea_a": 1001},
    )
    assert merged == 0
    assert not zones["sea_a"].covers(Point(10.0, 7.5))


def test_fjord_fill_disabled_at_zero():
    import copy

    from tools.map_pipeline.geometry import _fill_leftover

    zones, mask, clip = _fill_setup()
    sea = _mini_sea()
    cfg = copy.deepcopy(CFG)
    cfg.sea_cut.fill_max_area = 0.0
    result = _fill_leftover(zones, mask, clip, sea, cfg, {"sea_a": 1001})
    assert result == (0, 0.0, 0, 0.0)
    assert not zones["sea_a"].covers(Point(10.0, 7.5))


def test_fjord_fill_skips_lake_pieces():
    import copy

    from tools.map_pipeline.geometry import _fill_leftover
    from tools.map_pipeline.seas import KIND_LAKE

    zones, mask, clip = _fill_setup()
    sea = _mini_sea()
    col, row = sea.frame.point_to_pixel(10.0, 7.5)   # piece rep-point
    sea.kinds[row, col] = KIND_LAKE
    cfg = copy.deepcopy(CFG)
    merged, _a, _l, _b = _fill_leftover(
        zones, mask, clip, sea, cfg, {"sea_a": 1001},
    )
    assert merged == 0
    assert not zones["sea_a"].covers(Point(10.0, 7.5))


def test_fjord_fill_tie_breaks_by_node_id():
    """Equal shared boundaries -> the smaller node id wins."""
    import copy

    from tools.map_pipeline.geometry import _fill_leftover

    mask = box(0, 0, 20, 10).difference(box(9.95, 5, 10.05, 10))
    zones = {"sea_a": box(0, 10, 10, 16), "sea_b": box(10, 10, 20, 16)}
    clip = box(0, 0, 20, 20)
    sea = _mini_sea()
    cfg = copy.deepcopy(CFG)
    merged, _a, _l, _b = _fill_leftover(
        zones, mask, clip, sea, cfg, {"sea_a": 1002, "sea_b": 1001},
    )
    assert merged == 1
    assert zones["sea_b"].covers(Point(10.0, 7.5))
    assert not zones["sea_a"].covers(Point(10.0, 7.5))


def test_fjord_fill_end_to_end(make_data_dir, tmp_path):
    """Sub-pixel inlets on a real fixture build end up sea-covered.

    Five 0.12-wide inlets at different pixel phases: at least one is
    raster-land and produces a leftover piece, whichever alignment the
    raster frame picks; all of them end up covered by the zone. A width
    of 0.12 is under one raster pixel (0.25) but survives the land mask's
    0.04 closing — the same geometry real fjords have.
    """
    cuts = []
    for i in reversed(range(5)):   # coast runs right-to-left (x descends)
        x = 20.0 + i * 0.31
        cuts.append(
            f"L {x + 0.12:.2f} 34 L {x + 0.12:.2f} 28 "
            f"L {x:.2f} 28 L {x:.2f} 34"
        )
    elems = [
        '<path id="Alpha" d="M 10 10 L 34 10 L 34 34 '
        + " ".join(cuts)
        + ' L 10 34 Z"/>',
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[22.0, 36.5]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    sea = unary_union(paths["sea_a"])
    for i in range(5):
        assert sea.covers(Point(20.0 + i * 0.31 + 0.06, 28.2)), i
    report = (out_dir / "build_report.md").read_text(encoding="utf-8")
    m = re.search(r"Fjord fill: merged (\d+) leftover pieces", report)
    assert m and int(m.group(1)) >= 1


# --------------------------------------- Spec 1.5: lake windows (3.3)


def test_lake_windows_only_near_playable_land(make_data_dir, tmp_path):
    """A lake beside playable land is a window; inside excluded land —
    dark ``outside``."""
    elems = (
        [square("Alpha", 10, 10, 12), square("Beta", 30, 10, 12)]
        + _ring("W", 60, 30, cell=6)      # included ring -> pond window
        + _ring("X", 100, 30, cell=6)     # excluded ring -> dark pond
    )
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha", "Beta"] + _ring_keys("W"),
        overrides=base_overrides(
            sea_margin=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[24.0, 16.0]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0
    geom = _geom_doc(data_dir)
    outside = unary_union(parse_path(geom["outside"]))
    assert outside.is_valid
    assert not outside.covers(Point(63.0, 33.0))     # window kept
    assert outside.covers(Point(103.0, 33.0))        # stays dark
    report = (out_dir / "build_report.md").read_text(encoding="utf-8")
    m = re.search(
        r"Lakes away from playable land \(no window\): (\d+) pieces",
        report,
    )
    assert m and int(m.group(1)) >= 1


# --------------------------------- Spec 1.9: bays vs lakes (3.2 step 5a)


def _c_shape(name, x, y, pond_w=4.6, pond_h=10.0, wall=0.4):
    """Thin-walled ``⊃`` at ``(x, y)``: with the province ending at ``x``
    it encloses a pond of ``pond_w x pond_h`` behind a ``wall``-thin bar."""
    t = wall
    return (
        f'<path id="{name}" d="M {x} {y} L {x + pond_w + t} {y} '
        f"L {x + pond_w + t} {y + pond_h + 2 * t} "
        f"L {x} {y + pond_h + 2 * t} "
        f"L {x} {y + pond_h + t} L {x + pond_w} {y + pond_h + t} "
        f'L {x + pond_w} {y + t} L {x} {y + t} Z"/>'
    )


def test_bays_and_lakes_step5a(make_data_dir, tmp_path):
    """Ponds within ``sea_link_gap`` of sea water are bays (exported as
    ``sea_water``, sea-coloured windows); remote ponds stay lakes.
    ``sea_like_water`` forces a bay, ``lake_force`` wins over both.

    The rings hug the main landmass so their moat stays inside the
    reached band piece (isolated rings would be unreached band water).
    """
    from conftest import kind_at

    elems = (
        [
            square("Alpha", 10, 10, 30),           # land (10..40, 10..40)
            _c_shape("Beta", 40.0, 19.6),          # pond (40..44.6, 20..30)
            _c_shape("Gamma", 40.0, 32.6, pond_h=5.4),  # pond 33..38.4
        ]
        + _ring("W", 52, 30, cell=6)               # pond (52..58, 30..36)
        + _ring("S", 72, 30, cell=6)               # pond (72..78, 30..36)
    )
    data_dir = make_data_dir(
        svg_elems=elems,
        include=(
            ["Alpha", "Beta", "Gamma"]
            + _ring_keys("W") + _ring_keys("S")
        ),
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[86.0, 33.0]]}],
            sea_like_water=[[75.0, 33.0], [42.3, 35.7]],
            lake_force=[[42.3, 35.7]],
            # pixel-centre distance across the 0.4 wall is ~0.75
            sea_link_gap=1.0,
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0

    geom = _geom_doc(data_dir)
    bay_d = Point(42.3, 25.0)      # behind a 0.4 wall -> bay by distance
    bay_f = Point(75.0, 33.0)      # remote pond, sea_like_water -> bay
    lake_f = Point(42.3, 35.7)     # lake_force beats sea_like_water
    lake_d = Point(55.0, 33.0)     # remote pond -> lake

    assert kind_at(out_dir, 42.3, 25.0) == 4   # KIND_BAY
    assert kind_at(out_dir, 75.0, 33.0) == 4
    assert kind_at(out_dir, 42.3, 35.7) == 3   # KIND_LAKE
    assert kind_at(out_dir, 55.0, 33.0) == 3

    sea_water = unary_union(parse_path(geom["sea_water"]))
    assert sea_water.covers(bay_d) and sea_water.covers(bay_f)
    assert not sea_water.covers(lake_f) and not sea_water.covers(lake_d)

    # every small body is a window in ``outside`` (bay or lake alike)
    outside = unary_union(parse_path(geom["outside"]))
    for p in (bay_d, bay_f, lake_f, lake_d):
        assert not outside.covers(p)

    report = (out_dir / "graph_report.md").read_text()
    assert "Lakes: 2" in report
    assert "Bays: 2" in report


# --------------------------------- Spec 1.10: coast cosmetics (map_polish_4)


def test_bay_window_needs_a_node(make_data_dir, tmp_path):
    """1.10: a bay touching no node stays dark inside ``outside`` and does
    not go into ``sea_water``; a node-touching bay keeps its window."""
    elems = (
        [square("Alpha", 10, 10, 12)]
        + _ring("W", 60, 30, cell=6)      # included ring -> bay window
        + _ring("G", 140, 30, cell=6)     # excluded ring -> dark pond
    )
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"] + _ring_keys("W"),
        overrides=base_overrides(
            sea_margin=30.0,
            sea_like_water=[[63.0, 33.0], [143.0, 33.0]],
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[24.0, 16.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    outside = unary_union(parse_path(geom["outside"]))
    sea_water = (
        unary_union(parse_path(geom["sea_water"]))
        if geom["sea_water"]
        else MultiPolygon()
    )
    node_pond = Point(63.0, 33.0)
    ghost_pond = Point(143.0, 33.0)
    assert not outside.covers(node_pond)
    assert sea_water.covers(node_pond)
    assert outside.covers(ghost_pond)
    assert not sea_water.covers(ghost_pond)


def test_small_part_scaled_tolerance(make_data_dir, tmp_path):
    """1.10: tol = min(tolerance, small_part_factor·sqrt(area)) — a small
    island keeps > 6 vertices while a large part still gets 0.03."""
    import math

    n = 14
    island = (
        " ".join(
            f"{'M' if i == 0 else 'L'} "
            f"{60.0 + (0.55 if i % 2 else 0.45) * math.cos(2 * math.pi * i / n):.2f} "
            f"{60.0 + (0.55 if i % 2 else 0.45) * math.sin(2 * math.pi * i / n):.2f}"
            for i in range(n)
        )
        + " Z"
    )
    zig = " ".join(
        f"L {10.5 + i * 0.5:.2f} {10.0 if i % 2 else 10.02:.2f}"
        for i in range(23)
    )
    elems = [
        f'<path id="Alpha" d="M 10 10 {zig} L 22 22 L 10 22 Z {island}"/>',
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[24.0, 16.0]]}],
        ),
    )
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    parts = _node_paths(geom, mani)["alpha"]
    island_part = min(parts, key=lambda p: p.area)
    big_part = max(parts, key=lambda p: p.area)
    assert island_part.area < 3.0
    assert len(island_part.exterior.coords) - 1 > 6
    assert len(big_part.exterior.coords) - 1 <= 8


def test_sea_cut_exact_land_edge(make_data_dir, tmp_path):
    """1.10: sea zones are cut by the exact land contours — a zone does
    not overlap a land rim (intersection area ~ 0)."""
    data_dir = make_data_dir(**_two_lands())
    assert run_build(data_dir, tmp_path / "out") == 0
    geom = _geom_doc(data_dir)
    mani = _manifest(data_dir)
    paths = _node_paths(geom, mani)
    land = unary_union(
        [
            p
            for n in mani["nodes"]
            if n["kind"] == "LAND"
            for p in paths[n["key"]]
        ]
    )
    sea = unary_union(paths["sea_a"])
    assert land.intersection(sea).area < 0.002
