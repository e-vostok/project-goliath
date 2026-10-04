"""§3.2 Baked relief texture over our base coordinates.

Reads ``registration.json`` (from register.py), warps the Natural Earth
II raster into base coordinates over ``view.frame`` (+margin), applies
the land-only colour fix (nearest-land fill so no foreign blue shows
inside our coastline), contrast/dim grading and writes WebP/JPEG into
``reference/`` (committed artifacts) + stats.

Run:  python -m tools.map_pipeline.relief_proto.bake
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import shapefile
from PIL import Image
from scipy.ndimage import (
    distance_transform_edt,
    gaussian_filter,
    map_coordinates,
)
from shapely.geometry import Polygon

from tools.map_pipeline.svg_source import (
    build_geometries,
    read_province_paths,
)
from tools.map_pipeline.svgpath import parse_path

from . import proto_common as pc
from .transform import Transform, load as load_transform

Image.MAX_IMAGE_PIXELS = None  # NE2 HR is ~131 Mpx, that is expected

# ------------------------------------------------------------- parameters
PX_PER_UNIT = [12, 16]
FRAME_MARGIN = 5.0        # base units of texture around view.frame
RELIEF_CONTRAST = 0.6     # keep this share of deviation from local mean
CONTRAST_SIGMA_UNITS = 0.9
DIM_SATURATION = 0.15     # excluded land: colour luma mix
DIM_BRIGHTNESS = 0.45     # excluded land: brightness multiplier
COAST_BLEED_PX = 12       # land colour pushed this far over raster coast
WEBP_Q = 85
JPEG_Q = 85
RASTER_ZIP = "NE2_HR_LC_SR_W_DR.zip"
RASTER_TIF = "NE2_HR_LC_SR_W_DR.tif"


# ------------------------------------------------------------ raster load


def ensure_raster() -> Path:
    tif = pc.DL_DIR / RASTER_TIF
    if not tif.exists():
        zpath = pc.DL_DIR / RASTER_ZIP
        print(f"extracting {zpath.name}…")
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if name.startswith("NE2_HR_LC_SR_W_DR"):
                    z.extract(name, pc.DL_DIR)
    return tif


def raster_georef(tif: Path):
    """Read the .tfw world file -> (lon/lat)->pixel affine."""
    tfw = tif.with_suffix(".tfw")
    a, d, b, e, c, f = [
        float(v) for v in tfw.read_text().split()[:6]
    ]
    # col = (lon - c)/a - 0.5 handled implicitly: c is centre of px(0,0)
    def to_px(lon, lat):
        # invert [a b; d e] (b/d are ~0 for plate carree)
        det = a * e - b * d
        col = (e * (lon - c) - b * (lat - f)) / det
        row = (-d * (lon - c) + a * (lat - f)) / det
        return col, row
    return to_px


def warp_raster(rect, ppu: float, transform: Transform,
                raster=None, to_px=None):
    """Resample the NE2 raster onto the base grid of ``rect`` at ``ppu``.

    Returns an RGB uint8 array (h x w x 3).
    """
    if raster is None:
        tif = ensure_raster()
        raster = np.asarray(Image.open(tif).convert("RGB"))
        to_px = raster_georef(tif)
    x0, y0, x1, y1 = rect
    w = int(round((x1 - x0) * ppu))
    h = int(round((y1 - y0) * ppu))
    cols = np.arange(w) + 0.5
    rows = np.arange(h) + 0.5
    bx = x0 + cols / ppu
    by = y0 + rows / ppu
    BX, BY = np.meshgrid(bx, by)
    lon, lat = transform.inv(BX, BY)
    sc, sr = to_px(lon, lat)
    out = np.empty((h, w, 3), dtype=np.uint8)
    for ch in range(3):
        out[..., ch] = map_coordinates(
            raster[..., ch], [sr, sc], order=1, mode="nearest"
        )
    return out


# ------------------------------------------------------------------ masks


def ne_land_polys(transform: Transform, margin_units: float = 6.0):
    """NE 10m land polygons warped to base coords (vector form)."""
    shp = pc.DL_DIR / "ne_10m_land" / "ne_10m_land.shp"
    if not shp.exists():
        with zipfile.ZipFile(pc.DL_DIR / "ne_10m_land.zip") as z:
            z.extractall(pc.DL_DIR / "ne_10m_land")
    reader = shapefile.Reader(str(shp))
    georef = pc.load_manifest()["georef"]
    cfg = pc.load_map_config()
    lon0, lon1, lat0, lat1 = pc.frame_lonlat(
        cfg["view"]["frame"], georef, margin=margin_units
    )
    from shapely.geometry import shape as shp_shape
    polys = []
    for shape in reader.iterShapes():
        bb = shape.bbox  # [xmin, ymin, xmax, ymax] = lon/lat
        if bb[2] < lon0 or bb[0] > lon1 or bb[3] < lat0 or bb[1] > lat1:
            continue
        geom = shp_shape(shape.__geo_interface__)
        geoms = (geom.geoms if geom.geom_type == "MultiPolygon"
                 else [geom])
        for g in geoms:
            gb = g.bounds  # lon/lat
            if gb[2] < lon0 or gb[0] > lon1 or gb[3] < lat0 \
                    or gb[1] > lat1:
                continue
            ex, ey = transform.fwd(
                *np.asarray(g.exterior.coords).T)
            inrings = []
            for hole in g.interiors:
                hx, hy = transform.fwd(*np.asarray(hole.coords).T)
                inrings.append(np.column_stack([hx, hy]))
            polys.append(Polygon(np.column_stack([ex, ey]), inrings))
    return polys


def ne_land_mask(rect, ppu, transform: Transform) -> np.ndarray:
    return pc.rasterize(ne_land_polys(transform), rect, ppu) > 0


def our_masks(rect, ppu, geometry, manifest, land_ne):
    """Playable land / excluded land / water-window masks (bool)."""
    kinds = pc.node_kinds(manifest)
    playable_polys = []
    for key, d in geometry["paths"].items():
        if kinds.get(key) == "LAND":
            playable_polys.extend(parse_path(d))
    playable = pc.rasterize(playable_polys, rect, ppu) > 0
    outside = pc.rasterize(parse_path(geometry["outside"]), rect, ppu) > 0

    # excluded source provinces (land that never became a node):
    # every source province absent from boundary.include is out of play
    boundary = pc.load_boundary()
    included = set(boundary.get("include", []))
    src = read_province_paths(pc.DATA_DIR / "source" / "map.svg")
    excl_names = [n for n in src if n not in included]
    excl_polys = []
    if excl_names:
        from tools.map_pipeline.pipeline_config_schema import (
            load_pipeline_config,
        )
        cfgp = load_pipeline_config().clean
        geoms = build_geometries(
            {n: src[n] for n in excl_names}, cfgp)
        excl_polys = [p for parts in geoms.values() for p in parts]
    excluded_src = (
        pc.rasterize(excl_polys, rect, ppu) > 0 if excl_polys
        else np.zeros_like(playable)
    )
    # excluded land = real land (NE) covered by outside/excluded-src
    excluded = land_ne & (outside | excluded_src) & ~playable
    water_windows = pc.rasterize(
        parse_path(geometry["sea_water"]), rect, ppu) > 0
    return playable, excluded, water_windows


# ------------------------------------------------------------------ grade


def dim(rgb_f: np.ndarray) -> np.ndarray:
    luma = (0.299 * rgb_f[..., 0] + 0.587 * rgb_f[..., 1]
            + 0.114 * rgb_f[..., 2])[..., None]
    return np.clip(
        (luma + (rgb_f - luma) * DIM_SATURATION) * DIM_BRIGHTNESS,
        0, 255)


def bake_one(ppu, rect, raster, to_px, transform, geometry, manifest,
             land_ne, masks):
    x0, y0, x1, y1 = rect
    t0 = time.time()
    rgb = warp_raster(rect, ppu, transform, raster, to_px)
    print(f"    warp {rgb.shape[1]}x{rgb.shape[0]} "
          f"({time.time() - t0:.1f}s)")

    playable, excluded, _ = masks
    our_land = playable | excluded

    # nearest-land fill: every pixel that is not NE-land takes the colour
    # of the closest NE-land pixel (only used where our mask says land,
    # plus coast_bleed_px outward for sub-mask anti-fringe safety)
    t0 = time.time()
    dist, idx = distance_transform_edt(~land_ne, return_indices=True)
    need_fill = (~land_ne) & (our_land | (dist <= COAST_BLEED_PX))
    filled = rgb.reshape(-1, 3)[
        idx[0].ravel() * rgb.shape[1] + idx[1].ravel()
    ].reshape(rgb.shape)
    rgb_f = np.where(need_fill[..., None], filled, rgb).astype(np.float32)
    print(f"    coast bleed ({time.time() - t0:.1f}s)")

    t0 = time.time()
    mean = np.stack(
        [gaussian_filter(rgb_f[..., c], CONTRAST_SIGMA_UNITS * ppu)
         for c in range(3)], axis=-1)
    graded = np.clip(mean + (rgb_f - mean) * RELIEF_CONTRAST, 0, 255)
    dimmed = dim(graded)
    out = np.where(excluded[..., None], dimmed, graded)
    alpha = np.where(our_land, 255, 0).astype(np.uint8)
    rgba_dim = np.dstack([np.clip(out, 0, 255).astype(np.uint8), alpha])
    rgba_raw = np.dstack([np.clip(graded, 0, 255).astype(np.uint8),
                          alpha])
    print(f"    grading ({time.time() - t0:.1f}s)")
    return rgba_raw, rgba_dim


def main(argv=None) -> int:
    t_all = time.time()
    transform = load_transform()
    geometry = pc.load_geometry()
    manifest = pc.load_manifest()
    frame = pc.load_map_config()["view"]["frame"]
    rect = (frame["x"] - FRAME_MARGIN, frame["y"] - FRAME_MARGIN,
            frame["x"] + frame["width"] + FRAME_MARGIN,
            frame["y"] + frame["height"] + FRAME_MARGIN)
    tif = ensure_raster()
    to_px = raster_georef(tif)
    print("loading raster…")
    t0 = time.time()
    raster = np.asarray(Image.open(tif).convert("RGB"))
    print(f"  {raster.shape[1]}x{raster.shape[0]} "
          f"({time.time() - t0:.1f}s)")

    report = {"rect_units": rect, "results": {}}
    for ppu in PX_PER_UNIT:
        print(f"ppu={ppu}")
        t0 = time.time()
        land_ne = ne_land_mask(rect, ppu, transform)
        masks = our_masks(rect, ppu, geometry, manifest, land_ne)
        rgba_raw, rgba_dim = bake_one(ppu, rect, raster, to_px, transform,
                                      geometry, manifest, land_ne, masks)
        sha = {}
        for tag, rgba in (("", rgba_raw), ("_dim", rgba_dim)):
            img = Image.fromarray(rgba, "RGBA")
            webp = pc.REF_DIR / f"relief_texture_{ppu}{tag}.webp"
            img.save(webp, "WEBP", quality=WEBP_Q, method=4)
            sha[tag or "_raw"] = hashlib.sha256(
                webp.read_bytes()).hexdigest()
        jpg = pc.OUT_DIR / f"relief_texture_{ppu}.jpg"
        bg = np.array([30, 53, 71], dtype=np.uint8)  # sea colour
        flat = np.where(rgba_dim[..., 3:4] > 0, rgba_dim[..., :3], bg)
        Image.fromarray(flat).save(jpg, "JPEG", quality=JPEG_Q)
        w, h = img.size
        report["results"][str(ppu)] = {
            "webp_bytes_raw": (pc.REF_DIR /
                               f"relief_texture_{ppu}.webp").stat().st_size,
            "webp_bytes_dim": (pc.REF_DIR /
                               f"relief_texture_{ppu}_dim.webp"
                               ).stat().st_size,
            "jpeg_bytes": jpg.stat().st_size,
            "decoded_mb": round(w * h * 4 / 1e6, 1),
            "size": [w, h],
            "webp_sha256": sha,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"    {report['results'][str(ppu)]}")

    # detail at max zoom: screen px per unit vs texture px per unit
    cfg = pc.load_map_config()
    s_min = 1080.0 / frame["height"]
    s_max = s_min * cfg["view"]["zoom_max"]
    # source raster is 21600x1080/360deg plate carree = 60 px/deg;
    # 1 base unit = 1/k deg lon -> ~60/k px per unit at lon scale
    src_px_per_unit = 60.0 / manifest["georef"]["k"]
    report["max_zoom"] = {
        "screen_px_per_unit": round(s_max, 2),
        "texel_per_screen_px_12": round(12.0 / s_max, 3),
        "texel_per_screen_px_16": round(16.0 / s_max, 3),
        "src_px_per_unit_lon": round(src_px_per_unit, 2),
        "note": ("screen px/unit at zoom_max vs texel/unit: "
                 "values <1 mean the texture is stretched on screen"),
    }
    (pc.OUT_DIR / "bake_stats.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"total {time.time() - t_all:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
