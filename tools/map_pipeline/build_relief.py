"""map2_17: bake the two relief rasters for the 01_map client.

Input : a Natural Earth raster («Gray Earth with Shaded Relief and
        Hypsography», plate carrée) as the downloaded .zip or the .tif
        inside it, plus the ``ne_10m_land`` and ``ne_10m_lakes`` vector
        zips — all fetched manually, NEVER committed.
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
   Alpha = the land mask rasterised from the ``ne_10m_land`` polygons
   MINUS ``ne_10m_lakes`` (vector coverage, NE_SS x supersampling —
   a smooth 8-bit edge, never a raster threshold) TIMES the keep
   mask: 1 outside the PLAYABLE FRAME, the ``outside`` (excluded)
   polygons inside it. The frame is the union of ALL node polygons
   (LAND and SEA) with ALL union holes filled, grown by
   ``FRAME_GROW_UNITS`` — so every gulf, fjord, lake, bay and sliver
   between provinces inside the frame is alpha 0 (plain sea colour),
   while the excluded zone stays inactive land.

Run (from repo root):
    python -m tools.map_pipeline.build_relief --raster <GRAY_HR_SR.zip>
        --ne-land <ne_10m_land.zip> --ne-lakes <ne_10m_lakes.zip>
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
    binary_dilation,
    binary_erosion,
    binary_fill_holes,
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
RECT_PAD_UNITS = 1.0        # output rect padding around tight bounds
AA_SCALE = 2                # supersampling for polygon-alpha edges
FRAME_GROW_UNITS = 0.15     # union growth closing inter-polygon slivers
FRAME_WORK_SCALE = 2        # internal oversampling of the frame mask
NE_SS = 4                   # supersampling for the vector land coverage
COVERAGE_BAND = 64          # output rows per rasterisation band

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
    x0, y0, x1, y1 = rect
    out_w = max(1, int(round((x1 - x0) * ppu)))
    out_h = max(1, int(round((y1 - y0) * ppu)))
    hi = rasterize(polys, rect, ppu * AA_SCALE)
    img = Image.fromarray(hi, "L").resize((out_w, out_h), Image.BOX)
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


# ------------------------------------------ Natural Earth vector land mask


def load_ne_rings(zip_path: Path, transform: Transform):
    """NE shapefile zip -> [(exterior_xy, [hole_xy, ...])] in base units.

    Every ring vertex is pushed through the fitted registration, so the
    vector coast lands exactly where the warped raster lands.
    """
    import shapefile  # pyshp — reads .shp straight from memory
    from shapely.geometry import box as shp_box
    from shapely.geometry import shape as shp_shape

    sphere = shp_box(-180.0, -90.0, 180.0, 90.0)
    polys = []
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()

        def member(suffix: str) -> str:
            return next(
                n for n in names if n.lower().endswith(suffix)
            )

        reader = shapefile.Reader(
            shp=io.BytesIO(z.read(member(".shp"))),
            shx=io.BytesIO(z.read(member(".shx"))),
            dbf=io.BytesIO(z.read(member(".dbf"))),
        )
        for sr in reader.iterShapes():
            # Clipping to the sphere splits antimeridian-crossing rings
            # (Russia's Far East, Antarctica) into per-side parts; the
            # transform cannot wrap a 360-degree jump.
            geom = shp_shape(sr.__geo_interface__).intersection(sphere)
            if geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                parts = [geom]
            elif geom.geom_type == "MultiPolygon":
                parts = list(geom.geoms)
            else:  # GeometryCollection — keep its polygons only
                parts = [
                    g for g in geom.geoms
                    if g.geom_type == "Polygon"
                ]
            for p in parts:
                ext = np.asarray(p.exterior.coords, dtype=float)
                bx, by = transform.fwd(ext[:, 0], ext[:, 1])
                ext_u = np.column_stack([bx, by])
                ints = []
                for ring in p.interiors:
                    ixy = np.asarray(ring.coords, dtype=float)
                    ibx, iby = transform.fwd(ixy[:, 0], ixy[:, 1])
                    ints.append(np.column_stack([ibx, iby]))
                polys.append((ext_u, ints))
    return polys


def coverage_aa(fill_polys, erase_polys, rect, ppu: float,
                ss: int = NE_SS) -> np.ndarray:
    """8-bit land coverage over ``rect`` at ``ppu``, ``ss``x supersampled.

    Draws ``fill_polys`` (exteriors 255, interiors 0) then ``erase_polys``
    (exteriors 0 — the lakes carve land, their islands redraw at 255)
    in row bands so the 4x canvas never lives whole in memory.
    """
    x0, y0, x1, y1 = rect
    w = max(1, int(round((x1 - x0) * ppu)))
    h = max(1, int(round((y1 - y0) * ppu)))

    def items(polys):
        out = []
        for ext, ints in polys:
            ys = [ext[:, 1]] + [i[:, 1] for i in ints]
            out.append((min(y.min() for y in ys),
                        max(y.max() for y in ys), ext, ints))
        return out

    fill_items = items(fill_polys)
    erase_items = items(erase_polys)
    out = np.zeros((h, w), dtype=np.uint8)
    for r0 in range(0, h, COVERAGE_BAND):
        r1 = min(h, r0 + COVERAGE_BAND)
        y_lo = y0 + r0 / ppu
        y_hi = y0 + r1 / ppu
        img = Image.new("L", (w * ss, (r1 - r0) * ss), 0)
        draw = ImageDraw.Draw(img)

        def to_px(coords):
            return [
                ((x - x0) * ppu * ss, (y - y_lo) * ppu * ss)
                for x, y in coords
            ]

        for lo, hi, ext, ints in fill_items:
            if hi < y_lo or lo > y_hi:
                continue
            draw.polygon(to_px(ext), fill=255)
            for hole in ints:
                draw.polygon(to_px(hole), fill=0)
        for lo, hi, ext, ints in erase_items:
            if hi < y_lo or lo > y_hi:
                continue
            draw.polygon(to_px(ext), fill=0)
            for hole in ints:
                draw.polygon(to_px(hole), fill=255)
        band = np.asarray(img)
        band = (
            band.reshape(r1 - r0, ss, w * ss).mean(axis=1)
            .reshape(r1 - r0, w, ss).mean(axis=2)
        )
        out[r0:r1] = band.astype(np.uint8)
    return out


def playable_frame(rect, ppu: float, geometry, manifest) -> np.ndarray:
    """The PLAYABLE FRAME as a bool grid over ``rect`` at ``ppu``.

    Union of ALL node polygons (LAND and SEA) with the holes of the
    UNION filled — so gulfs and lakes enclosed by several provinces are
    inside the frame — then grown by ``FRAME_GROW_UNITS`` to close the
    slivers between separately simplified contours (the Vänern ring).
    Built at ``FRAME_WORK_SCALE``x so sub-pixel cracks cannot leak.
    """
    x0, y0, x1, y1 = rect
    out_w = max(1, int(round((x1 - x0) * ppu)))
    out_h = max(1, int(round((y1 - y0) * ppu)))
    ws = FRAME_WORK_SCALE
    mask = (
        rasterize(
            node_polys(geometry, manifest), rect, ppu * ws, filled=True
        )
        > 0
    )
    mask = binary_fill_holes(mask)
    grow = max(1, int(round(FRAME_GROW_UNITS * ppu * ws)))
    mask = binary_dilation(mask, iterations=grow)
    small = np.asarray(
        Image.fromarray(mask).resize((out_w, out_h), Image.BOX)
    )
    return small > 0


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
                  geometry, manifest, ne_land, ne_lakes,
                  brightness: float):
    """LA array: dimmed relief luma + (vector land & keep-mask) alpha.

    ``keep`` is 1 outside the PLAYABLE FRAME and the ``outside``
    excluded-zone coverage inside it — everything else inside the
    frame (gulfs, fjords, lakes, slivers, SEA nodes) is alpha 0.
    """
    gray, _valid, _lats = warp(rect, ppu, transform, raster, to_px,
                               strict_share=None)
    gray = grade(gray, ppu)

    land = (
        coverage_aa(ne_land, ne_lakes, rect, ppu).astype(np.float32)
        / 255.0
    )
    frame = playable_frame(rect, ppu, geometry, manifest)
    outside = (
        poly_alpha(list(parse_path(geometry["outside"])), rect, ppu)
        .astype(np.float32) / 255.0
    )
    if frame.shape != land.shape or outside.shape != land.shape:
        raise ReliefBuildError(
            f"mask shape mismatch: land {land.shape}, frame "
            f"{frame.shape}, outside {outside.shape}"
        )
    keep = np.maximum(1.0 - frame.astype(np.float32), outside)
    alpha = np.rint(land * keep * 255).astype(np.uint8)
    # Inside the frame only genuinely excluded land may stay dark —
    # sub-half coverage at the excluded coast is just the raster and
    # the geometry disagreeing by a sliver; painting it leaves phantom
    # specks in water holes, so cut it. The visible outside edge keeps
    # its smooth coverage at >=50%.
    alpha[frame & (outside < 0.5)] = 0

    dim = np.clip(gray.astype(np.float32) * brightness, 0, 255)
    return np.dstack([dim.astype(np.uint8), alpha])


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
    parser.add_argument("--ne-land", type=Path, required=True,
                        help="ne_10m_land.zip (never committed)")
    parser.add_argument("--ne-lakes", type=Path, required=True,
                        help="ne_10m_lakes.zip (never committed)")
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
    print(f"loading {args.ne_land.name} + {args.ne_lakes.name}…",
          flush=True)
    ne_land = load_ne_rings(args.ne_land, transform)
    ne_lakes = load_ne_rings(args.ne_lakes, transform)
    print(f"  land {len(ne_land)} polys, lakes {len(ne_lakes)} polys",
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
            geometry, manifest, ne_land, ne_lakes,
            relief_cfg["inactive_brightness"],
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
