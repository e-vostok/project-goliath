"""Register the Project Owner markup image to map base coordinates.

``reference/boundary_v2_markup.png`` is a crop of a render of this same
map in the preview/frontend palette, taken at one uniform scale with no
rotation (map_polish_1, Spec 1.9). This tool finds the similarity
transform

    base_x = offset_x + px_x / scale,  base_y = offset_y + px_y / scale

by maximising the land-mask IoU between the image and a land mask
rasterised from ``geometry.json`` in base coordinates. The mask classes
reproduce the render semantics: land = ``outside`` fill + LAND node
paths; water = SEA node paths, lake windows of ``outside`` and the
inland-water background (the ``outside`` colour covers excluded land
AND unexplored sea alike, so the source SVG alone cannot define the
mask — ``geometry.json`` can).

Search is coarse-to-fine: block-mean downscale ×8 with FFT correlation
over a wide scale grid, ×2 refinement on a narrow grid, then a
full-resolution local grid and, finally, a snap to the image pixel grid
(the image is expected to be an exact pixel crop of a fixed-ppu render).

Outputs (``tools/map_pipeline/reference/``):

- ``boundary_v2_markup.registration.json`` — scale, offset, IoU and
  ``base_rect`` (the full image rectangle in base units), plus both
  mapping directions in a comment field. Shared input of map_polish_2.
- ``calibration_overlay.png`` — the markup image with geometry.json
  outlines drawn on top for a visual check of the fit.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.signal import fftconvolve

from .errors import PipelineError, print_errors
from .svgpath import parse_path

# Palette of the render the markup was drawn on (Spec Part 4 defaults,
# also pipeline_config preview.colors; red/green are the Owner's markup).
_LAND_COLORS = ((140, 140, 140), (42, 42, 42), (255, 0, 0), (76, 255, 0))
_WATER_COLORS = ((30, 53, 71), (62, 107, 132), (44, 74, 98))
_IGNORE_COLORS = ((58, 58, 58),)

REGISTRATION = "boundary_v2_markup.registration.json"
OVERLAY = "calibration_overlay.png"
MARKUP_IMAGE = "boundary_v2_markup.png"

_IOU_MIN = 0.95
_PPU_HI = 12            # base mask raster resolution, px per base unit
_SCALE_LO, _SCALE_HI = 1.95, 8.0
_OVERLAY_COLOR = (0, 255, 255)


class Fit:
    """Similarity transform image px -> base units plus its score."""

    def __init__(self, scale: float, ox: float, oy: float, iou: float):
        self.scale = scale
        self.offset = (ox, oy)
        self.iou = iou

    def base_rect(self, width: int, height: int) -> dict:
        return {
            "x": round(self.offset[0], 1),
            "y": round(self.offset[1], 1),
            "width": round(width / self.scale, 1),
            "height": round(height / self.scale, 1),
        }

    def __repr__(self) -> str:
        return (
            f"Fit(scale={self.scale:.4f}, offset=({self.offset[0]:.4f}, "
            f"{self.offset[1]:.4f}), iou={self.iou:.4f})"
        )


# ---------------------------------------------------------------- masks


def _min_dist(rgb: np.ndarray, colors: tuple) -> np.ndarray:
    """Squared distance from each pixel to the nearest palette colour."""
    pal = np.asarray(colors, dtype=np.int32)
    return ((rgb[..., None, :] - pal) ** 2).sum(-1).min(-1)


def classify_image(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Split the markup image into (land mask, valid mask).

    Land = playable grey, outside dark, red and green markup; water =
    sea and inland-water colours; border lines (and pixels far from
    every palette colour) are not counted by either side.
    """
    rgb = np.asarray(img.convert("RGBA"), dtype=np.int32)[..., :3]
    alpha = np.asarray(img.convert("RGBA"))[..., 3]
    dl = _min_dist(rgb, _LAND_COLORS)
    dw = _min_dist(rgb, _WATER_COLORS)
    dg = _min_dist(rgb, _IGNORE_COLORS)
    land = (dl < dw) & (dl < dg)
    valid = (alpha > 0) & ~((dg <= dl) & (dg <= dw))
    return land, valid


