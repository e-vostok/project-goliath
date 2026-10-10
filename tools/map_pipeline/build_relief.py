"""map2_5: bake the grayscale relief underlay for the 01_map client.

Input : a Natural Earth raster («Gray Earth with Shaded Relief and
        Hypsography», plate carrée) as the downloaded .zip or the .tif
        inside it — fetched manually, NEVER committed.
        Registration (lon/lat -> base units) is the fitted transform in
        ``tools/map_pipeline/relief/registration.json`` — the same for
        every Natural Earth plate-carrée raster.
Frame : ``view.frame`` of ``configs/01_map.yaml`` grown by
        ``relief.margin_units`` on every side; the picture edge fades to
        transparent (sea colour underneath) over ``relief.edge_fade_units``.
Output: ONE grayscale+alpha image ``frontend/public/assets/map/
        relief.<sha256[:12]>.<ext>`` (the smaller of WebP and JPEG) and
        the client pointer ``frontend/src/modules/01_map/relief/
        manifest.json`` so a changed picture is never served stale.

Land mask: sea in this raster is a flat mid-gray — pixels in
``SEA_BAND`` with a sub-1.2 local std; only connected components of at
least ``MIN_SEA_UNITS2`` square units count as water (small flat plains
and speckles stay land). Provinces always get relief pixels: where our
coast overshoots the raster coast, the value is filled with the nearest
land texel (``COAST_BLEED_UNITS``). Our lakes and ``sea_water`` bays are
cut out so they stay sea colour.

Run (from repo root):
    python -m tools.map_pipeline.build_relief --raster <GRAY_HR_SR.zip>
        [--check-coast] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy.ndimage import (
    distance_transform_edt,
    label,
    map_coordinates,
    uniform_filter,
)

from tools.map_pipeline.relief.transform import Transform, load as load_transform
from tools.map_pipeline.svgpath import parse_path

Image.MAX_IMAGE_PIXELS = None  # Natural Earth HR is ~230 Mpx, expected

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "map"
CONFIG_PATH = REPO_ROOT / "configs" / "01_map.yaml"
REGISTRATION = REPO_ROOT / "tools" / "map_pipeline" / "relief" / "registration.json"
WEB_DIR = REPO_ROOT / "frontend" / "public" / "assets" / "map"
CLIENT_MANIFEST = (
    REPO_ROOT / "frontend" / "src" / "modules" / "01_map" / "relief" / "manifest.json"
)

# ------------------------------------------------------------- parameters

MAX_PPU = 18.0          # px per base unit cap — the source is soft above
WEBP_QUALITY = 78
JPEG_QUALITY = 80
SIZE_BUDGET = 1_500_000  # bytes; lower quality first, never resolution

SEA_BAND = (142, 149)   # flat-water value range in GRAY_*_SR rasters
SEA_MAX_STD = 1.2       # local 5x5 std — the raster sea is texture-free
MIN_SEA_UNITS2 = 2.5    # smaller flat components are land texture
COAST_BLEED_UNITS = 0.7  # nearest-land fill under our coast overshoot
RELIEF_CONTRAST = 0.6   # keep this share of deviation from the local mean
CONTRAST_SIGMA_UNITS = 0.9
EDGE_FADE_SMOOTH = True  # smoothstep fade, not linear

# Coast agreement control points (lon, lat) — checked by --check-coast.
CONTROL_POINTS = {
    "bosphorus": (29.0, 41.15),
    "gibraltar": (-5.55, 35.95),
    "danish_straits": (12.55, 55.6),
    "gulf_of_finland": (26.8, 59.9),
    "strait_of_messina": (15.65, 38.25),
}
CHECK_BOX_HALF = 4.0     # +- units around each control point
CHECK_PPU = 48.0         # rasterisation density for the comparison
SHIFT_LIMIT = 1.5        # units; above this the registration is wrong


class ReliefBuildError(RuntimeError):
    """Build input is inconsistent (registration off-raster, etc.)."""


# --------------------------------------------------------------- loading


def read_world_file(raw: bytes):
    """Parse a .tfw -> (lon, lat) -> (col, row) of pixel CENTRES."""
    a, d, b, e, c, f = [float(v) for v in raw.split()[:6]]
    det = a * e - b * d
    if abs(det) < 1e-15:
        raise ReliefBuildError("degenerate .tfw world file")

    def to_px(lon, lat):
        col = (e * (lon - c) - b * (lat - f)) / det
        row = (-d * (lon - c) + a * (lat - f)) / det
        return col, row

    return to_px


def load_raster(path: Path):
    """Return (uint8 L or RGB array, to_px) from a .zip or a .tif.

    The Natural Earth zip is opened in memory — the ~230 Mpx tif never
    touches the disk outside the caller's temp folder.
    """
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            tif = next(
                n for n in z.namelist() if n.lower().endswith(".tif")
            )
            tfw = next(
                n for n in z.namelist() if n.lower().endswith(".tfw")
            )
            data = z.read(tif)
            tfw_raw = z.read(tfw)
        img = Image.open(io.BytesIO(data))
        to_px = read_world_file(tfw_raw)
    else:
        img = Image.open(path)
        to_px = read_world_file(path.with_suffix(".tfw").read_bytes())
    raster = np.asarray(img)
    return raster, to_px


def load_map_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text("utf-8"))


def load_geometry() -> dict:
    return json.loads((DATA_DIR / "geometry.json").read_text("utf-8"))


def load_manifest() -> dict:
    return json.loads((DATA_DIR / "manifest.json").read_text("utf-8"))


# ----------------------------------------------------------------- masks


def rasterize(polys, rect, ppu: float, fill: int = 255) -> np.ndarray:
    """Rasterise polygons over ``rect = (x0, y0, x1, y1)`` base units."""
    x0, y0, x1, y1 = rect
    w = max(1, int(round((x1 - x0) * ppu)))
    h = max(1, int(round((y1 - y0) * ppu)))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)

    def to_px(coords):
        return [((x - x0) * ppu, (y - y0) * ppu) for x, y in coords]

    for poly in polys:
        geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            draw.polygon(to_px(g.exterior.coords), fill=fill)
            for hole in g.interiors:
                draw.polygon(to_px(hole.coords), fill=0)
    return np.asarray(img)


def interior_polys(polys) -> list:
    """Lake holes: every interior ring as a standalone polygon."""
    from shapely.geometry import Polygon

    holes = []
    for poly in polys:
        geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            holes.extend(Polygon(r) for r in g.interiors)
    return holes


def our_masks(rect, ppu, geometry, manifest):
    """(playable LAND, lake holes, sea_water) masks over the rect."""
    kinds = {str(n["id"]): n["kind"] for n in manifest["nodes"]}
    playable_polys = []
    for key, d in geometry["paths"].items():
        if kinds.get(str(key)) == "LAND":
            playable_polys.extend(parse_path(d))
    playable = rasterize(playable_polys, rect, ppu) > 0
    outside_polys = parse_path(geometry["outside"])
    lakes = rasterize(interior_polys(outside_polys), rect, ppu) > 0
    sea_water = (
        rasterize(parse_path(geometry["sea_water"]), rect, ppu) > 0
        if geometry.get("sea_water")
        else np.zeros_like(playable)
    )
    return playable, lakes, sea_water


def raster_land_mask(gray: np.ndarray, ppu: float) -> np.ndarray:
    """Raster-true land: sea is the flat mid-gray, large components."""
    band = (gray >= SEA_BAND[0]) & (gray <= SEA_BAND[1])
    g = gray.astype(np.float32)
    std = np.sqrt(
        np.clip(
            uniform_filter(g * g, size=5) - uniform_filter(g, size=5) ** 2,
            0.0,
            None,
        )
    )
    flat_sea = band & (std <= SEA_MAX_STD)
    lbl, _n = label(flat_sea)
    counts = np.bincount(lbl.ravel())
    big = counts >= MIN_SEA_UNITS2 * ppu * ppu
    big[0] = False
    return ~big[lbl]


def edge_fade(shape, rect, ppu: float, fade_units: float) -> np.ndarray:
    """1 inside, soft-stepping to 0 at the rect border."""
    h, w = shape
    if fade_units <= 0:
        return np.ones(shape, dtype=np.float32)
    fade_px = fade_units * ppu
    rows = np.arange(h, dtype=np.float32) + 0.5
    cols = np.arange(w, dtype=np.float32) + 0.5
    dist = np.minimum.reduce(
        [
            np.broadcast_to(rows[:, None], (h, w)),
            np.broadcast_to((h - rows)[:, None], (h, w)),
            np.broadcast_to(cols[None, :], (h, w)),
            np.broadcast_to((w - cols)[None, :], (h, w)),
        ]
    )
    t = np.clip(dist / fade_px, 0.0, 1.0).astype(np.float32)
    if EDGE_FADE_SMOOTH:
        t = t * t * (3.0 - 2.0 * t)
    return t


# ------------------------------------------------------------------ bake


def warp(rect, ppu, transform: Transform, raster, to_px):
    """Resample the raster onto the base-coordinate grid of ``rect``."""
    x0, y0, x1, y1 = rect
    w = int(round((x1 - x0) * ppu))
    h = int(round((y1 - y0) * ppu))
    if w <= 0 or h <= 0:
        raise ReliefBuildError(f"degenerate output grid {w}x{h}")
    cols = np.arange(w) + 0.5
    rows = np.arange(h) + 0.5
    bx, by = np.meshgrid(x0 + cols / ppu, y0 + rows / ppu)
    lon, lat = transform.inv(bx, by)
    sc, sr = to_px(lon, lat)
    h_src, w_src = raster.shape[:2]
    outside = (
        (sc < -0.5) | (sc > w_src - 0.5) | (sr < -0.5) | (sr > h_src - 0.5)
    )
    share = float(outside.mean())
    if share > 0.005:
        raise ReliefBuildError(
            "registration maps "
            f"{share:.1%} of the frame ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) "
            f"outside the source raster ({w_src}x{h_src} px) — "
            "check view.frame, relief.margin_units and registration.json"
        )
    if raster.ndim == 2:
        return map_coordinates(
            raster, [np.clip(sr, 0, h_src - 1), np.clip(sc, 0, w_src - 1)],
            order=1,
            mode="nearest",
        )
    out = np.empty((h, w, raster.shape[2]), dtype=raster.dtype)
    for ch in range(raster.shape[2]):
        out[..., ch] = map_coordinates(
            raster[..., ch],
            [np.clip(sr, 0, h_src - 1), np.clip(sc, 0, w_src - 1)],
            order=1,
            mode="nearest",
        )
    return out


def bake(rect, ppu, transform, raster, to_px, geometry, manifest,
         relief_cfg: dict):
    """Return the LA image array (H x W x 2 uint8) for the frame rect."""
    gray = warp(rect, ppu, transform, raster, to_px)
    if gray.ndim == 3:
        gray = (
            0.299 * gray[..., 0] + 0.587 * gray[..., 1]
            + 0.114 * gray[..., 2]
        ).astype(np.uint8)

    land_r = raster_land_mask(gray, ppu)
    playable, lakes, sea_water = our_masks(rect, ppu, geometry, manifest)

    # Nearest-land fill so province coasts overshooting the raster
    # coast never show sea colour under the multiply fills.
    _dist, idx = distance_transform_edt(~land_r, return_indices=True)
    filled = gray[idx[0], idx[1]]
    gray = np.where(playable | land_r, np.where(land_r, gray, filled),
                    gray)

    # Gentle local-contrast grading (prototype constant): broad height
    # tint survives, but the picture cannot go muddy under the fills.
    g = gray.astype(np.float32)
    mean = uniform_filter(g, size=max(3, int(CONTRAST_SIGMA_UNITS * ppu)))
    gray = np.clip(mean + (g - mean) * RELIEF_CONTRAST, 0, 255)

    alpha = (land_r | playable) & ~lakes & ~sea_water
    alpha_f = alpha.astype(np.float32) * edge_fade(
        gray.shape, rect, ppu, relief_cfg["edge_fade_units"]
    )
    return np.dstack(
        [gray.astype(np.uint8), (alpha_f * 255).astype(np.uint8)]
    )


def encode_webp(la: np.ndarray, quality: int) -> bytes:
    img = Image.fromarray(la, "LA")
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def encode_jpeg(la: np.ndarray, sea_rgb: tuple[int, int, int],
                quality: int) -> bytes:
    """Same picture flattened onto the sea colour (no alpha)."""
    luma = la[..., 0].astype(np.float32)[..., None]
    alpha = la[..., 1].astype(np.float32)[..., None] / 255.0
    rgb = np.clip(
        luma * alpha + np.asarray(sea_rgb, dtype=np.float32) * (1 - alpha),
        0, 255,
    ).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def native_ppu(raster, to_px, georef_k: float) -> float:
    """Px per base unit along the raster's x axis (plate carrée)."""
    c0, _ = to_px(np.array([0.0]), np.array([0.0]))
    c1, _ = to_px(np.array([1.0]), np.array([0.0]))
    px_per_deg = abs(float(c1[0] - c0[0]))
    return px_per_deg / georef_k


