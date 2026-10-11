"""map2_16 relief bakes: determinism + off-raster registration guard +
alpha at the Project Owner's fixed sample points on the shipped images.

The synthetic tests run on a small raster (flat sea value + a textured
land blob) warped through the REAL registration.json over a small rect,
so they exercise the same code path as the production bake without the
70 MB source. The sample-point test reads the actual baked WebP files
and the client manifest — the artefacts that ship — and checks the
alpha at geographic points the Project Owner named.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.map_pipeline import build_relief as br
from tools.map_pipeline.relief.transform import load as load_transform

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT_MANIFEST = (
    REPO_ROOT / "frontend" / "src" / "modules" / "01_map" / "relief"
    / "manifest.json"
)
WEB_DIR = REPO_ROOT / "frontend" / "public" / "assets" / "map"


def global_raster(w: int = 360, h: int = 180):
    """A 'plate carrée' raster: flat sea + one textured land blob.

    Returns (uint8 array, to_px(lon, lat) -> (col, row) of centres).
    """
    g = np.full((h, w), 145, dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    blob = (np.abs(xx - 200) < 30) & (np.abs(yy - 60) < 20)
    g[blob] = (170 + (xx * 3 + yy * 7) % 19)[blob].astype(np.uint8)

    def to_px(lon, lat):
        col = (np.asarray(lon, float) + 180.0) / 360.0 * w - 0.5
        row = (90.0 - np.asarray(lat, float)) / 180.0 * h - 0.5
        return col, row

    return g, to_px


def mini_geometry_manifest():
    """One LAND node + surrounding outside/sea shapes, base units."""
    geometry = {
        "paths": {"1": "M 520 60 560 60 560 100 520 100 Z"},
        "outside": "M 500 40 580 40 580 120 500 120 Z",
        "sea_water": "",
    }
    manifest = {"nodes": [{"id": 1, "kind": "LAND"}]}
    return geometry, manifest


RECT = (512.0, 44.0, 576.0, 112.0)  # inside view.frame


def test_playable_bake_is_deterministic():
    transform = load_transform()
    raster, to_px = global_raster()
    geometry, manifest = mini_geometry_manifest()

    a = br.bake_playable(RECT, 8.0, transform, raster, to_px,
                         geometry, manifest)
    b = br.bake_playable(RECT, 8.0, transform, raster, to_px,
                         geometry, manifest)
    assert a.shape == b.shape
    assert (a == b).all()
    body_a = br.encode_webp(a, br.WEBP_QUALITY)
    body_b = br.encode_webp(b, br.WEBP_QUALITY)
    assert hashlib.sha256(body_a).hexdigest() == hashlib.sha256(
        body_b
    ).hexdigest()

    # Alpha follows the polygon, not the raster: inside the LAND poly
    # it is opaque even where the synthetic raster says "sea".
    assert a[40 * 8, 28 * 8, 1] == 255   # (540, 84) inside the poly
    assert a[2 * 8, 2 * 8, 1] == 0       # (514, 46) outside the poly


def test_off_raster_registration_fails_with_clear_message():
    transform = load_transform()
    # A 'raster' covering only lon 0..10, lat 40..50 — the frame maps
    # almost entirely outside of it.
    w = h = 16
    raster = np.full((h, w), 145, dtype=np.uint8)

    def to_px(lon, lat):
        col = (np.asarray(lon, float) - 0.0) / 10.0 * w - 0.5
        row = (50.0 - np.asarray(lat, float)) / 10.0 * h - 0.5
        return col, row

    with pytest.raises(br.ReliefBuildError, match="outside the source"):
        br.warp(RECT, 8.0, transform, raster, to_px)


# --------------------------------------------- shipped-image alpha points
#
# (lon, lat) pairs the Project Owner named; the transform converts them
# to base units, the manifest rect converts those to image pixels.

PLAYABLE_ZERO = {
    "north_sea": (3.5, 56.0),
    # Open Tyrrhenian Sea NW of the Aeolian islands (38.4..38.8N,
    # 14.3..15.6E) — anything closer lands inside NE Sicily.
    "aeolian_tyrrhenian": (14.0, 39.0),
    "lake_vanern": (13.2, 58.9),
    "algerian_salt_lake": (35.45, 4.9),
}
PLAYABLE_OPAQUE = {
    "sicily": (14.15, 37.55),
    "ireland": (-8.0, 53.4),
}
INACTIVE_OPAQUE = {
    "iceland": (-18.5, 64.9),
    "w_kazakhstan": (55.0, 50.0),
    "sahara": (10.0, 23.0),
    "greenland": (-40.0, 73.0),
    "ohio": (-82.8, 40.2),
}
INACTIVE_ZERO = {
    "atlantic": (-30.0, 35.0),
    "black_sea": (34.7, 43.4),
    "lake_vanern": (13.2, 58.9),
}


def _load_baked(key: str):
    manifest = json.loads(CLIENT_MANIFEST.read_text("utf-8"))
    entry = manifest[key]
    path = WEB_DIR / Path(entry["file"]).name
    assert path.exists(), f"baked image missing: {path}"
    img = np.asarray(Image.open(path))
    # WebP stores LA as RGBA (grey duplicated into RGB).
    assert img.ndim == 3 and img.shape[2] == 4, "expected RGBA raster"
    return img, entry["rect"]


def _alpha_at(img, rect, lon: float, lat: float,
              transform, *, world: bool) -> int:
    bx, by = transform.fwd(np.array([lon]), np.array([lat]))
    x, y, w, h = rect
    col = int((float(bx[0]) - x) / w * img.shape[1])
    row = int((float(by[0]) - y) / h * img.shape[0])
    if not (0 <= col < img.shape[1] and 0 <= row < img.shape[0]):
        # Off the playable rect nothing is drawn — alpha 0 by
        # definition. The world image must cover every on-globe point.
        assert not world, (
            f"sample ({lon}, {lat}) maps outside the world rect"
        )
        return 0
    # Median of a 5x5 neighbourhood — one odd resample pixel must not
    # decide the check; a wrong mask fails on the whole area.
    patch = img[
        max(0, row - 2): row + 3, max(0, col - 2): col + 3, 3
    ]
    return int(np.median(patch))


def test_baked_alpha_at_sample_points():
    transform = load_transform()
    playable, rect_p = _load_baked("playable")
    inactive, rect_w = _load_baked("inactive")

    for name, (lon, lat) in PLAYABLE_ZERO.items():
        assert _alpha_at(
            playable, rect_p, lon, lat, transform, world=False
        ) == 0, f"playable alpha must be 0 at {name}"
    for name, (lon, lat) in PLAYABLE_OPAQUE.items():
        assert _alpha_at(
            playable, rect_p, lon, lat, transform, world=False
        ) == 255, f"playable alpha must be 255 at {name}"
    for name, (lon, lat) in INACTIVE_OPAQUE.items():
        assert _alpha_at(
            inactive, rect_w, lon, lat, transform, world=True
        ) == 255, f"inactive alpha must be 255 at {name}"
    for name, (lon, lat) in INACTIVE_ZERO.items():
        assert _alpha_at(
            inactive, rect_w, lon, lat, transform, world=True
        ) == 0, f"inactive alpha must be 0 at {name}"
