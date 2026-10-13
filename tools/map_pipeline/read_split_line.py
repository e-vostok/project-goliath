"""map2_2 Phase B: read the Owner's red split line back to base coords.

    python -m tools.map_pipeline.read_split_line <key> \
        --new-key matruh --new-name Matruh

Reads ``reference/<key>_split_markup.png`` — the Phase A canvas with ONE
pure-red (255,0,0) stroke drawn across the province — extracts the stroke,
maps it through ``<key>_split_canvas.registration.json`` (a rescaled copy
of the canvas is accepted: pixel coordinates are normalised to the
registered size), thins it to a single polyline via the diameter path of
the pixel graph, simplifies it and extends both ends beyond the province
outline.

The result is dry-run through the real ``geometry_patches`` machinery
(source geometry + all earlier patches, then the candidate ``split``), the
check picture ``<key>_split_check.png`` is written for review, and the
ready ``overrides.yaml`` entry is printed. Nothing under ``data/`` changes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import LineString, Point

from .errors import (
    DATA_INVALID,
    PipelineError,
    PipelineFailure,
    print_errors,
)
from .make_split_canvas import PAD_UNITS, TARGET_LONG_SIDE, render_canvas
from .models import (
    GeometryPatch,
    SplitPatch,
    collect_reference_errors,
    load_boundary,
    load_overrides,
)
from .patches import apply_geometry_patches
from .pipeline_config_schema import load_pipeline_config
from .svg_source import build_geometries, read_province_paths, safe_union
from .svgpath import parse_path

MARKUP_RED = np.array([255, 0, 0])
_RED_TOL2 = 8000  # squared RGB distance; covers anti-aliased edges

_SIMPLIFY = 0.05    # polyline tolerance, base units
_EXTEND = 1.5       # line ends pushed this far past the drawn stroke
_LINE_COLOR = (0, 255, 255)
_CROSS_COLOR = (255, 0, 255)

REF = Path("tools/map_pipeline/reference")


def _red_mask(img: Image.Image) -> np.ndarray:
    rgb = np.asarray(img.convert("RGB"), dtype=np.int32)
    return ((rgb - MARKUP_RED) ** 2).sum(-1) <= _RED_TOL2


def _largest_component(mask: np.ndarray) -> np.ndarray:
    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        raise PipelineError(
            DATA_INVALID, "no pure-red markup found in the image"
        )
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(sizes.argmax())


def _bfs_farthest(
    start: tuple[int, int], pixels: set[tuple[int, int]]
) -> tuple[tuple[int, int], dict]:
    """Farthest pixel from ``start`` inside ``pixels`` + parent map."""
    prev = {start: None}
    q = deque([start])
    last = start
    while q:
        cur = q.popleft()
        last = cur
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nxt = (cur[0] + dr, cur[1] + dc)
                if nxt in pixels and nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
    return last, prev


def _stroke_path(mask: np.ndarray) -> list[tuple[int, int]]:
    """Pixel-centre polyline of the stroke: graph-diameter BFS path."""
    pixels = set(map(tuple, np.argwhere(mask)))
    end_a, _ = _bfs_farthest(next(iter(pixels)), pixels)
    end_b, prev = _bfs_farthest(end_a, pixels)
    path = [end_b]
    while prev[path[-1]] is not None:
        path.append(prev[path[-1]])
    return path[::-1]  # (row, col) tuples, end_a -> end_b


def _to_base(
    path: list[tuple[int, int]],
    reg: dict,
    image_size: tuple[int, int],
) -> list[tuple[float, float]]:
    """Pixel indices -> base coordinates via the registration."""
    ppu = reg["px_per_unit"]
    ox, oy = reg["origin_x"], reg["origin_y"]
    rw, rh = reg["image_size"]
    iw, ih = image_size
    ppu_x, ppu_y = ppu * iw / rw, ppu * ih / rh
    return [
        (ox + (col + 0.5) / ppu_x, oy + (row + 0.5) / ppu_y)
        for row, col in path
    ]


def _simplify_extend(
    coords: list[tuple[float, float]], tolerance: float = _SIMPLIFY
) -> list[tuple[float, float]]:
    """Simplify to a few vertices, then extend both ends by _EXTEND."""
    line = LineString(coords).simplify(tolerance)
    pts = list(line.coords)
    if len(pts) < 2:
        raise PipelineError(
            DATA_INVALID, "markup stroke degenerated to a single point"
        )
    ax, ay = pts[0]
    bx, by = pts[1]
    dx, dy = ax - bx, ay - by
    n = float(np.hypot(dx, dy))
    head = (ax + dx / n * _EXTEND, ay + dy / n * _EXTEND)
    ax, ay = pts[-2]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    n = float(np.hypot(dx, dy))
    tail = (bx + dx / n * _EXTEND, by + dy / n * _EXTEND)
    return [head, *pts, tail]


def _crossings(parts, line: LineString) -> list[Point]:
    inter = safe_union(parts).boundary.intersection(line)
    if inter.is_empty:
        return []
    if inter.geom_type == "Point":
        return [inter]
    if inter.geom_type == "MultiPoint":
        return list(inter.geoms)
    return []


def _draw_check(
    manifest: dict,
    geometry: dict,
    key: str,
    colors,
    line: list[tuple[float, float]],
    out_path: Path,
) -> None:
    """Fresh canvas plus the registered split line for visual review."""
    node = next(n for n in manifest["nodes"] if n["key"] == key)
    x0, y0, x1, y1 = node["bbox"]
    crop = (x0 - PAD_UNITS, y0 - PAD_UNITS, x1 + PAD_UNITS, y1 + PAD_UNITS)
    ppu = TARGET_LONG_SIDE / max(crop[2] - crop[0], crop[3] - crop[1])
    img, _ = render_canvas(manifest, geometry, key, crop, ppu, colors)
    draw = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] - crop[0]) * ppu, (p[1] - crop[1]) * ppu)

    draw.line([px(p) for p in line], fill=_LINE_COLOR, width=4)
    for p in (line[0], line[-1]):
        x, y = px(p)
        draw.ellipse([x - 6, y - 6, x + 6, y + 6], outline=_LINE_COLOR,
                     width=3)
    crosses = _crossings(
        parse_path(geometry["paths"][str(node["id"])]),
        LineString(line),
    )
    for c in crosses:
        x, y = px((c.x, c.y))
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline=_CROSS_COLOR,
                     width=3)
    img.convert("RGB").save(out_path)


def run(
    data_dir: Path,
    key: str,
    image_path: Path,
    reg_path: Path,
    out_dir: Path,
    new_key: str,
    new_name: str,
    keep_point: tuple[float, float] | None,
) -> dict:
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    img = Image.open(image_path)
    mask = _largest_component(_red_mask(img))
    coords = _simplify_extend(_to_base(_stroke_path(mask), reg, img.size))

    manifest = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    node = next(n for n in manifest["nodes"] if n["key"] == key)
    if keep_point is None:
        keep_point = tuple(node["anchor"])

    split = SplitPatch(
        key=key,
        line=coords,
        keep_point=list(keep_point),
        new_key=new_key,
        new_name=new_name,
    )
    boundary = load_boundary(data_dir / "boundary.yaml")
    overrides = load_overrides(data_dir / "overrides.yaml")
    trial = overrides.model_copy(
        update={
            "geometry_patches": [
                *overrides.geometry_patches,
                GeometryPatch(split=split),
            ]
        }
    )
    ref_errors = collect_reference_errors(trial, boundary)
    if ref_errors:
        raise PipelineFailure(ref_errors)

    cfg = load_pipeline_config()
    paths = read_province_paths(data_dir / "source" / "map.svg")
    geoms = build_geometries(paths, cfg.clean)
    geoms, info, additions = apply_geometry_patches(geoms, trial)

    geometry = json.loads(
        (data_dir / "geometry.json").read_text(encoding="utf-8")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    check_path = out_dir / f"{key}_split_check.png"
    _draw_check(manifest, geometry, key, cfg.preview.colors, coords,
                check_path)

    parts = {
        name: safe_union(geoms[name]).area
        for name in (node["source_name"], new_name)
    }
    return {
        "line": [(round(x, 2), round(y, 2)) for x, y in coords],
        "keep_point": keep_point,
        "patch_info": info[-1],
        "parts": parts,
        "check": check_path,
        "additions": additions,
        "rescaled": list(img.size) != reg["image_size"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.map_pipeline.read_split_line",
        description="Register the Owner's red split line to base "
        "coordinates and dry-run the split patch.",
    )
    parser.add_argument("key", help="node key, e.g. alexandria")
    parser.add_argument("--data-dir", default="data/map", type=Path)
    parser.add_argument("--image", default=None, type=Path)
    parser.add_argument("--registration", default=None, type=Path)
    parser.add_argument("--out-dir", default=REF, type=Path)
    parser.add_argument("--new-key", required=True)
    parser.add_argument("--new-name", required=True)
    parser.add_argument(
        "--keep-point",
        default=None,
        help='"x,y" inside the part that keeps the old key '
        "(default: the node's current anchor)",
    )
    args = parser.parse_args(argv)
    image = args.image or REF / f"{args.key}_split_markup.png"
    reg_path = args.registration or REF / (
        f"{args.key}_split_canvas.registration.json"
    )
    keep = None
    if args.keep_point:
        keep = tuple(float(v) for v in args.keep_point.split(","))
        if len(keep) != 2:
            print("bad --keep-point", file=sys.stderr)
            return 1
    try:
        info = run(
            args.data_dir, args.key, image, reg_path, args.out_dir,
            args.new_key, args.new_name, keep,
        )
    except PipelineFailure as failure:
        print_errors(failure.errors)
        return 1
    except PipelineError as err:
        print_errors([err])
        return 1
    if info["rescaled"]:
        print("note: markup image size differs from the registered "
              "canvas — coordinates normalised")
    print(f"{info['check']}")
    print(info["patch_info"])
    print("overrides.yaml entry:")
    print(f"  - split:")
    print(f"      key: {args.key}")
    print(f"      line: {[list(p) for p in info['line']]}")
    print(f"      keep_point: {list(info['keep_point'])}")
    print(f"      new_key: {args.new_key}")
    print(f'      new_name: "{args.new_name}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