def frame_rect(frame: dict, margin: float) -> tuple[float, float, float, float]:
    return (
        frame["x"] - margin,
        frame["y"] - margin,
        frame["x"] + frame["width"] + margin,
        frame["y"] + frame["height"] + margin,
    )


# ------------------------------------------------------------ coast check


def coast_report(transform, raster, to_px, geometry, manifest) -> int:
    """Max coastline shift at the five control points, in base units."""
    from scipy.ndimage import binary_erosion

    kinds = {str(n["id"]): n["kind"] for n in manifest["nodes"]}
    polys = list(parse_path(geometry["outside"]))
    for key, d in geometry["paths"].items():
        if kinds.get(str(key)) != "SEA":
            polys.extend(parse_path(d))
    from shapely.ops import unary_union

    union = unary_union(polys)
    worst = 0.0
    for name, (lon, lat) in CONTROL_POINTS.items():
        cx, cy = transform.fwd(np.array([lon]), np.array([lat]))
        rect = (
            float(cx[0]) - CHECK_BOX_HALF,
            float(cy[0]) - CHECK_BOX_HALF,
            float(cx[0]) + CHECK_BOX_HALF,
            float(cy[0]) + CHECK_BOX_HALF,
        )
        gray = warp(rect, CHECK_PPU, transform, raster, to_px)
        if gray.ndim == 3:
            gray = gray[..., 0]
        land_r = raster_land_mask(gray, CHECK_PPU)
        edge_r = land_r & ~binary_erosion(land_r)
        dt_r = distance_transform_edt(~edge_r)
        ours = rasterize([union], rect, CHECK_PPU) > 0
        edge_o = ours & ~binary_erosion(ours)
        dt_o = distance_transform_edt(~edge_o)

        d1 = dt_r[edge_o] / CHECK_PPU
        near = edge_r & (distance_transform_edt(~ours) <= 3 * CHECK_PPU)
        d2 = dt_o[near] / CHECK_PPU
        m1 = float(d1.max()) if d1.size else 0.0
        m2 = float(d2.max()) if d2.size else 0.0
        worst = max(worst, m1, m2)
        print(
            f"  {name:20s} ours->relief max={m1:.2f}u "
            f"p95={np.percentile(d1, 95):.2f}u | "
            f"relief->ours max={m2:.2f}u"
        )
    print(f"  max coastline shift: {worst:.2f} units (limit {SHIFT_LIMIT})")
    return worst


