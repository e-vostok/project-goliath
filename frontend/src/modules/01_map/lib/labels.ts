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

/** Bundled-family table: CSS family plus whether the family has a real
 *  italic cut — families without one get a synthetic `skewX` slant on
 *  sea labels instead of `font-style: italic`. */
export const LABEL_FONT_FAMILIES: Record<
  MapLabelsRulesDTO['font'],
  { family: string; syntheticSlant: boolean }
> = {
  fira_sans_condensed: {
    family: '"Fira Sans Condensed"',
    syntheticSlant: false,
  },
  pt_sans_narrow: {
    family: '"PT Sans Narrow"',
    syntheticSlant: true, // the family ships Regular+Bold only
  },
  roboto_condensed: {
    family: '"Roboto Condensed"',
    syntheticSlant: false,
  },
};

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

/** One label that survived fit + collision, ready to render. Positions
 *  and sizes are in MAP units so the label <g> moves with the world
 *  transform and needs no work during a pan. */
export interface PlacedLabel {
  id: number;
  kind: 'LAND' | 'SEA';
  /** Text centre, map units. */
  x: number;
  y: number;
  /** font-size in map units (screen px ÷ scale). */
  fontSize: number;
  /** Chosen size, screen px (tests/debugging). */
  sizePx: number;
  /** halo stroke-width in map units. */
  haloW: number;
  lines: [string] | [string, string];
  /** Text box size in map units (screen px ÷ scale). */
  textW: number;
  textH: number;
  /** Node bbox in map units — the «most in view» fade rule (map2_6c). */
  bbox: [number, number, number, number];
}

/** A rendered label; `exiting` carries a merge stamp while it fades
 *  out (zoom/layout change, crossfade) before unmount. */
export interface RenderedLabel extends PlacedLabel {
  exiting?: number;
}

interface Candidate {
  node: MapNodeDTO;
  name: string;
  x: number;
  y: number;
  sizePx: number;
  lines: [string] | [string, string];
  textW: number;
  textH: number;
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
  return {
    node,
    name,
    x: node.label.x,
    y: node.label.y,
    sizePx,
    lines,
    textW,
    textH: lines.length * LINE_H * sizePx,
  };
}

export interface LabelRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

type Rect = LabelRect;

function overlaps(a: Rect, b: Rect): boolean {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
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

  const candidates: Candidate[] = [];
  for (const node of nodes) {
    if ((node.kind === 'LAND') !== atMax) {
      continue;
    }
    const name = displayName(node);
    if (name === '') {
      continue;
    }
    const c = fitCandidate(node, name, scale, rules, measurer);
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

  const grid = new Map<string, Rect[]>();
  const placed: PlacedLabel[] = [];
  for (const c of candidates) {
    const cx = c.x * scale;
    const cy = c.y * scale;
    const rect: Rect = {
      x0: cx - c.textW / 2 - pad,
      y0: cy - c.textH / 2 - pad,
      x1: cx + c.textW / 2 + pad,
      y1: cy + c.textH / 2 + pad,
    };
    const ix0 = Math.floor(rect.x0 / GRID_CELL_PX);
    const ix1 = Math.floor(rect.x1 / GRID_CELL_PX);
    const iy0 = Math.floor(rect.y0 / GRID_CELL_PX);
    const iy1 = Math.floor(rect.y1 / GRID_CELL_PX);
    let collides = false;
    for (let ix = ix0; ix <= ix1 && !collides; ix++) {
      for (let iy = iy0; iy <= iy1 && !collides; iy++) {
        const cell = grid.get(`${ix}:${iy}`);
        if (cell !== undefined && cell.some((r) => overlaps(rect, r))) {
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
          grid.set(key, [rect]);
        } else {
          cell.push(rect);
        }
      }
    }
    placed.push({
      id: c.node.id,
      kind: c.node.kind,
      x: c.x,
      y: c.y,
      fontSize: c.sizePx / scale,
      sizePx: c.sizePx,
      haloW: rules.halo_width_px / scale,
      lines: c.lines,
      textW: c.textW / scale,
      textH: c.textH / scale,
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
  for (const p of prev) {
    if (nextIds.has(p.id)) {
      continue;
    }
    if (p.exiting !== undefined) {
      out.push(p);
      continue;
    }
    if (fadeMs > 0 && intersectsRect(labelScreenRect(p, view), viewRect)) {
      out.push({ ...p, exiting: stamp });
    }
  }
  return out.slice(0, MAX_RENDERED_LABELS);
}
