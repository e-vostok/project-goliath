/**
 * Label layout (map2_6, Spec 3.9) — pure functions, no pan dependency.
 *
 * A node's name is drawn only when it FITS its `label` box at the
 * current scale: the largest font size in [min, max] whose one- or
 * two-line text is no wider and no taller than
 * `fit_ratio × {w,h} × scale` screen px. Two lines (break at a space or
 * hyphen) are used only when they permit a larger size. Candidates are
 * placed in area-priority order into a screen-space collision grid —
 * the loser is hidden at this zoom. The result depends on nodes +
 * scale only, so a pan never relayouts.
 *
 * map2_6c: kind gating — province names exist only at the maximum zoom
 * (`scale ≥ province_zoom_ratio × maxScale`), sea names only below it.
 * The RENDERED subset of placed labels follows the viewport during a
 * pan (selectRendered / windowCoversView), and at the maximum zoom a
 * province label shows only while most of its province is in view
 * (labelMostlyInView).
 *
 * map2_20: the name follows the province's shape. The pipeline baked a
 * `spine` baseline into every label — a straight or gently bent chord
 * inscribed in the territory — and the client only fits text onto it:
 * font size bounded by the local `thick`, letter spacing between
 * `letter_spacing_min_em`/`_max_em` to reach `length_ratio` of the
 * chord, `max_bend` already honoured by the arc itself. Curved labels
 * collide as oriented boxes around the real path. When nothing fits
 * along the spine the map2_6 box fit (the two-line horizontal version
 * included) stays as the fallback; nodes without `spine` keep the old
 * behaviour too.
 */

import type { MapLabelsRulesDTO, MapNodeDTO } from '../types';
import type { Size, ViewTransform } from './view';
import { displayName } from './search';

/** Line height used for the text block fit, in em. */
const LINE_H = 1.2;
/** Collision-grid cell side, screen px. */
const GRID_CELL_PX = 96;
/** Hard cap of rendered <text> elements at once (map2_6c). */
export const MAX_RENDERED_LABELS = 600;
/** How many `exiting` copies paint the fade at once (map2_21): the
 *  merge order is the placed priority order, so these are the
 *  top-priority leavers; the rest stay mounted as `ghost` copies
 *  (display:none — no raster, no extra commit) until the chunked
 *  sweep unmounts the batch. */
export const MAX_EXITING_LABELS = 100;
/** Rendered labels must cover the viewport grown by this fraction of
 *  the screen on every side (so a label exists before it shows). */
const RENDER_MARGIN = 0.5;
/** Re-select the rendered set once the viewport grown by this fraction
 *  is no longer covered by the current selection window. */
const RESELECT_MARGIN = 0.25;
/** «Most of the province in view» — bbox share threshold (map2_6c). */
const MOST_IN_VIEW_SHARE = 0.5;
/** …or the label anchor inside the viewport shrunk by this fraction on
 *  every side (covers provinces larger than the screen). */
const ANCHOR_INSET = 0.1;
/** Reference font size the canvas measures at (per-px factor below). */
const MEASURE_REF_PX = 64;

/** map2_20/map2_21 rule defaults — the configs/01_map.yaml values,
 *  used when a rules block predates the keys (cached manifests, perf
 *  stubs); a live server always sends them. */
export const SPINE_DEFAULTS = {
  thickness_ratio: 0.55,
  length_ratio: 0.85,
  letter_spacing_min_em: -0.02,
  letter_spacing_max_em: 0.3,
  land_opacity: 0.6,
  sea_curved: true,
  sea_font: 'pt_mono',
} as const;

export { MAP_FONTS as LABEL_FONT_FAMILIES } from './fonts';

export interface LabelMeasurer {
  /** Text width at font-size 1 px, letter spacing included. */
  measure(text: string, letterSpacingEm: number): number;
}

/**
 * Measurer backed by an offscreen canvas (the real bundled font once
 * `document.fonts` has loaded it). Widths are measured once per text at
 * MEASURE_REF_PX and cached as a per-px factor — linear scaling is
 * accurate enough at these sizes. When canvas is unavailable (tests,
 * SSR) a deterministic condensed-face estimate is used instead.
 */
