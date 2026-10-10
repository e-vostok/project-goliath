"""map2_5 relief bake: determinism + off-raster registration guard.

The tests run on a small synthetic raster (flat sea value + a textured
land blob) warped through the REAL registration.json over a small rect,
so they exercise the same code path as the production bake without the
70 MB source.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from tools.map_pipeline import build_relief as br
from tools.map_pipeline.relief.transform import load as load_transform


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
RELIEF_CFG = {"edge_fade_units": 4.0}


def bake_once():
    transform = load_transform()
    raster, to_px = global_raster()
    geometry, manifest = mini_geometry_manifest()
    la = br.bake(RECT, 8.0, transform, raster, to_px, geometry, manifest,
                 RELIEF_CFG)
    return la


def test_bake_is_deterministic():
    a = bake_once()
    b = bake_once()
    assert a.shape == b.shape
    assert (a == b).all()
    body_a = br.encode_webp(a, br.WEBP_QUALITY)
    body_b = br.encode_webp(b, br.WEBP_QUALITY)
    assert hashlib.sha256(body_a).hexdigest() == hashlib.sha256(
        body_b
    ).hexdigest()


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