# ------------------------------------------------------------------- main


def build(raster, to_px, transform, geometry, manifest, relief_cfg,
          frame_cfg, georef_k, sea_rgb):
    """Warp + mask + encode. Returns (la array, image bytes, ext, stats)."""
    margin = relief_cfg["margin_units"]
    rect = frame_rect(frame_cfg, margin)
    ppu = min(MAX_PPU, native_ppu(raster, to_px, georef_k))
    la = bake(rect, ppu, transform, raster, to_px, geometry, manifest,
              relief_cfg)
    h, w = la.shape[:2]
    webp = encode_webp(la, WEBP_QUALITY)
    jpeg = encode_jpeg(la, sea_rgb, JPEG_QUALITY)
    ext, body = ("webp", webp) if len(webp) <= len(jpeg) else ("jpg", jpeg)
    stats = {
        "rect": rect,
        "ppu": round(ppu, 2),
        "pixels": [w, h],
        "webp_bytes": len(webp),
        "jpeg_bytes": len(jpeg),
        "chosen": ext,
    }
    return la, body, ext, stats


def write_outputs(body: bytes, ext: str, rect, ppu: float,
                  source_name: str, dry_run: bool) -> dict:
    sha = hashlib.sha256(body).hexdigest()
    name = f"relief.{sha[:12]}.{ext}"
    manifest = {
        "file": f"/assets/map/{name}",
        "rect": [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]],
        "px_per_unit": round(ppu, 2),
        "bytes": len(body),
        "sha256": sha,
        "source": source_name,
    }
    if not dry_run:
        WEB_DIR.mkdir(parents=True, exist_ok=True)
        for stale in WEB_DIR.glob("relief.*"):
            stale.unlink()
        (WEB_DIR / name).write_bytes(body)
        CLIENT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        CLIENT_MANIFEST.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raster", type=Path, required=True,
                        help="Natural Earth .zip or .tif (never committed)")
    parser.add_argument("--registration", type=Path, default=REGISTRATION)
    parser.add_argument("--check-coast", action="store_true",
                        help="report coastline shift at the control points")
    parser.add_argument("--dry-run", action="store_true",
                        help="bake and report, write nothing")
    args = parser.parse_args(argv)

    config = load_map_config()
    relief_cfg = config["relief"]
    transform = load_transform(args.registration)
    geometry = load_geometry()
    manifest = load_manifest()

    print(f"loading {args.raster.name}…", flush=True)
    raster, to_px = load_raster(args.raster)
    print(f"  {raster.shape[1]}x{raster.shape[0]} {raster.dtype}",
          flush=True)

    if args.check_coast:
        print("coast control points:")
        coast_report(transform, raster, to_px, geometry, manifest)

    la, body, ext, stats = build(
        raster, to_px, transform, geometry, manifest, relief_cfg,
        config["view"]["frame"], manifest["georef"]["k"],
        hex_rgb(config["colors"]["sea"]),
    )
    print(
        f"baked {stats['pixels'][0]}x{stats['pixels'][1]} "
        f"@ {stats['ppu']} px/unit — webp {stats['webp_bytes']} B, "
        f"jpeg {stats['jpeg_bytes']} B -> {ext}"
    )
    if stats["chosen"] == "webp" and len(body) > SIZE_BUDGET:
        print(f"WARNING: {len(body)} B exceeds the {SIZE_BUDGET} B budget")
    out = write_outputs(body, ext, stats["rect"], stats["ppu"],
                        args.raster.name, args.dry_run)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
