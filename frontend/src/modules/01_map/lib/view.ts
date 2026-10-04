/**
 * View mathematics of the map screen — Spec 3.8 (v1.9), pure functions.
 *
 * Coordinates: the map lives in "world" units of the source SVG; the
 * screen transform is `screen = t + s·world`, where `s = s_min · z`.
 * `s_min` fits the *frame* (`view.frame`, a rect in view_box units)
 * by the window HEIGHT only — at z = 1 the whole frame height is
 * visible and the width is centred; a wider window shows `outside`.
 * `z` is the user zoom within [1, zoom_max].
 */

export type BBox = [number, number, number, number]; // [x0, y0, x1, y1]
export type Frame = [number, number, number, number]; // [x, y, w, h]

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/** Affine world→screen transform: screen = (tx, ty) + s · world. */
export interface ViewTransform {
  s: number;
  tx: number;
  ty: number;
}

/** Fit scale of a bbox into a viewport. */
export function fitScale(bbox: BBox, viewport: Size): number {
  const w = bbox[2] - bbox[0];
  const h = bbox[3] - bbox[1];
  if (w <= 0 || h <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return 0;
  }
  return Math.min(viewport.width / w, viewport.height / h);
}

/** Transform that centres a bbox on the viewport at scale `s`. */
export function centeredAt(bbox: BBox, viewport: Size, s: number): ViewTransform {
  return {
    s,
    tx: (viewport.width - s * (bbox[0] + bbox[2])) / 2,
    ty: (viewport.height - s * (bbox[3] + bbox[1])) / 2,
  };
}

/** `s_min = H_v / frame.height` — the frame height fills the window. */
export function minScale(frame: Frame, viewport: Size): number {
  if (frame[3] <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return 0;
  }
  return viewport.height / frame[3];
}

/** Total-scale bounds implied by the zoom rules (s = s_min · z). */
export function scaleBounds(
  sMin: number,
  zoomMax: number,
): [number, number] {
  return [sMin, sMin * zoomMax];
}

/** The initial view: z = 1, the frame centred on the viewport. */
export function initialTransform(
  frame: Frame,
  viewport: Size,
): ViewTransform {
  const s = minScale(frame, viewport);
  return {
    s,
    tx: (viewport.width - s * (2 * frame[0] + frame[2])) / 2,
    ty: (viewport.height - s * (2 * frame[1] + frame[3])) / 2,
  };
}

/**
 * Zoom around a screen point (Spec 3.8): the point `c` keeps the same
 * world point under the cursor — t' = c − (c − t)·(s′/s).
 */
export function zoomAt(
  view: ViewTransform,
  cursor: Point,
  nextScale: number,
): ViewTransform {
  const r = view.s === 0 ? 1 : nextScale / view.s;
  return {
    s: nextScale,
    tx: cursor.x - (cursor.x - view.tx) * r,
    ty: cursor.y - (cursor.y - view.ty) * r,
  };
}

/** Below this range width (px) an axis counts as locked — guards
 *  against a hairline [lo, hi] band left by float rounding at μ = 0. */
const LOCK_EPSILON = 1e-6;

/**
 * Pan clamp (Spec 3.8), per axis: if the visible length exceeds the
 * frame length on an axis, the map is centred on that axis and cannot
 * pan there; otherwise the frame may leave the window by at most a
 * `marginFraction` share of the window size on each side.
 */
export function clampOffset(
  view: ViewTransform,
  frame: Frame,
  viewport: Size,
  marginFraction: number,
): ViewTransform {
  const clampAxis = (
    t: number,
    vLen: number,
    fPos: number,
    fLen: number,
    mu: number,
  ): number => {
    const centre = (vLen - view.s * (2 * fPos + fLen)) / 2;
    if (vLen > view.s * fLen) {
      // Viewport longer than the frame on this axis — centre, no pan.
      return centre;
    }
    const lo = vLen - view.s * (fPos + fLen) - mu * vLen;
    const hi = -view.s * fPos + mu * vLen;
    if (hi - lo < LOCK_EPSILON) {
      // Degenerate band (μ = 0 at z = 1, or rounding dust): lock the
      // axis on the centred value so the map cannot creep.
      return centre;
    }
    return Math.min(hi, Math.max(lo, t));
  };
  return {
    s: view.s,
    tx: clampAxis(
      view.tx,
      viewport.width,
      frame[0],
      frame[2],
      marginFraction,
    ),
    ty: clampAxis(
      view.ty,
      viewport.height,
      frame[1],
      frame[3],
      marginFraction,
    ),
  };
}

/** Screen-space position of a world point. */
export function worldToScreen(view: ViewTransform, p: Point): Point {
  return { x: view.tx + view.s * p.x, y: view.ty + view.s * p.y };
}

/** World-space position of a screen point. */
export function screenToWorld(view: ViewTransform, p: Point): Point {
  return { x: (p.x - view.tx) / view.s, y: (p.y - view.ty) / view.s };
}

/**
 * Fit the view to a node's bbox (search result): scale so the bbox takes
 * `1/margin` of the viewport, clamped to [sMin, sMax], then centre it.
 */
export function fitBBox(
  bbox: BBox,
  viewport: Size,
  margin: number,
  sMin: number,
  sMax: number,
): ViewTransform {
  const fit = fitScale(bbox, viewport) / margin;
  const s = Math.min(sMax, Math.max(sMin, fit));
  return centeredAt(bbox, viewport, s);
}

/**
 * Centre a world point in the viewport keeping the current scale
 * (clamped to [sMin, sMax] — a resize may have made it illegal).
 */
export function centerOn(
  view: ViewTransform,
  point: Point,
  viewport: Size,
  sMin: number,
  sMax: number,
): ViewTransform {
  const s = Math.min(sMax, Math.max(sMin, view.s));
  return {
    s,
    tx: viewport.width / 2 - s * point.x,
    ty: viewport.height / 2 - s * point.y,
  };
}

export function bboxCenter(bbox: BBox): Point {
  return { x: (bbox[0] + bbox[2]) / 2, y: (bbox[1] + bbox[3]) / 2 };
}

/**
 * Recompute the view after the viewport resized: the world point at the
 * old centre stays at the new centre, and the user zoom z = s/s_min is
 * preserved (s_min itself is viewport-dependent). The caller re-clamps
 * the result against the new viewport.
 */
export function rescaleOnResize(
  view: ViewTransform,
  frame: Frame,
  oldViewport: Size,
  newViewport: Size,
): ViewTransform {
  const oldMin = minScale(frame, oldViewport);
  const newMin = minScale(frame, newViewport);
  if (oldMin === 0 || newMin === 0) {
    return initialTransform(frame, newViewport);
  }
  const z = view.s / oldMin;
  const centre = screenToWorld(view, {
    x: oldViewport.width / 2,
    y: oldViewport.height / 2,
  });
  const s = newMin * z;
  return {
    s,
    tx: newViewport.width / 2 - s * centre.x,
    ty: newViewport.height / 2 - s * centre.y,
  };
}