export function createMeasurer(family: string): LabelMeasurer {
  let ctx: CanvasRenderingContext2D | null = null;
  if (typeof document !== 'undefined') {
    try {
      ctx = document.createElement('canvas').getContext('2d');
    } catch {
      ctx = null;
    }
  }
  const cache = new Map<string, number>();
  const rawWidth = (text: string): number => {
    let w = cache.get(text);
    if (w !== undefined) {
      return w;
    }
    if (ctx !== null) {
      ctx.font = `500 ${MEASURE_REF_PX}px ${family}`;
      w = ctx.measureText(text).width / MEASURE_REF_PX;
    } else {
      // Heuristic for a condensed face (~0.5 em average).
      w = 0;
      for (const ch of text) {
        w += ch === ' '
          ? 0.28
          : ch === '-' || ch === '’'
            ? 0.34
            : /[\p{Lu}]/u.test(ch)
              ? 0.62
              : 0.5;
      }
    }
    cache.set(text, w);
    return w;
  };
  return {
    measure(text, letterSpacingEm) {
      const gaps = Math.max(0, Array.from(text).length - 1);
      return rawWidth(text) + letterSpacingEm * gaps;
    },
  };
}

/** Quadratic-Bézier baseline slice a curved name follows (map2_20),
 *  map units — rendered via `<textPath>` like the state names. */
export interface LabelPath {
  x0: number;
  y0: number;
  cx: number;
  cy: number;
  x1: number;
  y1: number;
}

/** One label that survived fit + collision, ready to render. Positions
 *  and sizes are in MAP units so the label <g> moves with the world
 *  transform and needs no work during a pan. */
export interface PlacedLabel {
  id: number;
  kind: 'LAND' | 'SEA';
  /** Text centre, map units (the collision box's centre for a curved
   *  label — its baseline midpoint offset along the slice normal). */
  x: number;
  y: number;
  /** font-size in map units (screen px ÷ scale). */
  fontSize: number;
  /** Chosen size, screen px (tests/debugging). */
  sizePx: number;
  /** halo stroke-width in map units. */
  haloW: number;
  lines: [string] | [string, string];
  /** Axis-aligned text box size in map units (screen px ÷ scale) —
   *  the bounding box of the curved box for a path label. */
  textW: number;
  textH: number;
  /** Curved baseline slice (map2_20); null → straight box label. */
  path: LabelPath | null;
  /** Letter spacing in em (computed along the spine for curved labels;
   *  `sea_letter_spacing_em` for a straight sea label, 0 for land). */
  letterSpacingEm: number;
  /** Whole-element opacity — `labels.land_opacity` for province names
   *  (map2_20), 1 for sea labels (their map2_6 look is unchanged). */
  opacity: number;
  /** Node bbox in map units — the «most in view» fade rule (map2_6c). */
  bbox: [number, number, number, number];
}

/** A rendered label; `exiting` carries a merge stamp while it fades
 *  out (zoom/layout change, crossfade) before unmount. `ghost` marks
 *  exiting copies beyond the visible-fade cap: kept mounted
 *  (display:none — no raster) so a kind switch never becomes one big
 *  removal commit, and dropped by the chunked sweep (map2_21). */
export interface RenderedLabel extends PlacedLabel {
  exiting?: number;
  ghost?: boolean;
}

interface Candidate {
  node: MapNodeDTO;
  name: string;
  /** Collision-box centre, map units. */
  x: number;
  y: number;
  sizePx: number;
  lines: [string] | [string, string];
  /** Text box dims, screen px (pre-padding). */
  textW: number;
  textH: number;
  path: LabelPath | null;
  letterSpacingEm: number;
  opacity: number;
  /** Collision OBB: major-axis unit vector and half extents in map
   *  units, centred on (x, y); the padding is added in screen px when
   *  the grid is built. */
  ux: number;
  uy: number;
  hw: number;
  hh: number;
}

/** Every valid two-line split of `name`: break at a space (removed) or
 *  a hyphen (kept on the first line). Never more than two lines. */
