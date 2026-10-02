/**
 * View mathematics of the map screen — Spec 3.8, pure functions.
 *
 * Coordinates: the map lives in "world" units of the source SVG; the
 * screen transform is `screen = t + s·world`, where `s = s_fit · z`
 * (s_fit fits `playable_bbox` into the viewport, `z` is the user zoom
 * within [zoom_min, zoom_max]).
 */

export type BBox = [number, number, number, number]; // [x0, y0, x1, y1]

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

/** Fit scale of a bbox into a viewport (Spec 3.8: s_fit). */
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

/** The initial view: the playable area fitted to the window (z = 1). */
export function fitView(bbox: BBox, viewport: Size): ViewTransform {
  return centeredAt(bbox, viewport, fitScale(bbox, viewport));
}

/** Total-scale bounds implied by the zoom rules (s = s_fit · z). */
export function scaleBounds(
  sFit: number,
  zoomMin: number,
  zoomMax: number,
): [number, number] {
  return [sFit * zoomMin, sFit * zoomMax];
}

/**
 * Zoom around a screen point (Spec 3.8): the point `c` keeps the same
 * world point under the cursor — t' = c − (c − t)·(s′/s).
 */
export function zoomAtPoint(
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

/**
 * Pan clamp (Spec 3.8): with margin μ the bbox may leave the viewport by
 * at most a μ fraction of the window size on each side.
 */
export function clampPan(
  view: ViewTransform,
  bbox: BBox,
  viewport: Size,
  marginFraction: number,
): ViewTransform {
  const mx = marginFraction * viewport.width;
  const my = marginFraction * viewport.height;
  const clampAxis = (v: number, lo: number, hi: number) =>
    // An empty interval (content smaller than viewport + margins) has no
    // legal value; its midpoint is exactly the centred position.
    lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v));
  return {
    s: view.s,
    tx: clampAxis(
      view.tx,
      viewport.width - view.s * bbox[2] - mx,
      -view.s * bbox[0] + mx,
    ),
    ty: clampAxis(
      view.ty,
      viewport.height - view.s * bbox[3] - my,
      -view.s * bbox[1] + my,
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
 * old centre stays at the new centre, and the user zoom z = s/s_fit is
 * preserved (s_fit itself is viewport-dependent).
 */
export function rescaleOnResize(
  view: ViewTransform,
  bbox: BBox,
  oldViewport: Size,
  newViewport: Size,
): ViewTransform {
  const oldFit = fitScale(bbox, oldViewport);
  const newFit = fitScale(bbox, newViewport);
  if (oldFit === 0 || newFit === 0) {
    return fitView(bbox, newViewport);
  }
  const z = view.s / oldFit;
  const centre = screenToWorld(view, {
    x: oldViewport.width / 2,
    y: oldViewport.height / 2,
  });
  const s = newFit * z;
  return {
    s,
    tx: newViewport.width / 2 - s * centre.x,
    ty: newViewport.height / 2 - s * centre.y,
  };
}
