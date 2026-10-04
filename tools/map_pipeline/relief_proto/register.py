"""§3.1 Registration: fit lon/lat -> base (x, y) against our coastline.

"Our coastline" = the edge of the *rendered* land mask: every source
province polygon rasterised at COAST_PPU px per unit (hairline slivers
between imperfectly tiling SVG provinces vanish — they are not coast).
Each candidate projection (pyproj) gets a free affine fitted by ICP +
bounded least-squares on the coast distance field.  If the best model's
p95 coastline error exceeds P95_SPLINE units, a thin-plate-spline
correction over auto-matched GCPs is fitted and the residual re-reported.

Outputs:
- ``relief_proto/registration.json`` — chosen model + params + GCPs +
  raster id/sha256 + the full fit table.
- ``reference/relief_coast_check.png`` + ``relief_coast_crop_*.png``.

Run:  python -m tools.map_pipeline.relief_proto.register
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pyproj
import shapefile  # pyshp
from PIL import Image, ImageDraw
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import (
    binary_closing,
    binary_erosion,
    distance_transform_edt,
    map_coordinates,
)
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from tools.map_pipeline.pipeline_config_schema import load_pipeline_config
from tools.map_pipeline.svg_source import (
    build_geometries,
    read_province_paths,
)

from . import proto_common as pc
from .transform import Transform

# ------------------------------------------------------------- parameters
COAST_PPU = 24.0          # mask resolution for coast extraction, px/unit
DT_PPU = 12.0             # distance-field resolution (subsampled x2)
COAST_RECT_MARGIN = 18.0  # extra base units around the view frame
NE_MARGIN_DEG = 8.0       # lon/lat margin for NE coast point selection
OPT_POINTS = 7000         # subsampled NE points used inside the optimiser
ICP_ITERS = 10
ICP_CAP = 2.0             # pairs farther than this are dropped, units
LSQ_CAP = 1.5             # residual cap inside least_squares, units
P95_SPLINE = 0.3          # threshold that triggers the TPS refinement
GCP_MAX = 250
GCP_MAX_DIST = 0.5        # match tolerance for GCP pairs, units
DISAGREE_UNITS = 0.3      # coast vs relief disagreement marker, units
OVERVIEW_PPU = 6.0
CROP_SCALE = 4.0          # crops rendered at OVERVIEW_PPU * CROP_SCALE
CROP_SIZE_UNITS = (28.0, 17.0)

# Crop centres in lon/lat (converted via the fitted transform).
CROPS = {
    "lappmark_norway": (16.0, 66.5),
    "alexandria_nile": (30.5, 31.3),
    "alps_balkans": (12.0, 45.5),
    "black_sea_crimea": (34.5, 45.3),
    "cyclades": (25.3, 37.2),
    "britain_ireland": (-3.0, 54.5),
}

# Candidate models; ``shape`` names the free pyproj params refined jointly
# with the affine.  Anything a free affine absorbs (lon_0 of cylindric and
# conic models, lat_0 of conics, global scale/offset) stays fixed.
CANDIDATES = [
    ("equirectangular", {"proj": "eqc"}, []),
    ("mercator", {"proj": "merc"}, []),
    ("miller", {"proj": "mill"}, []),
    ("gall_stereographic", {"proj": "gall"}, []),
    ("lambert_conformal_conic",
     {"proj": "lcc", "lat_0": 50.0, "lon_0": 20.0}, ["lat_1", "lat_2"]),
    ("albers",
     {"proj": "aea", "lat_0": 50.0, "lon_0": 20.0}, ["lat_1", "lat_2"]),
    ("lambert_azimuthal_eq_area",
     {"proj": "laea"}, ["lat_0", "lon_0"]),
    ("azimuthal_equidistant",
     {"proj": "aeqd"}, ["lat_0", "lon_0"]),
]
SHAPE_INIT = {
    "lat_1": 36.0, "lat_2": 62.0,   # sane Europe parallels
    "lat_0": 50.0, "lon_0": 20.0,
}
SHAPE_BOUNDS = {
    "lat_1": (5.0, 85.0), "lat_2": (5.0, 85.0),
    "lat_0": (-89.0, 89.0), "lon_0": (-180.0, 180.0),
}


# ------------------------------------------------------------- input data


def source_polys():
    cfg = load_pipeline_config().clean
    paths = read_province_paths(pc.DATA_DIR / "source" / "map.svg")
    geoms = build_geometries(paths, cfg)
    return [p for parts in geoms.values() for p in parts]


def our_land_mask(polys, rect, ppu):
    """Rendered land mask: all source provinces, cracks sealed."""
    mask = pc.rasterize(polys, rect, ppu) > 0
    # seal hairline slivers between non-tiling provinces (<= ~0.12 u)
    mask = binary_closing(mask, iterations=max(1, round(0.12 * ppu)))
    return mask


def mask_edge_pts(mask, rect, ppu):
    """Edge pixels of the land mask as base-coord point array."""
    edge = mask & ~binary_erosion(mask)
    rows, cols = np.nonzero(edge)
    x0, y0 = rect[0], rect[1]
    return np.column_stack(
        [x0 + (cols + 0.5) / ppu, y0 + (rows + 0.5) / ppu])


def ne_coast_points(shp_path: Path, lonlat_bbox):
    """Coastline vertices of ne_10m_land rings intersecting the bbox."""
    lon0, lon1, lat0, lat1 = lonlat_bbox
    pts = []
    reader = shapefile.Reader(str(shp_path))
    for shape in reader.iterShapes():
        ring_idx = list(shape.parts) + [len(shape.points)]
        for a, b in zip(ring_idx[:-1], ring_idx[1:]):
            ring = np.asarray(shape.points[a:b], dtype=float)
            keep = (
                (ring[:, 0] >= lon0) & (ring[:, 0] <= lon1)
                & (ring[:, 1] >= lat0) & (ring[:, 1] <= lat1)
            )
            if keep.any():
                pts.append(ring[keep])
    return np.vstack(pts)


# --------------------------------------------------------------- fitting


def build_proj(base_kw: dict, shape_names, shape_vals):
    kw = dict(base_kw)
    for n, v in zip(shape_names, shape_vals):
        kw[n] = float(v)
    kw.setdefault("datum", "WGS84")
    return pyproj.Proj(**kw)


def init_affine(proj, lonlat_bbox, georef):
    """LSQ affine proj-plane -> base, initialised on the spec georef."""
    lon0, lon1, lat0, lat1 = lonlat_bbox
    lons = np.linspace(lon0, lon1, 40)
    lats = np.linspace(lat0, lat1, 40)
    LON, LAT = np.meshgrid(lons, lats)
    u, v = proj(LON.ravel(), LAT.ravel())
    bx, by = pc.lonlat_to_base(LON.ravel(), LAT.ravel(), georef)
    A = np.column_stack([u, v, np.ones_like(u)])
    cx, *_ = np.linalg.lstsq(A, bx, rcond=None)
    cy, *_ = np.linalg.lstsq(A, by, rcond=None)
    return np.array([cx[:2], cy[:2]]), np.array([cx[2], cy[2]])


def apply_affine(M, t, u, v):
    return (M[0, 0] * u + M[0, 1] * v + t[0],
            M[1, 0] * u + M[1, 1] * v + t[1])


def icp_refine(proj, M, t, ne_ll, coast_tree):
    """Iterate: match transformed NE pts to our coast, refit affine."""
    u, v = proj(ne_ll[:, 0], ne_ll[:, 1])
    for _ in range(ICP_ITERS):
        bx, by = apply_affine(M, t, u, v)
        dist, idx = coast_tree.query(np.column_stack([bx, by]))
        keep = dist < ICP_CAP
        if keep.sum() < 50:
            break
        w = 1.0 / (1.0 + dist[keep] ** 2)
        A = np.column_stack(
            [u[keep], v[keep], np.ones(int(keep.sum()))]
        ) * np.sqrt(w)[:, None]
        B = coast_tree.data[idx[keep]] * np.sqrt(w)[:, None]
        cx, *_ = np.linalg.lstsq(A, B[:, 0], rcond=None)
        cy, *_ = np.linalg.lstsq(A, B[:, 1], rcond=None)
        M = np.array([cx[:2], cy[:2]])
        t = np.array([cx[2], cy[2]])
    return M, t


def fit_candidate(name, kw, shape_names, ne_opt,
                  dt, dt_origin, dt_ppu, coast_tree, georef, lonlat_bbox):
    """Fit one projection+affine; returns model dict.

    The optimiser works in a normalised proj plane ``uN = (u-u_ref)/S``
    so all fitted parameters are O(1); the stored affine is folded back
    to raw proj units afterwards.
    """
    S = 1e6
    s0 = [SHAPE_INIT[n] for n in shape_names]
    proj = build_proj(kw, shape_names, s0)
    M, t = init_affine(proj, lonlat_bbox, georef)
    M, t = icp_refine(proj, M, t, ne_opt, coast_tree)

    def residuals(theta):
        # theta = [shape params..., m00, m01, m10, m11, tx, ty] where the
        # affine acts on normalised proj coords with FIXED reference
        # (recomputed below for the current shape params via anchor pts)
        sv = theta[: len(shape_names)]
        m = theta[len(shape_names):]
        pr = build_proj(kw, shape_names, sv)
        u, v = pr(ne_opt[:, 0], ne_opt[:, 1])
        u_ref, v_ref = pr(20.0, 50.0)
        uN = (u - u_ref) / S
        vN = (v - v_ref) / S
        bx = m[0] * uN + m[1] * vN + m[4]
        by = m[2] * uN + m[3] * vN + m[5]
        px_i = (bx - dt_origin[0]) * dt_ppu
        py_i = (by - dt_origin[1]) * dt_ppu
        d = map_coordinates(dt, [py_i, px_i], order=1, mode="constant",
                            cval=LSQ_CAP) / dt_ppu
        return np.minimum(d, LSQ_CAP)

    # convert the ICP affine into normalised-affine parameters
    u_ref0, v_ref0 = proj(20.0, 50.0)
    Mn = M * S
    tn = np.array([t[0] + (M[0, 0] * u_ref0 + M[0, 1] * v_ref0),
                   t[1] + (M[1, 0] * u_ref0 + M[1, 1] * v_ref0)])
    theta0 = np.concatenate([s0, [Mn[0, 0], Mn[0, 1], Mn[1, 0], Mn[1, 1],
                                  tn[0], tn[1]]])
    lb = [SHAPE_BOUNDS[n][0] for n in shape_names] + [-np.inf] * 6
    ub = [SHAPE_BOUNDS[n][1] for n in shape_names] + [np.inf] * 6
    sol = least_squares(residuals, theta0, bounds=(lb, ub),
                        loss="soft_l1", f_scale=0.4)
    theta = sol.x
    sv = theta[: len(shape_names)]
    m = theta[len(shape_names):]
    proj_kw = {**kw, **dict(zip(shape_names, sv))}
    # fold the normalisation back into raw-proj affine:
    # bx = m0*(u-u_ref)/S + m1*(v-v_ref)/S + tx
    pr = build_proj(kw, shape_names, sv)
    u_ref, v_ref = pr(20.0, 50.0)
    M_raw = np.array([[m[0] / S, m[1] / S], [m[2] / S, m[3] / S]])
    t_raw = np.array([
        m[4] - M_raw[0, 0] * u_ref - M_raw[0, 1] * v_ref,
        m[5] - M_raw[1, 0] * u_ref - M_raw[1, 1] * v_ref])
    return {"name": name, "proj_kw": proj_kw,
            "affine": M_raw.tolist(), "shift": t_raw.tolist()}


def stats_of(transform, ne_ll, coast_tree, kmu, rect):
    """Coast stats over NE points landing inside the coast rect."""
    bx, by = transform.fwd(ne_ll[:, 0], ne_ll[:, 1])
    inside = ((bx >= rect[0]) & (bx <= rect[2])
              & (by >= rect[1]) & (by <= rect[3]))
    d, _ = coast_tree.query(np.column_stack([bx[inside], by[inside]]))
    matched = d[d < ICP_CAP]
    rms_m = float(np.sqrt(np.mean(matched ** 2))) if len(matched) \
        else float("nan")
    return {
        "rms": float(np.sqrt(np.mean(d ** 2))),
        "p95": float(np.percentile(d, 95)),
        "max": float(d.max()),
        "rms_km": float(np.sqrt(np.mean(d ** 2)) * kmu),
        "p95_km": float(np.percentile(d, 95) * kmu),
        "max_km": float(d.max() * kmu),
        "matched_share": float(len(matched) / len(d)),
        "rms_matched": rms_m,
        "rms_matched_km": rms_m * kmu,
        "n_points": int(len(d)),
        "n_in_rect": int(inside.sum()),
    }


# ------------------------------------------------------------------- main


def main(argv=None) -> int:
    t_start = time.time()
    manifest = pc.load_manifest()
    georef = manifest["georef"]
    cfg = pc.load_map_config()
    frame = cfg["view"]["frame"]
    fb = pc.frame_lonlat(frame, georef, margin=0.0)
    lonlat_bbox = (fb[0] - NE_MARGIN_DEG, fb[1] + NE_MARGIN_DEG,
                   fb[2] - NE_MARGIN_DEG, fb[3] + NE_MARGIN_DEG)
    print("lonlat bbox:", [round(v, 2) for v in lonlat_bbox])

    # our coastline: edge of the rendered source-land mask
    x0 = frame["x"] - COAST_RECT_MARGIN
    y0 = frame["y"] - COAST_RECT_MARGIN
    rect = (x0, y0,
            frame["x"] + frame["width"] + COAST_RECT_MARGIN,
            frame["y"] + frame["height"] + COAST_RECT_MARGIN)
    print("rasterising source land @%.0f px/unit…" % COAST_PPU)
    t0 = time.time()
    polys = source_polys()
    print(f"  source polygons: {len(polys)}")
    land_mask = our_land_mask(polys, rect, COAST_PPU)
    print(f"  mask done ({time.time() - t0:.0f}s)")
    our_pts = mask_edge_pts(land_mask, rect, COAST_PPU)
    print(f"  our coast edge points: {len(our_pts)}")
    coast_tree = cKDTree(our_pts)

    # distance field: edt at full resolution, then subsample the FIELD
    # (decimating a 1px edge mask would alias it away)
    dsub = max(1, round(COAST_PPU / DT_PPU))
    edge = land_mask & ~binary_erosion(land_mask)
    dt = distance_transform_edt(~edge).astype(np.float32)[::dsub, ::dsub]
    dt = dt / dsub  # back to DT_PPU pixel units

    shp = pc.DL_DIR / "ne_10m_land" / "ne_10m_land.shp"
    if not shp.exists():
        import zipfile
        with zipfile.ZipFile(pc.DL_DIR / "ne_10m_land.zip") as z:
            z.extractall(pc.DL_DIR / "ne_10m_land")
    print("reading NE land coastline…")
    ne_ll = ne_coast_points(shp, lonlat_bbox)
    print(f"  NE coast points in extent: {len(ne_ll)}")
    rng = np.random.default_rng(7)
    idx = rng.choice(len(ne_ll), size=min(OPT_POINTS, len(ne_ll)),
                     replace=False)
    ne_opt = ne_ll[np.sort(idx)]

    kmu = pc.km_per_unit(georef)
    print(f"  km per base unit @50N: {kmu:.2f}")

    table = {}
    models = {}
    for name, kw, shapes in CANDIDATES:
        t0 = time.time()
        m = fit_candidate(name, kw, shapes, ne_opt,
                          dt, (x0, y0), DT_PPU, coast_tree,
                          georef, lonlat_bbox)
        tr = Transform(m["proj_kw"], m["affine"], m["shift"])
        st = stats_of(tr, ne_ll, coast_tree, kmu, rect)
        models[name] = (m, tr)
        table[name] = {
            "proj_kw": {k: round(float(v), 5) if isinstance(v, float)
                        else v for k, v in m["proj_kw"].items()},
            **st,
        }
        print(f"  {name:28s} rms={st['rms']:.3f} p95={st['p95']:.3f} "
              f"max={st['max']:.2f} u ({time.time() - t0:.0f}s)")

    best_name = min(table, key=lambda n: table[n]["p95"])
    best_m, _ = models[best_name]
    print(f"best: {best_name} p95={table[best_name]['p95']:.3f}")

    # ------------------------------------------------ optional TPS step
    gcp_list = []
    resid_after = None
    if table[best_name]["p95"] > P95_SPLINE:
        print("p95 > 0.3 units — fitting TPS correction…")
        tr0 = models[best_name][1]
        bx, by = tr0.fwd(ne_ll[:, 0], ne_ll[:, 1])
        inside = ((bx >= rect[0]) & (bx <= rect[2])
                  & (by >= rect[1]) & (by <= rect[3]))
        d, ii = coast_tree.query(np.column_stack([bx, by]))
        ok = (d < GCP_MAX_DIST) & inside
        pred = np.column_stack([bx[ok], by[ok]])
        truth = our_pts[ii[ok]]
        cell = np.floor(pred / 2.0).astype(int)
        seen = {}
        chosen = []
        for i in rng.permutation(len(pred)):
            key = tuple(cell[i])
            if seen.get(key, 0) < 3:
                seen[key] = seen.get(key, 0) + 1
                chosen.append(i)
            if len(chosen) >= GCP_MAX:
                break
        if len(chosen) < 10:
            print("  too few GCP matches — skipping TPS")
            transform = Transform(best_m["proj_kw"], best_m["affine"],
                                  best_m["shift"])
        else:
            chosen = np.asarray(chosen)
            gcp_pred = pred[chosen]
            gcp_true = truth[chosen]
            gcp_list = [
                {"base_est": [round(float(a), 4) for a in p],
                 "base_true": [round(float(a), 4) for a in q]}
                for p, q in zip(gcp_pred, gcp_true)
            ]
            transform = Transform(best_m["proj_kw"], best_m["affine"],
                                  best_m["shift"], gcp_list)
            st2 = stats_of(transform, ne_ll, coast_tree, kmu, rect)
            resid_after = {k: st2[k] for k in
                           ("rms", "p95", "max", "rms_km", "p95_km",
                            "max_km", "rms_matched", "rms_matched_km")}
            print(f"  TPS residual rms={st2['rms']:.3f} "
                  f"p95={st2['p95']:.3f} max={st2['max']:.2f}")
    else:
        print("p95 <= 0.3 units — no spline correction needed")
        transform = Transform(best_m["proj_kw"], best_m["affine"],
                              best_m["shift"])

    # --------------------------------------------------- registration doc
    raster_zip = pc.DL_DIR / "NE2_HR_LC_SR_W_DR.zip"
    doc = {
        "model": best_name,
        "proj_kw": {k: (round(float(v), 6) if isinstance(v, float) else v)
                    for k, v in best_m["proj_kw"].items()},
        "affine": [[round(float(v), 9) for v in row]
                   for row in best_m["affine"]],
        "shift": [round(float(v), 6) for v in best_m["shift"]],
        "mapping": ("base = affine(proj(lon_deg, lat_deg)) [+ TPS in base "
                    "units]; proj via pyproj.Proj(**proj_kw); "
                    "inverse for raster warping: lonlat = "
                    "proj^-1(affine^-1(base - TPS(base))), fixed-point"),
        "tps": (
            {"kernel": "thin_plate_spline", "degree": 1,
             "note": "correction in base units: base += TPS(base); "
                     "rebuilt from gcps (base_est -> base_true)"}
            if gcp_list else None
        ),
        "gcps": gcp_list,
        "source_raster": {
            "file": raster_zip.name,
            "sha256": hashlib.sha256(raster_zip.read_bytes()).hexdigest(),
        },
        "km_per_unit_at_50N": round(kmu, 3),
        "fit_table": table,
        "residual_after_tps": resid_after,
        "spec_georef_baseline": georef,
    }
    out_path = pc.PROTO_DIR / "registration.json"
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"wrote {out_path}")

    # --------------------------------------------------- coast check img
    print("rendering coast-check image…")
    render_check(transform, polys, frame, ne_ll, coast_tree, our_pts)
    print(f"done in {time.time() - t_start:.0f}s")
    return 0


def render_check(transform, polys, frame, ne_ll,
                 coast_tree, our_pts):
    """Overview + six 4x crops: relief, our coast edge, disagreements."""
    from .bake import ensure_raster, raster_georef, warp_raster

    tif = ensure_raster()
    to_px = raster_georef(tif)
    raster = np.asarray(Image.open(tif).convert("RGB"))
    margin = 5.0
    o_rect = (frame["x"] - margin, frame["y"] - margin,
              frame["x"] + frame["width"] + margin,
              frame["y"] + frame["height"] + margin)

    # disagreement markers (both directions)
    bx, by = transform.fwd(ne_ll[:, 0], ne_ll[:, 1])
    ne_tree = cKDTree(np.column_stack([bx, by]))
    d_ours, _ = ne_tree.query(our_pts)
    bad_ours = our_pts[d_ours > DISAGREE_UNITS]
    d_ne, _ = coast_tree.query(np.column_stack([bx, by]))
    bad_ne = np.column_stack([bx, by])[d_ne > DISAGREE_UNITS]
    print(f"  disagreement pts: ours={len(bad_ours)} ne={len(bad_ne)}")

    def compose(r, ppu, edge_mask):
        rgb = warp_raster(r, ppu, transform, raster, to_px)
        # red = our coastline edge
        rgb[edge_mask] = [255, 60, 60]
        img = Image.fromarray(rgb)
        dr = ImageDraw.Draw(img)
        for pts, col in ((bad_ours, (255, 0, 255)),
                         (bad_ne, (0, 255, 255))):
            step = max(1, len(pts) // 6000)
            for pt in pts[::step]:
                cx = (pt[0] - r[0]) * ppu
                cy = (pt[1] - r[1]) * ppu
                if -2 <= cx < img.width + 2 and -2 <= cy < img.height + 2:
                    dr.ellipse([cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5],
                               fill=col)
        return img

    def edge_in(r, ppu):
        """Edge pixels of the rendered land mask for rect r."""
        m = our_land_mask(polys, r, ppu)
        return m & ~binary_erosion(m)

    img = compose(o_rect, OVERVIEW_PPU, edge_in(o_rect, OVERVIEW_PPU))
    img.save(pc.REF_DIR / "relief_coast_check.png", optimize=True)

    half_w = CROP_SIZE_UNITS[0] / 2.0
    half_h = CROP_SIZE_UNITS[1] / 2.0
    for name, (lon, lat) in CROPS.items():
        cx_b, cy_b = transform.fwd(np.array([lon]), np.array([lat]))
        cx_b, cy_b = float(cx_b[0]), float(cy_b[0])
        r = (cx_b - half_w, cy_b - half_h, cx_b + half_w, cy_b + half_h)
        ppu = OVERVIEW_PPU * CROP_SCALE
        im2 = compose(r, ppu, edge_in(r, ppu))
        im2.save(pc.REF_DIR / f"relief_coast_crop_{name}.png",
                 optimize=True)
        print(f"  crop {name}: base=({cx_b:.1f},{cy_b:.1f})")


if __name__ == "__main__":
    sys.exit(main())
