/**
 * Label layout (map2_6, Spec 3.9) — pure functions, no pan dependency.
 *
 * A node's name is drawn only when it FITS its `label` box at the
 * current scale: the largest font size in [min, max] whose one- or
 * two-line text is no wider and no taller than
 * `fit_ratio × {w,h} × scale` screen px. Two lines (break at a space or
 * hyphen) are used only when they permit a larger size. Candidates are
 * placed in area-priority order (land before sea at equal area) into a
 * screen-space collision grid — the loser is hidden at this zoom. The
 * result depends on nodes + scale only, so a pan never relayouts.
 */

import type { MapLabelsRulesDTO, MapNodeDTO } from '../types';
import { displayName } from './search';

/** Line height used for the text block fit, in em. */
const LINE_H = 1.2;
/** Collision-grid cell side, screen px. */
const GRID_CELL_PX = 96;
/** Hard cap of rendered <text> elements at any zoom (< 400, Spec 3.9). */
export const MAX_PLACED_LABELS = 399;
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
 * Lay out every node label for `scale` screen px per map unit.
 *
 * `viewRect` (screen px, already margined by the caller) culls labels
 * whose collision rect lies entirely off it — the group itself moves
 * with the map so no per-frame work happens while panning. Pass null to
 * skip culling. Result is capped at MAX_PLACED_LABELS by priority.
 */
export function layoutLabels(
  nodes: MapNodeDTO[],
  scale: number,
  rules: MapLabelsRulesDTO,
  measurer: LabelMeasurer,
  viewRect: LabelRect | null = null,
): PlacedLabel[] {
  if (!Number.isFinite(scale) || scale <= 0) {
    return [];
  }
  const pad = rules.collision_padding_px;

  const candidates: Candidate[] = [];
  for (const node of nodes) {
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
    if (
      viewRect !== null &&
      (rect.x1 < viewRect.x0 ||
        rect.x0 > viewRect.x1 ||
        rect.y1 < viewRect.y0 ||
        rect.y0 > viewRect.y1)
    ) {
      continue;
    }
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
    });
    if (placed.length >= MAX_PLACED_LABELS) {
      break;
    }
  }
  return placed;
}
