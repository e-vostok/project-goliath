"""Fitted lon/lat <-> base transform, shared by register/bake/preview.

The model is ``base = affine(proj(lonlat)) + TPS(affine(proj(lonlat)))``
with the TPS term absent when no correction was needed.  The inverse
(base -> lonlat, needed to resample the raster) is computed by a few
fixed-point iterations on the TPS correction; the correction field is
smooth and small, so 3 iterations converge well below pixel scale.
"""
from __future__ import annotations

import json

import numpy as np
import pyproj
from scipy.interpolate import RBFInterpolator

from . import proto_common as pc


class Transform:
    def __init__(self, proj_kw: dict, affine, shift, gcps=None):
        self.proj = pyproj.Proj(**proj_kw)
        self.M = np.asarray(affine, dtype=float)
        self.t = np.asarray(shift, dtype=float)
        self.Minv = np.linalg.inv(self.M)
        self.tps = None
        if gcps:
            est = np.array([g["base_est"] for g in gcps], dtype=float)
            true = np.array([g["base_true"] for g in gcps], dtype=float)
            self.tps = RBFInterpolator(
                est, true - est, kernel="thin_plate_spline", degree=1
            )

    def fwd(self, lon, lat):
        """lon/lat degrees -> base units."""
        u, v = self.proj(lon, lat)
        bx = self.M[0, 0] * u + self.M[0, 1] * v + self.t[0]
        by = self.M[1, 0] * u + self.M[1, 1] * v + self.t[1]
        if self.tps is not None:
            c = self.tps(np.column_stack([np.ravel(bx), np.ravel(by)]))
            bx = np.asarray(bx) + c[:, 0].reshape(np.shape(bx))
            by = np.asarray(by) + c[:, 1].reshape(np.shape(by))
        return bx, by

    def inv(self, bx, by):
        """base units -> lon/lat degrees (fixed-point on the TPS)."""
        bx = np.asarray(bx, dtype=float)
        by = np.asarray(by, dtype=float)
        dx = np.zeros_like(bx)
        dy = np.zeros_like(by)
        for _ in range(4):
            ux = bx - dx - self.t[0]
            uy = by - dy - self.t[1]
            u = self.Minv[0, 0] * ux + self.Minv[0, 1] * uy
            v = self.Minv[1, 0] * ux + self.Minv[1, 1] * uy
            lon, lat = self.proj(u, v, inverse=True)
            if self.tps is None:
                break
            b0x = self.M[0, 0] * u + self.M[0, 1] * v + self.t[0]
            b0y = self.M[1, 0] * u + self.M[1, 1] * v + self.t[1]
            c = self.tps(np.column_stack([np.ravel(b0x), np.ravel(b0y)]))
            dx = c[:, 0].reshape(np.shape(bx))
            dy = c[:, 1].reshape(np.shape(by))
        return lon, lat


def load(path=None) -> Transform:
    doc = json.loads(
        (path or pc.PROTO_DIR / "registration.json").read_text("utf-8")
    )
    return Transform(doc["proj_kw"], doc["affine"], doc["shift"],
                     doc.get("gcps"))