export function lineSplits(name: string): [string, string][] {
  const out: [string, string][] = [];
  const chars = Array.from(name);
  for (let i = 0; i < chars.length - 1; i++) {
    const ch = chars[i];
    if (ch === ' ') {
      const a = chars.slice(0, i).join('').trimEnd();
      const b = chars.slice(i + 1).join('').trimStart();
      if (a !== '' && b !== '') {
        out.push([a, b]);
      }
    } else if (ch === '-') {
      const a = chars.slice(0, i + 1).join('');
      const b = chars.slice(i + 1).join('');
      if (b !== '') {
        out.push([a, b]);
      }
    }
  }
  return out;
}

/** Largest in-range size whose text fits the node's `label` box at
 *  `scale`, or null when even `minPx` does not fit. */
function fitCandidate(
  node: MapNodeDTO,
  name: string,
  scale: number,
  rules: MapLabelsRulesDTO,
  measurer: LabelMeasurer,
): Candidate | null {
  const sea = node.kind === 'SEA';
  const minPx = sea ? rules.sea_min_px : rules.land_min_px;
  const maxPx = sea ? rules.sea_max_px : rules.land_max_px;
  const spacing = sea ? rules.sea_letter_spacing_em : 0;
  const W = node.label.w * scale * rules.fit_ratio;
  const H = node.label.h * scale * rules.fit_ratio;
  if (!(W > 0) || !(H > 0)) {
    return null;
  }

  // One line: width and height both capped by the box.
  const w1 = measurer.measure(name, spacing);
  if (!(w1 > 0)) {
    return null;
  }
  const p1 = Math.min(maxPx, W / w1, H / LINE_H);

  // Two lines: the split that minimises the longer line, then the same
  // fit rule against a two-line block.
  let bestSplit: [string, string] | null = null;
  let w2 = Number.POSITIVE_INFINITY;
  for (const split of lineSplits(name)) {
    const w = Math.max(
      measurer.measure(split[0], spacing),
      measurer.measure(split[1], spacing),
    );
    if (w < w2) {
      w2 = w;
      bestSplit = split;
    }
  }
  const p2 = bestSplit === null
    ? -1
    : Math.min(maxPx, W / w2, H / (2 * LINE_H));

  let sizePx: number;
  let lines: [string] | [string, string];
  let textW: number;
  if (bestSplit !== null && p2 > p1 && p2 >= minPx) {
    sizePx = p2;
    lines = bestSplit;
    textW = w2 * p2;
  } else if (p1 >= minPx) {
    sizePx = p1;
    lines = [name];
    textW = w1 * p1;
  } else {
    return null;
  }
  const textH = lines.length * LINE_H * sizePx;
  return {
    node,
    name,
    x: node.label.x,
    y: node.label.y,
    sizePx,
    lines,
    textW,
    textH,
    path: null,
    letterSpacingEm: spacing,
    opacity: sea ? 1 : (rules.land_opacity ?? SPINE_DEFAULTS.land_opacity),
    ux: 1,
    uy: 0,
    hw: textW / 2 / scale,
    hh: textH / 2 / scale,
  };
}

/**
 * map2_20: fit `name` along the node's spine — a chord or gentle arc
 * inscribed in the territory. Font size is capped by the local
 * thickness (`thickness_ratio × thick` screen px of text height) and
 * `min/max_px`; letter spacing spreads the glyphs between
 * `letter_spacing_min_em`/`_max_em` up to `length_ratio` of the chord
 * length, and when even the tightest spacing overflows, the font
 * shrinks. Returns null below `minPx` — the caller falls back to the
 * map2_6 box fit. The collision box is oriented along the drawn arc
 * slice, not the axis-aligned `label` box.
 */