def render_land_mask(
    geometry: dict,
    sea_ids: set[str],
    view_box: list[float],
    ppu: float,
) -> Image.Image:
    """Rasterise the render's land mask over ``view_box`` at ``ppu``.

    Everything starts as water; ``outside`` parts (exteriors filled,
    holes left open) and every non-sea node path become land.
    """
    vx, vy = view_box[0], view_box[1]
    w = max(1, round((view_box[2] - view_box[0]) * ppu))
    h = max(1, round((view_box[3] - view_box[1]) * ppu))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)

    def stamp(polys) -> None:
        for poly in polys:
            ext = [
                ((x - vx) * ppu, (y - vy) * ppu)
                for x, y in poly.exterior.coords
            ]
            draw.polygon(ext, fill=255)
            for hole in poly.interiors:
                hring = [
                    ((x - vx) * ppu, (y - vy) * ppu)
                    for x, y in hole.coords
                ]
                draw.polygon(hring, fill=0)

    stamp(parse_path(geometry["outside"]))
    for key, d in geometry["paths"].items():
        if key not in sea_ids:
            stamp(parse_path(d))
    return img


# ---------------------------------------------------------------- search


def _downsample(x: np.ndarray, d: int) -> np.ndarray:
    h, w = x.shape
    h2, w2 = h // d, w // d
    return x[: h2 * d, : w2 * d].reshape(h2, d, w2, d).mean((1, 3))


def _scale_mask(base: Image.Image, src_ppu: float, ppu: float) -> np.ndarray:
    """Base mask resampled to ``ppu`` px per unit, values in [0, 1]."""
    w = max(1, round(base.width * ppu / src_ppu))
    h = max(1, round(base.height * ppu / src_ppu))
    out = base.resize((w, h), Image.BILINEAR)
    return np.asarray(out, dtype=np.float32) / 255.0


def _iou_map(
    base_frac: np.ndarray, k_land: np.ndarray, k_valid: np.ndarray
) -> np.ndarray:
    """Land-mask IoU of the image at every crop offset (valid mode).

    ``k_land``/``k_valid`` are the image land fraction and validity
    fraction at the same resolution as ``base_frac``.
    """
    inter = fftconvolve(
        base_frac, (k_valid * k_land)[::-1, ::-1], mode="valid"
    )
    cov = fftconvolve(base_frac, k_valid[::-1, ::-1], mode="valid")
    land_sum = float((k_valid * k_land).sum())
    union = land_sum + cov - inter
    return np.divide(
        inter, union, out=np.zeros_like(inter), where=union > 0
    )


def _stage_fft(
    base: Image.Image,
    src_ppu: float,
    land: np.ndarray,
    valid: np.ndarray,
    down: int,
    scales: np.ndarray,
) -> Fit:
    """FFT scan at image downscale ``down``; returns the best Fit."""
    l_f = _downsample((land & valid).astype(np.float32), down)
    v_f = _downsample(valid.astype(np.float32), down)
    best = Fit(0.0, 0.0, 0.0, -1.0)
    for scale in scales:
        ppu = scale / down
        h = round(base.height * ppu / src_ppu)
        w = round(base.width * ppu / src_ppu)
        if h < l_f.shape[0] or w < l_f.shape[1]:
            continue
        b = _scale_mask(base, src_ppu, ppu)
        iou = _iou_map(b, l_f, v_f)
        i = int(np.argmax(iou))
        if iou.flat[i] > best.iou:
            oy, ox = np.unravel_index(i, iou.shape)
            best = Fit(
                float(scale),
                float(ox) * down / scale,
                float(oy) * down / scale,
                float(iou.flat[i]),
            )
    return best


