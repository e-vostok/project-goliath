"""map2_16: bake the two relief rasters for the 01_map client.

Input : a Natural Earth raster («Gray Earth with Shaded Relief and
        Hypsography», plate carrée) as the downloaded .zip or the .tif
        inside it — fetched manually, NEVER committed.
        Registration (lon/lat -> base units) is the fitted transform in
        ``tools/map_pipeline/relief/registration.json`` — the same for
        every Natural Earth plate-carrée raster; its Gall model maps
        the WHOLE globe to a finite rectangle of base units.

Output (two WebP/PNG images with alpha, content-hashed, written to
``frontend/public/assets/map/`` plus the client pointer
``frontend/src/modules/01_map/relief/manifest.json``):

a) PLAYABLE — up to ``MAX_PPU`` px/unit over the LAND-node bbox.
   Luma is the graded relief; alpha comes ONLY from the geometry:
   255 inside LAND polygons with their holes (even-odd, rasterised
   at 2x supersampling), 0 elsewhere — no halo, no phantom islets,
   no softening on any coast.

b) INACTIVE — ``WORLD_PPU`` px/unit over the whole world rect.
   Luma is the relief dimmed by ``relief.inactive_brightness``.
   Alpha = raster land mask MINUS the playable union (all node
   polygons with holes filled, eroded by ``SUBTRACT_ERODE_UNITS`` so
   the dark land laps a little under the opaque fills — the visible
   edge stays exactly the province shape); plus the land parts of
   ``outside`` (the excluded zone) — which the formula already
   covers. Everywhere else alpha 0: ocean stays plain sea colour.

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
    binary_erosion,
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

MAX_PPU = 18.0            # playable-image px/unit cap (source is soft above)
MIN_PPU = 8.0             # playable floor under the byte budget (TZ)
WORLD_PPU = 5.0           # inactive-image px/unit (TZ allows 4..6)
WORLD_PPU_MIN = 4.0
SIZE_BUDGET = 3_000_000   # bytes, BOTH images together (TZ)
WEBP_QUALITY = 78
PNG_COMPRESS = 9

SEA_BAND = (142, 149)    # flat-water value range in GRAY_*_SR rasters
SEA_MAX_STD = 1.2        # local 5x5 std — the raster sea is texture-free
MIN_SEA_UNITS2 = 2.5     # smaller flat components are land texture
RELIEF_CONTRAST = 0.6    # keep this share of deviation from the local mean
CONTRAST_SIGMA_UNITS = 0.9
SUBTRACT_ERODE_UNITS = 1.0  # inactive land laps this far under the fills
POLE_LAT_CUT = 88.0         # |lat| above this is forced sea (pole artifact)
RECT_PAD_UNITS = 1.0        # output rect padding around tight bounds
AA_SCALE = 2                # supersampling for polygon-alpha edges

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


def rasterize(polys, rect, ppu: float, fill: int = 255,
              filled: bool = False) -> np.ndarray:
    """Rasterise polygons over ``rect = (x0, y0, x1, y1)`` base units.

    ``filled=True`` ignores interior rings (province holes filled).
    """
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
            if not filled:
                for hole in g.interiors:
                    draw.polygon(to_px(hole.coords), fill=0)
    return np.asarray(img)


def poly_alpha(polys, rect, ppu: float) -> np.ndarray:
    """Anti-aliased 0..255 alpha: polygons with holes, 2x supersample."""
    hi = rasterize(polys, rect, ppu * AA_SCALE)
    h, w = hi.shape
    img = Image.fromarray(hi, "L").resize(
        (w // AA_SCALE, h // AA_SCALE), Image.BOX
    )
    return np.asarray(img)


def node_polys(geometry, manifest, kind=None):
    """Polygons of all nodes (or of one kind) from geometry paths."""
    kinds = {str(n["id"]): n["kind"] for n in manifest["nodes"]}
    polys = []
    for key, d in geometry["paths"].items():
        if kind is None or kinds.get(str(key)) == kind:
            polys.extend(parse_path(d))
    return polys


def land_bbox(geometry, manifest, pad: float) -> tuple:
    """Bounding rect of all LAND polygons plus ``pad`` units."""
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for poly in node_polys(geometry, manifest, "LAND"):
        for g in (
            poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
        ):
            bx0, by0, bx1, by1 = g.bounds
            x0, y0 = min(x0, bx0), min(y0, by0)
            x1, y1 = max(x1, bx1), max(y1, by1)
    if x0 > x1:
        raise ReliefBuildError("no LAND polygons in geometry")
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def world_rect(transform: Transform, pad: float) -> tuple:
    """Outer envelope of the transformed globe border, plus ``pad``.

    Gall is cylindrical: the -180..180 / -90..90 sphere maps to a
    finite rectangle; the TPS term can wobble edges a little, so the
    border is sampled densely instead of trusting four corners.
    """
    lon = np.linspace(-180.0, 180.0, 721)
    lat = np.linspace(-90.0, 90.0, 361)
    xs, ys = [], []
    for lo, la in [
        (lon, np.full_like(lon, 90.0)),
        (lon, np.full_like(lon, -90.0)),
        (np.full_like(lat, -180.0), lat),
        (np.full_like(lat, 180.0), lat),
    ]:
        bx, by = transform.fwd(lo, la)
        xs.append(bx)
        ys.append(by)
    xs = np.concatenate(xs)
    ys = np.concatenate(ys)
    return (
        float(xs.min()) - pad,
        float(ys.min()) - pad,
        float(xs.max()) + pad,
        float(ys.max()) + pad,
    )


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


def grade(gray: np.ndarray, ppu: float) -> np.ndarray:
    """Keep ``RELIEF_CONTRAST`` of the deviation from the local mean."""
    g = gray.astype(np.float32)
    mean = uniform_filter(g, size=max(3, int(CONTRAST_SIGMA_UNITS * ppu)))
    return np.clip(mean + (g - mean) * RELIEF_CONTRAST, 0, 255)


# ------------------------------------------------------------------ bake


def warp(rect, ppu, transform: Transform, raster, to_px,
         strict_share: float | None = 0.005):
    """Resample the raster onto the base-coordinate grid of ``rect``.

    Returns (gray, valid, lats): ``valid`` marks pixels whose source
    point lands inside the raster's lon/lat coverage — off-globe pixels
    are sampled from the clamped edge and must stay transparent;
    ``lats`` is the geographic latitude of every output pixel.

    ``strict_share`` — if given, fail when more than this share of the
    rect maps outside the source (a wrong registration), instead of
    silently marking those pixels invalid.
    """
    x0, y0, x1, y1 = rect
    w = int(round((x1 - x0) * ppu))
    h = int(round((y1 - y0) * ppu))
    if w <= 0 or h <= 0:
        raise ReliefBuildError(f"degenerate output grid {w}x{h}")
    cols = np.arange(w) + 0.5
    rows = np.arange(h) + 0.5
    h_src, w_src = raster.shape[:2]
    # Row bands keep the TPS kernel matrix (points x 250 centres)
    # bounded on the ~28 MP world grid.
    band = max(1, int(np.ceil(1_000_000 / w)))
    lons = np.empty((h, w))
    lats = np.empty((h, w))
    for r0 in range(0, h, band):
        r1 = min(h, r0 + band)
        bx, by = np.meshgrid(
            x0 + cols / ppu, y0 + rows[r0:r1] / ppu
        )
        lo, la = transform.inv(bx, by)
        lons[r0:r1] = lo
        lats[r0:r1] = la
    sc, sr = to_px(lons, lats)
    outside = (
        (sc < -0.5) | (sc > w_src - 0.5) | (sr < -0.5) | (sr > h_src - 0.5)
    )
    share = float(outside.mean())
    if strict_share is not None and share > strict_share:
        raise ReliefBuildError(
            "registration maps "
            f"{share:.1%} of the rect ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) "
            f"outside the source raster ({w_src}x{h_src} px) — "
            "check the rect and registration.json"
        )
    valid = ~outside
    src_r = np.clip(sr, 0, h_src - 1)
    src_c = np.clip(sc, 0, w_src - 1)
    if raster.ndim == 2:
        gray = map_coordinates(
            raster, [src_r, src_c], order=1, mode="nearest"
        )
    else:
        gray = np.empty(
            (h, w, raster.shape[2]), dtype=raster.dtype
        )
        for ch in range(raster.shape[2]):
            gray[..., ch] = map_coordinates(
                raster[..., ch], [src_r, src_c], order=1, mode="nearest"
            )
        gray = (
            0.299 * gray[..., 0] + 0.587 * gray[..., 1]
            + 0.114 * gray[..., 2]
        )
    return gray, valid, lats


def bake_playable(rect, ppu, transform, raster, to_px,
                  geometry, manifest):
    """LA array (H x W x 2): graded relief luma + LAND-polygon alpha."""
    gray, _valid, _lats = warp(rect, ppu, transform, raster, to_px)
    gray = grade(gray, ppu)

    land = node_polys(geometry, manifest, "LAND")
    inside = rasterize(land, rect, ppu) > 0
    # Where our coast overshoots the raster coast, the flat sea value
    # would show inside a province — fill those pixels with the
    # nearest land texel (the alpha mask still ends exactly at the
    # polygon; this only fixes the luma).
    land_r = raster_land_mask(gray, ppu)
    if not land_r.all():
        _dist, idx = distance_transform_edt(~land_r, return_indices=True)
        filled = gray[idx[0], idx[1]]
        gray = np.where(inside & ~land_r, filled, gray)

    alpha = poly_alpha(land, rect, ppu)
    return np.dstack([gray.astype(np.uint8), alpha.astype(np.uint8)])


def bake_inactive(rect, ppu, transform, raster, to_px,
                  geometry, manifest, brightness: float):
    """LA array: dimmed relief luma + world-land-minus-playable alpha."""
    gray, valid, lats = warp(rect, ppu, transform, raster, to_px,
                             strict_share=None)
    gray = grade(gray, ppu)

    land_r = raster_land_mask(gray, ppu) & valid
    # The extreme pole caps of the source raster (|lat| > ~88) are a
    # flat sea sliver disconnected from the ocean — it fails the
    # component-size test and would bake as a fake dark line along the
    # world edge. No real land exists there (northernmost land ~83.6N;
    # the Antarctic pole tip squashes to ~1 unit in this projection),
    # so force it to sea.
    land_r &= np.abs(lats) <= POLE_LAT_CUT
    playable_filled = (
        rasterize(node_polys(geometry, manifest), rect, ppu,
                  filled=True) > 0
    )
    erode_px = max(1, int(round(SUBTRACT_ERODE_UNITS * ppu)))
    playable_filled = binary_erosion(playable_filled, iterations=erode_px)
    alpha = land_r & ~playable_filled

    dim = np.clip(gray.astype(np.float32) * brightness, 0, 255)
    return np.dstack(
        [dim.astype(np.uint8), (alpha * 255).astype(np.uint8)]
    )


def encode_webp(la: np.ndarray, quality: int) -> bytes:
    img = Image.fromarray(la, "LA")
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def encode_png(la: np.ndarray) -> bytes:
    img = Image.fromarray(la, "LA")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True, compress_level=PNG_COMPRESS)
    return buf.getvalue()


def encode_best(la: np.ndarray, quality: int) -> tuple[bytes, str]:
    """The smaller of WebP and PNG (alpha is required — no JPEG)."""
    webp = encode_webp(la, quality)
    png = encode_png(la)
    return (webp, "webp") if len(webp) <= len(png) else (png, "png")


def native_ppu(raster, to_px, georef_k: float) -> float:
    """Px per base unit along the raster's x axis (plate carrée)."""
    c0, _ = to_px(np.array([0.0]), np.array([0.0]))
    c1, _ = to_px(np.array([1.0]), np.array([0.0]))
    px_per_deg = abs(float(c1[0] - c0[0]))
    return px_per_deg / georef_k