function fitSpineCandidate(
  node: MapNodeDTO,
  name: string,
  scale: number,
  rules: MapLabelsRulesDTO,
  measurer: LabelMeasurer,
): Candidate | null {
  const label = node.label;
  if (
    label.spine === undefined ||
    label.len === undefined ||
    label.thick === undefined
  ) {
    return null;
  }
  const sea = node.kind === 'SEA';
  const minPx = sea ? rules.sea_min_px : rules.land_min_px;
  const maxPx = sea ? rules.sea_max_px : rules.land_max_px;
  const lengthRatio = rules.length_ratio ?? SPINE_DEFAULTS.length_ratio;
  const thicknessRatio =
    rules.thickness_ratio ?? SPINE_DEFAULTS.thickness_ratio;
  const lsMin =
    rules.letter_spacing_min_em ?? SPINE_DEFAULTS.letter_spacing_min_em;
  const lsMax =
    rules.letter_spacing_max_em ?? SPINE_DEFAULTS.letter_spacing_max_em;
  const targetLen = lengthRatio * label.len * scale;
  const heightCap = thicknessRatio * label.thick * scale;
  if (!(targetLen > 0) || !(heightCap > 0)) {
    return null;
  }

  const w0 = measurer.measure(name, 0);
  if (!(w0 > 0)) {
    return null;
  }
  const gaps = Math.max(0, Array.from(name).length - 1);
  let sizePx = Math.min(maxPx, heightCap / LINE_H);
  let spacing: number;
  if (gaps === 0) {
    spacing = 0;
    if (sizePx * w0 > targetLen) {
      sizePx = targetLen / w0;
    }
  } else {
    spacing = (targetLen / sizePx - w0) / gaps;
    if (spacing > lsMax) {
      spacing = lsMax;
    } else if (spacing < lsMin) {
      spacing = lsMin;
      sizePx = targetLen / (w0 + lsMin * gaps);
    }
  }
  if (sizePx < minPx || !(sizePx > 0)) {
    return null;
  }
  sizePx = Math.min(sizePx, maxPx);

  const textW = sizePx * (w0 + spacing * gaps);
  const textH = LINE_H * sizePx;

  // The arc slice the text actually rides: the central part of the
  // spine whose chord is exactly the text width — centred on the
  // spine's midpoint so the name sits in the middle of the stretch.
  const [x0, y0, x1, y1, s] = label.spine;
  const len = label.len;
  const halfT = Math.min(textW / scale / len / 2, 0.5);
  const tA = 0.5 - halfT;
  const tB = 0.5 + halfT;
  const dnx = -(y1 - y0) / len;
  const dny = (x1 - x0) / len;
  const arcPt = (t: number) => {
    const f = 4 * s * t * (1 - t);
    return {
      x: x0 + (x1 - x0) * t + f * dnx,
      y: y0 + (y1 - y0) * t + f * dny,
    };
  };
  const pA = arcPt(tA);
  const pB = arcPt(tB);
  const pM = arcPt(0.5);

  // The slice is itself a parabola: control = 2·mid − chord mid.
  const path: LabelPath = {
    x0: pA.x,
    y0: pA.y,
    cx: 2 * pM.x - (pA.x + pB.x) / 2,
    cy: 2 * pM.y - (pA.y + pB.y) / 2,
    x1: pB.x,
    y1: pB.y,
  };

  // Oriented collision box around the drawn slice: major axis = the
  // slice's own chord, minor = slice sagitta + text height.
  const midX = (pA.x + pB.x) / 2;
  const midY = (pA.y + pB.y) / 2;
  const sliceLen = Math.hypot(pB.x - pA.x, pB.y - pA.y);
  const ux = sliceLen > 1e-9 ? (pB.x - pA.x) / sliceLen : 1;
  const uy = sliceLen > 1e-9 ? (pB.y - pA.y) / sliceLen : 0;
  const sagSlice =
    (pM.x - midX) * -uy + (pM.y - midY) * ux;
  const hw = sliceLen / 2;
  const hh = Math.abs(sagSlice) / 2 + textH / 2 / scale;
  return {
    node,
    name,
    x: midX + (sagSlice / 2) * -uy,
    y: midY + (sagSlice / 2) * ux,
    sizePx,
    lines: [name],
    textW,
    textH,
    path,
    letterSpacingEm: spacing,
    opacity: sea ? 1 : (rules.land_opacity ?? SPINE_DEFAULTS.land_opacity),
    ux,
    uy,
    hw,
    hh,
  };
}

export interface LabelRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** Oriented box in screen px — the real collision shape of a curved
 *  (or straight: u=(1,0)) label. `v` = the left normal (−uy, ux). */
interface LabelBox {
  cx: number;
  cy: number;
  ux: number;
  uy: number;
  hw: number;
  hh: number;
}