def _iou_at(
    base_img: Image.Image,
    src_ppu: float,
    scale: float,
    ox: float,
    oy: float,
    land: np.ndarray,
    valid: np.ndarray,
    resample: int = Image.BILINEAR,
) -> float:
    """Exact land-mask IoU for one transform via affine resampling."""
    hi, wi = land.shape
    s = src_ppu / scale
    crop = base_img.transform(
        (wi, hi),
        Image.AFFINE,
        (s, 0, ox * src_ppu, 0, s, oy * src_ppu),
        resample=resample,
    )
    b = np.asarray(crop, dtype=np.float32) / 255.0
    if resample == Image.NEAREST:
        b = (b > 0.5).astype(np.float32)
    inter = float((valid * land * b).sum())
    union = float((valid * land).sum() + (valid * b).sum() - inter)
    return inter / union if union > 0 else 0.0


def _refine(
    base_img: Image.Image,
    src_ppu: float,
    fit: Fit,
    land: np.ndarray,
    valid: np.ndarray,
    scale_span: float,
    scale_step: float,
    off_span: float,
    off_step: float,
) -> Fit:
    """Full-resolution grid refinement around ``fit``."""
    best = Fit(fit.scale, *fit.offset, fit.iou)
    ox0, oy0 = fit.offset
    for scale in np.arange(
        fit.scale - scale_span, fit.scale + scale_span + 1e-9, scale_step
    ):
        for oy in np.arange(oy0 - off_span, oy0 + off_span + 1e-9, off_step):
            for ox in np.arange(
                ox0 - off_span, ox0 + off_span + 1e-9, off_step
            ):
                iou = _iou_at(
                    base_img, src_ppu, scale, ox, oy, land, valid
                )
                if iou > best.iou:
                    best = Fit(float(scale), float(ox), float(oy), iou)
    return best


def calibrate(
    land: np.ndarray,
    valid: np.ndarray,
    base_img: Image.Image,
    src_ppu: float = _PPU_HI,
) -> Fit:
    """Find the image->base similarity transform; returns the best Fit."""
    hi, wi = land.shape
    # Stage A: coarse scan, image downscale x8.
    fit = _stage_fft(
        base_img,
        src_ppu,
        land,
        valid,
        8,
        np.arange(_SCALE_LO, _SCALE_HI + 1e-9, 0.05),
    )
    if fit.iou < 0:
        raise PipelineError(
            "CALIBRATION_FAILED", "no scale fits the view_box"
        )
    # Stage B: medium scan, image downscale x2, narrow scale band.
    fit = _stage_fft(
        base_img,
        src_ppu,
        land,
        valid,
        2,
        np.arange(
            max(_SCALE_LO, fit.scale - 0.08),
            min(_SCALE_HI, fit.scale + 0.08) + 1e-9,
            0.01,
        ),
    )
    # Stage C: full-resolution local grid (bilinear eval — smooth, so
    # the argmax basin is reliable).
    fit = _refine(
        base_img, src_ppu, fit, land, valid,
        scale_span=0.015, scale_step=0.003,
        off_span=0.4, off_step=0.05,
    )
    # Stage D: crisp re-evaluation. Bilinear resampling inflates IoU for
    # every candidate, so the last word is nearest-sample agreement.
    # The top of the IoU surface is a flat plateau (±~0.05 units wide);
    # when the scale snapped to 2 decimals (renders use round
    # px-per-unit scales) is statistically indistinguishable from the
    # continuous optimum, prefer the snapped one — it is the physical
    # answer: a crop of a round-ppu render lands at 6.0, not 5.999.
    ox0, oy0 = fit.offset
    snap_scale = round(fit.scale, 2)
    best_per_scale: dict[float, Fit] = {}
    for scale in sorted({fit.scale, snap_scale}):
        grid: list[tuple[float, float, float]] = []
        for oy in np.arange(oy0 - 0.12, oy0 + 0.12 + 1e-9, 0.02):
            for ox in np.arange(ox0 - 0.12, ox0 + 0.12 + 1e-9, 0.02):
                iou = _iou_at(
                    base_img, src_ppu, scale, ox, oy, land, valid,
                    resample=Image.NEAREST,
                )
                grid.append((iou, float(ox), float(oy)))
        top = max(g[0] for g in grid)
        plateau = [g for g in grid if g[0] >= top - 5e-4]
        cx = float(np.mean([g[1] for g in plateau]))
        cy = float(np.mean([g[2] for g in plateau]))
        iou = _iou_at(
            base_img, src_ppu, scale, cx, cy, land, valid,
            resample=Image.NEAREST,
        )
        best_per_scale[scale] = Fit(scale, cx, cy, iou)
    fit = max(best_per_scale.values(), key=lambda f: f.iou)
    if best_per_scale[snap_scale].iou >= fit.iou - 0.0005:
        fit = best_per_scale[snap_scale]
    if fit.iou < _IOU_MIN:
        raise PipelineError(
            "CALIBRATION_FAILED",
            f"best land-mask IoU {fit.iou:.4f} < {_IOU_MIN}",
            details=[repr(fit)],
        )
    return fit