# ------------------------------------------------------------ coast check


def coast_report(transform, raster, to_px, geometry, manifest) -> float:
    """Max coastline shift at the five control points, in base units."""
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
        gray, _v, _l = warp(rect, CHECK_PPU, transform, raster, to_px)
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


def write_outputs(outputs: dict, source_name: str,
                  dry_run: bool) -> dict:
    """Write hashed files + the client manifest; delete stale relief.*"""
    manifest = {"source": source_name}
    for key, (body, ext, rect, ppu) in outputs.items():
        sha = hashlib.sha256(body).hexdigest()
        name = f"relief.{key}.{sha[:12]}.{ext}"
        manifest[key] = {
            "file": f"/assets/map/{name}",
            "rect": [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]],
            "px_per_unit": round(ppu, 2),
            "bytes": len(body),
            "sha256": sha,
        }
        if not dry_run:
            WEB_DIR.mkdir(parents=True, exist_ok=True)
            (WEB_DIR / name).write_bytes(body)
    if not dry_run:
        for stale in WEB_DIR.glob("relief.*"):
            if stale.name not in {
                v["file"].rsplit("/", 1)[1] for v in manifest.values() if isinstance(v, dict)
            }:
                stale.unlink()
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

    nat = native_ppu(raster, to_px, manifest["georef"]["k"])
    playable_ppu = min(MAX_PPU, nat)
    playable_rect = land_bbox(geometry, manifest, RECT_PAD_UNITS)
    inactive_rect = world_rect(transform, RECT_PAD_UNITS)
    inactive_ppu = WORLD_PPU

    def build(ppu_p: float, ppu_w: float):
        la_p = bake_playable(
            playable_rect, ppu_p, transform, raster, to_px,
            geometry, manifest,
        )
        la_w = bake_inactive(
            inactive_rect, ppu_w, transform, raster, to_px,
            geometry, manifest, relief_cfg["inactive_brightness"],
        )
        return (
            (*encode_best(la_p, WEBP_QUALITY), la_p.shape),
            (*encode_best(la_w, WEBP_QUALITY), la_w.shape),
        )

    # Budget ladder: drop the world image to 4 px/u first, then the
    # playable one toward MIN_PPU (TZ order).
    budget_plan = [
        (playable_ppu, WORLD_PPU),
        (playable_ppu, WORLD_PPU_MIN),
        (14.0, WORLD_PPU_MIN),
        (MIN_PPU, WORLD_PPU_MIN),
    ]
    chosen = None
    for pp, pw in budget_plan:
        if pp > nat + 0.05:
            continue
        (body_p, ext_p, shape_p), (body_w, ext_w, shape_w) = build(pp, pw)
        total = len(body_p) + len(body_w)
        print(
            f"  try playable {pp:.2f}px/u {shape_p[1]}x{shape_p[0]} "
            f"{len(body_p)}B {ext_p} | world {pw:.2f}px/u "
            f"{shape_w[1]}x{shape_w[0]} {len(body_w)}B {ext_w} "
            f"| total {total}B",
            flush=True,
        )
        chosen = (pp, pw, body_p, ext_p, body_w, ext_w, total)
        if total <= SIZE_BUDGET:
            break
    else:
        chosen = None
    if chosen is None or chosen[6] > SIZE_BUDGET:
        raise ReliefBuildError(
            f"budget {SIZE_BUDGET} B exceeded even at "
            f"{MIN_PPU}/{WORLD_PPU_MIN} px/u — report to the Project Owner"
        )

    pp, pw, body_p, ext_p, body_w, ext_w, total = chosen
    if pp < playable_ppu or pw < WORLD_PPU:
        print(
            f"WARNING: resolution lowered for the budget — "
            f"playable {pp:.2f}px/u, world {pw:.2f}px/u"
        )

    out = write_outputs(
        {
            "playable": (body_p, ext_p, playable_rect, pp),
            "inactive": (body_w, ext_w, inactive_rect, pw),
        },
        args.raster.name,
        args.dry_run,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