/** Separating-axis test of two oriented boxes (4 axis projections:
 *  both majors and both normals). */
function boxOverlaps(a: LabelBox, b: LabelBox): boolean {
  const dcx = b.cx - a.cx;
  const dcy = b.cy - a.cy;
  const axes = [
    [a.ux, a.uy],
    [-a.uy, a.ux],
    [b.ux, b.uy],
    [-b.uy, b.ux],
  ];
  for (const [ax, ay] of axes) {
    const ra =
      a.hw * Math.abs(a.ux * ax + a.uy * ay) +
      a.hh * Math.abs(-a.uy * ax + a.ux * ay);
    const rb =
      b.hw * Math.abs(b.ux * ax + b.uy * ay) +
      b.hh * Math.abs(-b.uy * ax + b.ux * ay);
    if (Math.abs(dcx * ax + dcy * ay) > ra + rb + 1e-9) {
      return false;
    }
  }
  return true;
}

/** Axis-aligned bounds of an oriented box, for the grid index. */
function boxBounds(b: LabelBox): LabelRect {
  const ex = b.hw * Math.abs(b.ux) + b.hh * Math.abs(b.uy);
  const ey = b.hw * Math.abs(b.uy) + b.hh * Math.abs(b.ux);
  return {
    x0: b.cx - ex,
    y0: b.cy - ey,
    x1: b.cx + ex,
    y1: b.cy + ey,
  };
}

/**
 * True while the camera sits at the maximum zoom: `scale` reaches
 * `province_zoom_ratio` of the camera's own top scale (map2_6c).
 * Province names exist only then; sea names exist only below it.
 */
export function isProvinceZoom(
  scale: number,
  maxScale: number,
  rules: MapLabelsRulesDTO,
): boolean {
  return scale >= rules.province_zoom_ratio * maxScale;
}

/**
 * Lay out every node label for `scale` screen px per map unit.
 *
 * map2_6c: `maxScale` is the camera's maximum (min scale × zoom_max).
 * At the maximum zoom only LAND candidates exist; below it only SEA
 * ones. The layout covers ALL nodes — never culled by the viewport,
 * so a pan can pull any placed label into the rendered set without a
 * relayout.
 */
export function layoutLabels(
  nodes: MapNodeDTO[],
  scale: number,
  rules: MapLabelsRulesDTO,
  measurer: LabelMeasurer,
  maxScale: number,
): PlacedLabel[] {
  if (!Number.isFinite(scale) || scale <= 0) {
    return [];
  }
  const pad = rules.collision_padding_px;
  const atMax = isProvinceZoom(scale, maxScale, rules);
  const seaCurved = rules.sea_curved ?? SPINE_DEFAULTS.sea_curved;

  const candidates: Candidate[] = [];
  for (const node of nodes) {
    if ((node.kind === 'LAND') !== atMax) {
      continue;
    }
    const name = displayName(node);
    if (name === '') {
      continue;
    }
    // map2_20: along the spine first; the map2_6 box (two-line version
    // included) is the fallback. Sea zones keep the box when
    // labels.sea_curved is off.
    const c =
      (node.kind === 'LAND' || seaCurved
        ? fitSpineCandidate(node, name, scale, rules, measurer)
        : null) ?? fitCandidate(node, name, scale, rules, measurer);
    if (c !== null) {
      candidates.push(c);
    }
  }

  // Priority: larger province first; at equal area land before sea;
  // id for a stable order.
  candidates.sort(
    (a, b) =>
      b.node.area - a.node.area ||
      (a.node.kind === b.node.kind ? 0 : a.node.kind === 'LAND' ? -1 : 1) ||
      a.node.id - b.node.id,
  );

  const grid = new Map<string, LabelBox[]>();
  const placed: PlacedLabel[] = [];
  for (const c of candidates) {
    const box: LabelBox = {
      cx: c.x * scale,
      cy: c.y * scale,
      ux: c.ux,
      uy: c.uy,
      hw: c.hw * scale + pad,
      hh: c.hh * scale + pad,
    };
    const rect = boxBounds(box);
    const ix0 = Math.floor(rect.x0 / GRID_CELL_PX);
    const ix1 = Math.floor(rect.x1 / GRID_CELL_PX);
    const iy0 = Math.floor(rect.y0 / GRID_CELL_PX);
    const iy1 = Math.floor(rect.y1 / GRID_CELL_PX);
    let collides = false;
    for (let ix = ix0; ix <= ix1 && !collides; ix++) {
      for (let iy = iy0; iy <= iy1 && !collides; iy++) {
        const cell = grid.get(`${ix}:${iy}`);
        if (cell !== undefined && cell.some((b) => boxOverlaps(box, b))) {
          collides = true;
        }
      }
    }
    if (collides) {
      continue;
    }
    for (let ix = ix0; ix <= ix1; ix++) {
      for (let iy = iy0; iy <= iy1; iy++) {
        const key = `${ix}:${iy}`;
        const cell = grid.get(key);
        if (cell === undefined) {
          grid.set(key, [box]);
        } else {
          cell.push(box);
        }
      }
    }
    // x/y keep the OBB centre and textW/textH its axis-aligned bounds —
    // the pan sweep only needs a sane screen rect.
    const bounds = boxBounds({ ...box, hw: c.hw * scale, hh: c.hh * scale });
    placed.push({
      id: c.node.id,
      kind: c.node.kind,
      x: c.x,
      y: c.y,
      fontSize: c.sizePx / scale,
      sizePx: c.sizePx,
      haloW: rules.halo_width_px / scale,
      lines: c.lines,
      textW: (bounds.x1 - bounds.x0) / scale,
      textH: (bounds.y1 - bounds.y0) / scale,
      path: c.path,
      letterSpacingEm: c.letterSpacingEm,
      opacity: c.opacity,
      bbox: c.node.bbox,
    });
  }
  return placed;
}