# ---------------------------------------------------------------- outputs


def registration_doc(fit: Fit, width: int, height: int) -> dict:
    return {
        "image_size": [width, height],
        "scale": round(fit.scale, 6),
        "offset": [round(fit.offset[0], 4), round(fit.offset[1], 4)],
        "iou": round(fit.iou, 4),
        "base_rect": fit.base_rect(width, height),
        "_comment": (
            "px -> base: base = offset + px / scale "
            "(scale px per base unit). "
            "base -> px: px = (base - offset) * scale. "
            "base_rect = the full image rectangle in base coordinates, "
            "rounded to 0.1 (units of manifest.view_box)."
        ),
    }


def draw_overlay(
    img: Image.Image,
    geometry: dict,
    fit: Fit,
) -> Image.Image:
    """Markup image with geometry.json outlines drawn on top."""
    out = img.convert("RGBA").copy()
    draw = ImageDraw.Draw(out)
    a = fit.scale
    ox, oy = fit.offset

    def px(ring):
        return [
            ((x - ox) * a, (y - oy) * a) for x, y in ring.coords
        ]

    def stroke(polys) -> None:
        for poly in polys:
            draw.line(px(poly.exterior), fill=_OVERLAY_COLOR, width=1)
            for hole in poly.interiors:
                draw.line(px(hole), fill=_OVERLAY_COLOR, width=1)

    stroke(parse_path(geometry["outside"]))
    for d in geometry["paths"].values():
        stroke(parse_path(d))
    return out


def _sea_ids(manifest: dict) -> set[str]:
    return {
        str(n["id"]) for n in manifest["nodes"] if n["kind"] == "SEA"
    }


def run(
    data_dir: Path,
    image_path: Path,
    out_dir: Path,
) -> Fit:
    """Calibrate and write registration + overlay; returns the Fit."""
    geometry = json.loads(
        (data_dir / "geometry.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    view_box = manifest["view_box"]
    img = Image.open(image_path)
    land, valid = classify_image(img)
    base_img = render_land_mask(
        geometry, _sea_ids(manifest), view_box, _PPU_HI
    )
    fit = calibrate(land, valid, base_img, _PPU_HI)

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = registration_doc(fit, *img.size)
    (out_dir / REGISTRATION).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    draw_overlay(img, geometry, fit).save(out_dir / OVERLAY)
    return fit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.map_pipeline.calibrate_markup",
        description="Register boundary_v2_markup.png to base coordinates.",
    )
    parser.add_argument("--data-dir", default="data/map", type=Path)
    parser.add_argument(
        "--image",
        default=Path("tools/map_pipeline/reference") / MARKUP_IMAGE,
        type=Path,
    )
    parser.add_argument(
        "--out-dir",
        default=Path("tools/map_pipeline/reference"),
        type=Path,
    )
    args = parser.parse_args(argv)
    try:
        fit = run(args.data_dir, args.image, args.out_dir)
    except PipelineError as err:
        print_errors([err])
        return 1
    print(fit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