/** Screen-px rect of a placed label's text box under `view`. */
export function labelScreenRect(
  label: PlacedLabel,
  view: ViewTransform,
): LabelRect {
  const cx = view.tx + view.s * label.x;
  const cy = view.ty + view.s * label.y;
  const hw = (view.s * label.textW) / 2;
  const hh = (view.s * label.textH) / 2;
  return { x0: cx - hw, y0: cy - hh, x1: cx + hw, y1: cy + hh };
}

function intersectsRect(a: LabelRect, b: LabelRect): boolean {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/**
 * Pick the labels that get a `<text>` element under `view`: every placed
 * label whose text box intersects the viewport enlarged by half a screen
 * on every side (so a label exists before its province shows), capped at
 * MAX_RENDERED_LABELS — viewport-intersecting labels first, then the
 * rest in the placed order (already the priority order), so the lowest
 * priority outside the viewport drops first.
 *
 * Returns the selection window in scaled-map space (screen px minus the
 * view translate) so windowCoversView can compare later pans cheaply.
 */
export function selectRendered(
  placed: PlacedLabel[],
  view: ViewTransform,
  viewport: Size,
): { items: PlacedLabel[]; window: LabelRect } {
  const w = viewport.width;
  const h = viewport.height;
  const viewRect: LabelRect = { x0: 0, y0: 0, x1: w, y1: h };
  const margin: LabelRect = {
    x0: -RENDER_MARGIN * w,
    y0: -RENDER_MARGIN * h,
    x1: (1 + RENDER_MARGIN) * w,
    y1: (1 + RENDER_MARGIN) * h,
  };
  const inside: PlacedLabel[] = [];
  const near: PlacedLabel[] = [];
  for (const l of placed) {
    const r = labelScreenRect(l, view);
    if (intersectsRect(r, viewRect)) {
      inside.push(l);
    } else if (intersectsRect(r, margin)) {
      near.push(l);
    }
  }
  return {
    items: inside.concat(near).slice(0, MAX_RENDERED_LABELS),
    window: {
      x0: -view.tx - RENDER_MARGIN * w,
      y0: -view.ty - RENDER_MARGIN * h,
      x1: -view.tx + (1 + RENDER_MARGIN) * w,
      y1: -view.ty + (1 + RENDER_MARGIN) * h,
    },
  };
}

/**
 * Does the current selection `window` still cover everything the
 * viewport enlarged by a quarter screen could touch? While it does,
 * every label that could enter view already exists; once it doesn't,
 * the rendered set is re-selected (map2_6c pan fix).
 */
export function windowCoversView(
  window: LabelRect,
  view: ViewTransform,
  viewport: Size,
): boolean {
  const w = viewport.width;
  const h = viewport.height;
  return (
    -view.tx - RESELECT_MARGIN * w >= window.x0 &&
    -view.tx + (1 + RESELECT_MARGIN) * w <= window.x1 &&
    -view.ty - RESELECT_MARGIN * h >= window.y0 &&
    -view.ty + (1 + RESELECT_MARGIN) * h <= window.y1
  );
}

/**
 * «Most of the province in view» (map2_6c): at the maximum zoom a
 * province label is visible when at least MOST_IN_VIEW_SHARE of the
 * node's bbox lies inside the viewport, OR the label anchor is inside
 * the viewport shrunk by ANCHOR_INSET on every side (covers provinces
 * larger than the screen).
 */
export function labelMostlyInView(
  label: PlacedLabel,
  view: ViewTransform,
  viewport: Size,
): boolean {
  const bx0 = view.tx + view.s * label.bbox[0];
  const by0 = view.ty + view.s * label.bbox[1];
  const bx1 = view.tx + view.s * label.bbox[2];
  const by1 = view.ty + view.s * label.bbox[3];
  const area = (bx1 - bx0) * (by1 - by0);
  if (area > 0) {
    const ix = Math.min(bx1, viewport.width) - Math.max(bx0, 0);
    const iy = Math.min(by1, viewport.height) - Math.max(by0, 0);
    if (ix > 0 && iy > 0 && (ix * iy) / area >= MOST_IN_VIEW_SHARE) {
      return true;
    }
  }
  const ax = view.tx + view.s * label.x;
  const ay = view.ty + view.s * label.y;
  return (
    ax >= ANCHOR_INSET * viewport.width &&
    ax <= (1 - ANCHOR_INSET) * viewport.width &&
    ay >= ANCHOR_INSET * viewport.height &&
    ay <= (1 - ANCHOR_INSET) * viewport.height
  );
}

/**
 * Merge a freshly selected rendered set with the previous one so React
 * unmounts single elements only: continuing labels keep their identity
 * (same object, same key, no DOM churn), leavers whose text box still
 * intersects the viewport are kept once as `exiting` copies to fade
 * out (the caller unmounts them after `fadeMs`), offscreen leavers drop
 * immediately — invisible either way. Still-fading entries carry over.
 * The result is capped at MAX_RENDERED_LABELS — exiting copies trim
 * first.
 */
export function mergeRendered(
  prev: RenderedLabel[],
  next: PlacedLabel[],
  view: ViewTransform,
  viewport: Size,
  stamp: number,
  fadeMs: number,
): RenderedLabel[] {
  const nextIds = new Set(next.map((l) => l.id));
  const out: RenderedLabel[] = [...next];
  const viewRect: LabelRect = {
    x0: 0,
    y0: 0,
    x1: viewport.width,
    y1: viewport.height,
  };
  // map2_21: every leaver stays mounted as an exiting copy — a kind
  // switch that dropped ~440 nodes in one commit was a >33 ms frame.
  // Only the first MAX_EXITING_LABELS (placed priority order) paint
  // the fade; the rest are `ghost` copies (display:none, no raster),
  // and the chunked sweep unmounts the batch a few at a time.
  let exits = 0;
  for (const p of prev) {
    if (nextIds.has(p.id)) {
      continue;
    }
    if (p.exiting !== undefined) {
      if (!p.ghost) {
        exits += 1;
      }
      out.push(p);
      continue;
    }
    if (fadeMs <= 0) {
      continue;
    }
    const ghost =
      exits >= MAX_EXITING_LABELS ||
      !intersectsRect(labelScreenRect(p, view), viewRect);
    if (!ghost) {
      exits += 1;
    }
    out.push(ghost ? { ...p, exiting: stamp, ghost: true } : { ...p, exiting: stamp });
  }
  return out.slice(0, MAX_RENDERED_LABELS);
}
