/**
 * State-name inscriptions (map2_7) — pure placement functions, no pan
 * dependency.
 *
 * One inscription per state is laid along the territory's longest
 * comfortable line: the group's provinces are rasterised into a coarse
 * mask (256 cells on the long bbox side), then a direction/offset
 * search maximises `free length × min thickness` over angles every
 * 10° inside ±`states.max_angle_deg` (refined to 3°), thickness taken
 * by perpendicular scans over the run's central part. The text box is
 * fitted per the rules — height ≤ `thickness_ratio` of the local
 * thickness, length ≈ `length_ratio` of the free run, filled first by
 * letter-spacing up to `max_letter_spacing_em` and then by the font
 * size — and must sit ≥97 % inside the mask or shrink/retry until it
 * does (else the group gets no inscription). map2_7a: each chord is
 * also tried as a gentle arc (sagitta ±max_bend/±max_bend/2 of the
 * chord span); a crescent gets a slightly bent name, a compact state a
 * straight one. The rendered baseline is one quadratic Bézier — a
 * parabola segment — drawn with <textPath>.
 *
 * Everything is computed in MAP units once per ownership/font/config
 * change, so during a pan or a zoom the <text> elements only move and
 * scale with the world transform — the render layer merely clamps the
 * screen size to `min_px`/`max_px` and gates the whole layer off at the
 * maximum zoom (the `labels.province_zoom_ratio` threshold, crossfaded
 * by `labels.fade_ms` — the mirror image of the province names).
 *
 * A state whose provinces form several connected components (land/
 * strait adjacency, same as `selection.components`) gets one
 * inscription per group of ≥ `min_group_share` of the total area, the
 * largest group always included. Screen-space overlaps resolve toward
 * the larger state.
 */

import { components } from './selection';
import type {
  MapEdgeDTO,
  MapNationDTO,
  MapNodeDTO,
  MapStateDTO,
  MapStatesRulesDTO,
} from '../types';
import type { Point } from './view';

/** Bundled faces of the map font registry (map2_21, SIL OFL
 *  self-hosted WOFF2 subsets) — the full CSS stacks live in
 *  `fonts.ts`. */
export { MAP_FONTS as STATE_FONT_FAMILIES } from './fonts';

/** Fixed colours for `color_mode` — palette-consistent with the map. */
export const STATE_TEXT_LIGHT = '#F2F3F5';
export const STATE_TEXT_DARK = '#101014';

/** Text-box height in em used for fit + inside checks. */
const BOX_HEIGHT_EM = 1.0;
/** Long side of the coarse territory mask, cells. */
const MASK_LONG_SIDE = 256;
/** Along-line march step, mask cells. */
const SCAN_STEP = 0.5;
/** Offset grid step (coarse / refined), mask cells. */
const OFFSET_STEP = 1.0;
const OFFSET_STEP_FINE = 0.5;
/** Direction grid (coarse / refined), radians. */
const ANGLE_STEP = (10 * Math.PI) / 180;
const ANGLE_STEP_FINE = (3 * Math.PI) / 180;
const ANGLE_RANGE_FINE = (9 * Math.PI) / 180;
/** Share of the chord used for the min-thickness scan. */
const CENTRAL_PART = 0.6;
/** Required share of sampled text-box points inside the mask. */
const INSIDE_SHARE = 0.97;
/** Font shrink factor while the box does not fit the mask. */
const SHRINK = 0.88;
/** Fallback monospace advance, em (canvas unavailable: tests/SSR). */
const FALLBACK_ADVANCE_EM = 0.6;

export interface PlacedStateName {
  /** `${stateKey}:${groupIndex}` — React key. */
  key: string;
  stateKey: string;
  text: string;
  /** Resolved text colour. */
  color: string;
  /** Text centre, map units. */
  x: number;
  y: number;
  /** Baseline angle from horizontal, degrees, in (−90, 90]. */
  angleDeg: number;
  /** Font size in map units (scales with the map). */
  fontSize: number;
  letterSpacingEm: number;
  /** Rotated text box extents, map units. */
  width: number;
  height: number;
  /** Total state area — overlap priority. */
  area: number;
  groupArea: number;
  /** Effective bend of the drawn arc (sagitta ÷ chord, signed; map2_7a). */
  bend: number;
  /** Quadratic-Bézier baseline in map units for the <textPath>. */
  path: { x0: number; y0: number; cx: number; cy: number; x1: number; y1: number };
  /** Placement signature the cache entry was built under. */
  sig: string;
}

interface Mask {
  w: number;
  h: number;
  x0: number;
  y0: number;
  cell: number;
  px: Uint8Array;
}

/** Measure the bundled monospace advance once per family. */
export function measureMonoAdvance(family: string): number {
  if (typeof document === 'undefined') {
    return FALLBACK_ADVANCE_EM;
  }
  try {
    const ctx = document.createElement('canvas').getContext('2d');
    if (ctx === null) {
      return FALLBACK_ADVANCE_EM;
    }
    ctx.font = `400 64px ${family}`;
    // A mixed probe keeps the advance honest even if a family ever
    // ships a non-uniform cut.
    const probe = 'ЁЖШ00MW—il';
    return ctx.measureText(probe).width / probe.length / 64;
  } catch {
    return FALLBACK_ADVANCE_EM;
  }
}

/**
 * Parse a geometry path (`M x y … Z` segments — the pipeline emits
 * only M/L/Z) into rings of [x, y] map-unit points. Unknown commands
 * degrade to coordinate-pair reading, which is safe for straight-line
 * geometry.
 */
export function parsePathRings(d: string): Point[][] {
  const rings: Point[][] = [];
  for (const seg of d.split(/[Mm]/)) {
    const body = seg.replace(/[Zz]/g, ' ').trim();
    if (body === '') {
      continue;
    }
    const nums = body
      .split(/[\s,]+/)
      .map(Number)
      .filter((v) => Number.isFinite(v));
    const ring: Point[] = [];
    for (let i = 0; i + 1 < nums.length; i += 2) {
      ring.push({ x: nums[i], y: nums[i + 1] });
    }
    if (ring.length >= 3) {
      rings.push(ring);
    }
  }
  return rings;
}

/** Even-odd (XOR) scanline fill of every ring into the mask. */
function rasterise(rings: Point[][], g: Mask): void {
  for (const ring of rings) {
    let yMin = Infinity;
    let yMax = -Infinity;
    const gx: number[] = new Array(ring.length);
    const gy: number[] = new Array(ring.length);
    for (let i = 0; i < ring.length; i++) {
      gx[i] = (ring[i].x - g.x0) / g.cell;
      gy[i] = (ring[i].y - g.y0) / g.cell;
      if (gy[i] < yMin) {
        yMin = gy[i];
      }
      if (gy[i] > yMax) {
        yMax = gy[i];
      }
    }
    const j0 = Math.max(0, Math.floor(yMin - 0.5));
    const j1 = Math.min(g.h - 1, Math.ceil(yMax - 0.5));
    for (let j = j0; j <= j1; j++) {
      const y = j + 0.5;
      const xs: number[] = [];
      for (let i = 0; i < ring.length; i++) {
        const k = (i + 1) % ring.length;
        const y1 = gy[i];
        const y2 = gy[k];
        if (y1 === y2 || y < Math.min(y1, y2) || y >= Math.max(y1, y2)) {
          continue;
        }
        xs.push(gx[i] + ((y - y1) / (y2 - y1)) * (gx[k] - gx[i]));
      }
      xs.sort((a, b) => a - b);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        const x0 = Math.max(0, Math.ceil(xs[k] - 0.5));
        const x1 = Math.min(g.w, Math.ceil(xs[k + 1] - 0.5));
        for (let i = x0; i < x1; i++) {
          g.px[j * g.w + i] ^= 1;
        }
      }
    }
  }
}

function buildMask(rings: Point[][]): Mask | null {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const ring of rings) {
    for (const p of ring) {
      if (p.x < x0) x0 = p.x;
      if (p.y < y0) y0 = p.y;
      if (p.x > x1) x1 = p.x;
      if (p.y > y1) y1 = p.y;
    }
  }
  if (!(x1 > x0) || !(y1 > y0)) {
    return null;
  }
  const cell = Math.max(x1 - x0, y1 - y0) / MASK_LONG_SIDE;
  const g: Mask = {
    w: Math.max(4, Math.ceil((x1 - x0) / cell)),
    h: Math.max(4, Math.ceil((y1 - y0) / cell)),
    x0,
    y0,
    cell,
    px: new Uint8Array(0),
  };
  g.px = new Uint8Array(g.w * g.h);
  rasterise(rings, g);
  return g;
}

const inside = (g: Mask, x: number, y: number): boolean =>
  x >= 0 && y >= 0 && x < g.w && y < g.h && g.px[(y | 0) * g.w + (x | 0)] === 1;

interface ScanLine {
  /** Direction from horizontal, radians (grid space). */
  theta: number;
  /** Offset along the line normal, cells. */
  offset: number;
  /** Inside-run extent along the direction, cells (on the ARC when
   *  bent — t is the chord parameter). */
  t0: number;
  t1: number;
  /** Min perpendicular thickness over the run's central part, cells. */
  thickness: number;
  /** Worst-case distance to the nearer mask edge over the central part —
   *  how centred the line is inside the strip, cells. */
  clear: number;
  /** Signed sagitta fraction of the chord span (map2_7a; 0 = straight).
   *  The sign says to which side of the chord (+dn/−dn) the arc bows. */
  bend: number;
  /** Chord parameter span the arc parabola is defined over. */
  e0: number;
  e1: number;
}

/** Parabolic arc height above the chord at parameter t, cells. */
const arcRise = (t: number, e0: number, e1: number, sag: number): number => {
  const u = (t - e0) / (e1 - e0);
  return 4 * sag * u * (1 - u);
};

/** dh/dt of arcRise — the arc's slope along the chord direction. */
const arcSlope = (t: number, e0: number, e1: number, sag: number): number => {
  const u = (t - e0) / (e1 - e0);
  return ((4 * sag) / (e1 - e0)) * (1 - 2 * u);
};

/** Arc point in grid cells: chord point + rise along the normal. */
const arcPos = (
  du: Point,
  dn: Point,
  o: number,
  t: number,
  e0: number,
  e1: number,
  sag: number,
): Point => {
  const oo = o + arcRise(t, e0, e1, sag);
  return { x: oo * dn.x + t * du.x, y: oo * dn.y + t * du.y };
};

/** Unit normal of the arc at parameter t (rotated −90° of the tangent). */
const arcNormal = (
  du: Point,
  dn: Point,
  t: number,
  e0: number,
  e1: number,
  sag: number,
): Point => {
  const s = arcSlope(t, e0, e1, sag);
  const tx = du.x + s * dn.x;
  const ty = du.y + s * dn.y;
  const m = Math.hypot(tx, ty) || 1;
  return { x: -ty / m, y: tx / m };
};

/**
 * One scan line at (theta, offset): the straight inside-run plus — for
 * `maxBend > 0` — the same chord tried as a gentle arc. The chord span
 * for the arc is the whole inside extent of the line (first run start
 * → last run end): on a crescent the straight middle can sit in a bay
 * while the arc dips back into the territory, so a bent run may span
 * gaps the straight run never could. Scored per run
 * `len × min(thickness, len)`; ties prefer the smaller |bend|.
 */
function scanLine(
  g: Mask,
  theta: number,
  o: number,
  maxBend: number,
  maxAngle: number,
  scoreFloor: number,
  tryBends: boolean,
): ScanLine | null {
  const du = { x: Math.cos(theta), y: Math.sin(theta) };
  const dn = { x: -du.y, y: du.x };
  const corners = [
    { x: 0, y: 0 },
    { x: g.w, y: 0 },
    { x: 0, y: g.h },
    { x: g.w, y: g.h },
  ];
  let tLo = Infinity;
  let tHi = -Infinity;
  for (const c of corners) {
    const t = c.x * du.x + c.y * du.y;
    if (t < tLo) tLo = t;
    if (t > tHi) tHi = t;
  }
  const limit = g.w + g.h;

  // All inside-runs along the chord line.
  const runs: { t0: number; t1: number }[] = [];
  let runStart: number | null = null;
  for (let t = tLo; t <= tHi; t += SCAN_STEP) {
    const x = o * dn.x + t * du.x;
    const y = o * dn.y + t * du.y;
    if (inside(g, x, y)) {
      if (runStart === null) {
        runStart = t;
      }
    } else if (runStart !== null) {
      runs.push({ t0: runStart, t1: t });
      runStart = null;
    }
  }
  if (runStart !== null) {
    runs.push({ t0: runStart, t1: tHi });
  }
  let longest: { t0: number; t1: number } | null = null;
  for (const r of runs) {
    if (longest === null || r.t1 - r.t0 > longest.t1 - longest.t0) {
      longest = r;
    }
  }
  if (longest === null || longest.t1 - longest.t0 < 4) {
    return null;
  }

  // Min thickness / clearance over a run's central part, measured along
  // the local arc normal (identical to ±dn for a straight line).
  const profile = (t0: number, t1: number, e0: number, e1: number, sag: number) => {
    const L = t1 - t0;
    const a = t0 + (L * (1 - CENTRAL_PART)) / 2;
    const b = t1 - (L * (1 - CENTRAL_PART)) / 2;
    let thickness = Infinity;
    let clear = Infinity;
    for (let i = 0; i < 7; i++) {
      const t = a + ((b - a) * i) / 6;
      const p = arcPos(du, dn, o, t, e0, e1, sag);
      const n = arcNormal(du, dn, t, e0, e1, sag);
      let s = 0;
      while (s < limit && inside(g, p.x + s * n.x, p.y + s * n.y)) {
        s += SCAN_STEP;
      }
      const up = s;
      s = 0;
      while (s < limit && inside(g, p.x - s * n.x, p.y - s * n.y)) {
        s += SCAN_STEP;
      }
      const out = up + s;
      if (out < thickness) {
        thickness = out;
      }
      const half = Math.min(up, s);
      if (half < clear) {
        clear = half;
      }
    }
    return { thickness, clear };
  };

  const mkLine = (
    t0: number,
    t1: number,
    bend: number,
    e0: number,
    e1: number,
  ): ScanLine => {
    const prof = profile(t0, t1, e0, e1, bend * (e1 - e0));
    return {
      theta,
      offset: o,
      t0,
      t1,
      thickness: prof.thickness,
      clear: prof.clear,
      bend,
      e0,
      e1,
    };
  };
  const scoreOf = (l: ScanLine): number => {
    const len = l.t1 - l.t0;
    return len * Math.min(l.thickness, len);
  };

  let best = mkLine(longest.t0, longest.t1, 0, longest.t0, longest.t1);

  // Bend trials only on multi-run chords: a single-run chord is fully
  // inside, so an arc can never lengthen the run — the marginal
  // thickness gain it could find is already covered by the
  // neighbouring offsets of the grid. On a crescent or a state split
  // by a bay the chord exits in the middle and the arc can span the
  // gap — that is where the sagitta earns its keep.
  if (tryBends && maxBend > 0 && runs.length > 1) {
    const e0 = runs[0].t0;
    const e1 = runs[runs.length - 1].t1;
    const span = e1 - e0;
    // An arc run can span at most the whole extent and its thickness
    // rarely exceeds ~2.5× the straight run's — below that bound even
    // a perfect arc loses, so the four arc scans are skipped.
    const bound =
      span * Math.min(span, 2.5 * Math.max(1, best.thickness));
    if (
      span >= 4 &&
      bound > Math.max(scoreOf(best), scoreFloor) + 1e-9
    ) {
      const bestScore = () => scoreOf(best);
      for (const bf of [0.5, -0.5, 1, -1]) {
        const sag = bf * maxBend * span;
        // Longest inside-run ALONG THE ARC (gaps of the chord where
        // the arc stays inside count as continuous). Step 1 cell —
        // mask-level precision is enough for scoring.
        let arcBest: { t0: number; t1: number } | null = null;
        let rs: number | null = null;
        for (let t = e0; t <= e1; t += 1) {
          const p = arcPos(du, dn, o, t, e0, e1, sag);
          if (inside(g, p.x, p.y)) {
            if (rs === null) {
              rs = t;
            }
          } else if (rs !== null) {
            if (arcBest === null || t - rs > arcBest.t1 - arcBest.t0) {
              arcBest = { t0: rs, t1: t };
            }
            rs = null;
          }
        }
        if (
          rs !== null &&
          (arcBest === null || e1 - rs > arcBest.t1 - arcBest.t0)
        ) {
          arcBest = { t0: rs, t1: e1 };
        }
        if (arcBest === null || arcBest.t1 - arcBest.t0 < 4) {
          continue;
        }
        const lenArc = arcBest.t1 - arcBest.t0;
        // Skip the profile when the arc run cannot outscore the
        // current best even at thickness = length.
        if (lenArc * lenArc <= Math.max(bestScore(), scoreFloor)) {
          continue;
        }
        // The angle limit applies to the chord between the run's
        // ends — a bent run whose ends tilt the chord past
        // max_angle_deg is not a candidate.
        const pa = arcPos(du, dn, o, arcBest.t0, e0, e1, sag);
        const pb = arcPos(du, dn, o, arcBest.t1, e0, e1, sag);
        const chordAng = Math.atan2(pb.y - pa.y, pb.x - pa.x);
        if (Math.abs(chordAng) > maxAngle + 1e-9) {
          continue;
        }
        const line = mkLine(
          arcBest.t0,
          arcBest.t1,
          bf * maxBend,
          e0,
          e1,
        );
        const s = scoreOf(line);
        const bs = bestScore();
        if (
          s > bs + 1e-9 ||
          (s >= bs - 1e-9 && Math.abs(line.bend) < Math.abs(best.bend))
        ) {
          best = line;
        }
      }
    }
  }
  return best;
}

/** Within this share of the best score the most horizontal line wins —
 *  a rectangle reads better level than at a cosmetic 10° tilt. */
const FLAT_PREFERENCE = 0.2;

/** Score a direction/offset grid; returns the best line or null. */
function searchLines(
  g: Mask,
  thetaFrom: number,
  thetaTo: number,
  thetaStep: number,
  offsetCentre: number | null,
  offsetHalfRange: number,
  offsetStep: number,
  maxBend: number,
  maxAngle: number,
  bendStride: number,
): ScanLine | null {
  const corners = [
    { x: 0, y: 0 },
    { x: g.w, y: 0 },
    { x: 0, y: g.h },
    { x: g.w, y: g.h },
  ];
  const scored: { line: ScanLine; score: number }[] = [];
  let maxScore = -1;
  for (let th = thetaFrom; th <= thetaTo + 1e-9; th += thetaStep) {
    const dn = { x: -Math.sin(th), y: Math.cos(th) };
    let oLo = Infinity;
    let oHi = -Infinity;
    for (const c of corners) {
      const o = c.x * dn.x + c.y * dn.y;
      if (o < oLo) oLo = o;
      if (o > oHi) oHi = o;
    }
    const lo =
      offsetCentre === null
        ? oLo
        : Math.max(oLo, offsetCentre - offsetHalfRange);
    const hi =
      offsetCentre === null
        ? oHi
        : Math.min(oHi, offsetCentre + offsetHalfRange);
    let oIndex = 0;
    for (let o = lo; o <= hi + 1e-9; o += offsetStep, oIndex++) {
      // Bend trials every bendStride-th chord: the coarse grid only
      // needs to DISCOVER curvature (the refine pass retries all five
      // sagittae around the winner at its fine offsets).
      const tryBends = bendStride <= 1 || oIndex % bendStride === 0;
      const line = scanLine(
        g,
        th,
        o,
        maxBend,
        maxAngle,
        maxScore,
        tryBends,
      );
      if (line === null || line.thickness <= 0) {
        continue;
      }
      const len = line.t1 - line.t0;
      // Cap the thickness term at the run length: a transverse chord
      // through a long strip reads the strip's LENGTH as its
      // perpendicular extent, which would tie it with the proper
      // longitudinal line — the cap breaks that symmetry toward the
      // longest comfortable direction.
      const score = len * Math.min(line.thickness, len);
      scored.push({ line, score });
      if (score > maxScore) {
        maxScore = score;
      }
    }
  }
  if (maxScore <= 0) {
    return null;
  }
  const floor = maxScore * (1 - FLAT_PREFERENCE);
  let best: ScanLine | null = null;
  for (const { line, score } of scored) {
    if (score < floor) {
      continue;
    }
    // Most horizontal first; on the same angle, the line most centred
    // in the strip (largest clearance to the nearer edge).
    if (
      best === null ||
      Math.abs(line.theta) < Math.abs(best.theta) - 1e-9 ||
      (Math.abs(Math.abs(line.theta) - Math.abs(best.theta)) <= 1e-9 &&
        line.clear > best.clear)
    ) {
      best = line;
    }
  }
  return best;
}

/**
 * Share of sampled text-box points inside the mask, sampled along the
 * (possibly bent) baseline: 13 stations along the arc × 7 rows across
 * the box height along the local arc normal. `arcP(t)`/`arcN(t)` give
 * the baseline point and unit normal at chord parameter t.
 */
function arcCoverage(
  g: Mask,
  arcP: (t: number) => Point,
  arcN: (t: number) => Point,
  tCentre: number,
  halfLen: number,
  halfH: number,
): number {
  let inCount = 0;
  let total = 0;
  for (let i = 0; i <= 12; i++) {
    const t = tCentre - halfLen + ((2 * halfLen * i) / 12);
    const p = arcP(t);
    const n = arcN(t);
    for (let j = 0; j <= 6; j++) {
      const v = (j / 6 - 0.5) * 2 * halfH;
      total += 1;
      if (inside(g, p.x + v * n.x, p.y + v * n.y)) {
        inCount += 1;
      }
    }
  }
  return total === 0 ? 0 : inCount / total;
}

/** Thickness (cells) across the run part the text actually occupies,
 *  measured along the local arc normal. */
function thicknessOverArc(
  g: Mask,
  arcP: (t: number) => Point,
  arcN: (t: number) => Point,
  tCentre: number,
  halfLen: number,
): number {
  const limit = g.w + g.h;
  let min = Infinity;
  for (let i = 0; i < 9; i++) {
    const t = tCentre - halfLen + (2 * halfLen * i) / 8;
    const p = arcP(t);
    const n = arcN(t);
    let out = 0;
    let s = 0;
    while (s < limit && inside(g, p.x + s * n.x, p.y + s * n.y)) {
      s += SCAN_STEP;
    }
    out += s;
    s = 0;
    while (s < limit && inside(g, p.x - s * n.x, p.y - s * n.y)) {
      s += SCAN_STEP;
    }
    out += s;
    if (out < min) {
      min = out;
    }
  }
  return min;
}

/**
 * Fit one inscription inside a territory.
 *
 * `rings` — map-unit polygons of the group (province fill rings, holes
 * included); `text` — the display string; `widthEm` — advance width of
 * the whole string at font-size 1 em and zero letter-spacing;
 * `minFontSize` — map units below which the inscription can never be
 * readable (`states.min_px` at the camera's top scale).
 *
 * Returns map-unit geometry, or null when nothing readable fits.
 */
export function placeStateLabel(
  rings: Point[][],
  text: string,
  widthEm: number,
  rules: MapStatesRulesDTO,
  minFontSize: number,
): Omit<PlacedStateName, 'key' | 'stateKey' | 'text' | 'color' | 'area' | 'groupArea' | 'sig'> | null {
  const g = buildMask(rings);
  const n = Math.max(1, Array.from(text).length);
  if (g === null || !(widthEm > 0)) {
    return null;
  }
  const gaps = Math.max(1, n - 1);
  const maxAngle = (rules.max_angle_deg * Math.PI) / 180;

  const coarse = searchLines(
    g,
    -maxAngle,
    maxAngle,
    ANGLE_STEP,
    null,
    0,
    OFFSET_STEP,
    rules.max_bend,
    maxAngle,
    2,
  );
  if (coarse === null) {
    return null;
  }
  const refined =
    searchLines(
      g,
      Math.max(-maxAngle, coarse.theta - ANGLE_RANGE_FINE),
      Math.min(maxAngle, coarse.theta + ANGLE_RANGE_FINE),
      ANGLE_STEP_FINE,
      coarse.offset,
      2,
      OFFSET_STEP_FINE,
      rules.max_bend,
      maxAngle,
      1,
    ) ?? coarse;

  const theta = refined.theta;
  const du = { x: Math.cos(theta), y: Math.sin(theta) };
  const dn = { x: -du.y, y: du.x };
  // The inscription's baseline: a straight chord or a gentle parabolic
  // arc of sagitta `bend × chord span` (map2_7a).
  const arcSpan = Math.max(1e-9, refined.e1 - refined.e0);
  const sag = refined.bend * arcSpan; // cells, signed
  const arcP = (t: number): Point =>
    arcPos(du, dn, refined.offset, t, refined.e0, refined.e1, sag);
  const arcN = (t: number): Point =>
    arcNormal(du, dn, t, refined.e0, refined.e1, sag);
  const tCentre = (refined.t0 + refined.t1) / 2;
  const L = (refined.t1 - refined.t0) * g.cell; // free length, map units

  // Local thickness under the text extent (the run's central part is
  // the first estimate; re-measure once the text width is known).
  let thickness = refined.thickness * g.cell;

  const targetLen = rules.length_ratio * L;
  const lsMax = rules.max_letter_spacing_em;
  // The font size honours two caps: the local thickness (the box must
  // stay inside the strip) and the free length of the UNSPACED glyphs
  // (too long a name shrinks). Letter-spacing then fills the target
  // length — it widens, it never shrinks the font.
  let fontSize = Math.min(
    (rules.thickness_ratio * thickness) / BOX_HEIGHT_EM,
    targetLen / widthEm,
  );
  let ls = Math.min(
    lsMax,
    Math.max(0, targetLen / fontSize - widthEm) / gaps,
  );
  let W = fontSize * (widthEm + ls * gaps);
  // Re-measure thickness across the text extent once — a tapering
  // shape can be thinner under the text than across the whole run.
  const t2 = thicknessOverArc(g, arcP, arcN, tCentre, (W / g.cell) / 2);
  if (t2 * g.cell < thickness) {
    thickness = Math.max(0, t2 * g.cell);
    fontSize = Math.min(
      fontSize,
      (rules.thickness_ratio * thickness) / BOX_HEIGHT_EM,
      targetLen / widthEm,
    );
    ls = Math.min(lsMax, Math.max(0, targetLen / fontSize - widthEm) / gaps);
    W = fontSize * (widthEm + ls * gaps);
  }

  let H = fontSize * BOX_HEIGHT_EM;
  while (
    arcCoverage(g, arcP, arcN, tCentre, (W / g.cell) / 2, (H / g.cell) / 2) <
    INSIDE_SHARE
  ) {
    fontSize *= SHRINK;
    W = fontSize * (widthEm + ls * gaps);
    H = fontSize * BOX_HEIGHT_EM;
    if (fontSize < minFontSize) {
      return null;
    }
  }
  if (fontSize < minFontSize) {
    return null;
  }

  // The drawn baseline is the text-length slice of the arc — itself a
  // parabola, so one quadratic Bézier reproduces it exactly:
  // B(0.5) = (P0 + 2C + P1)/4 → C = 2·M − (P0 + P1)/2.
  const tA = tCentre - W / g.cell / 2;
  const tB = tCentre + W / g.cell / 2;
  const p0 = arcP(tA);
  const p1 = arcP(tB);
  const pm = arcP(tCentre);
  const ctrl = {
    x: 2 * pm.x - (p0.x + p1.x) / 2,
    y: 2 * pm.y - (p0.y + p1.y) / 2,
  };
  const mid = { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
  const chordLen = Math.hypot(p1.x - p0.x, p1.y - p0.y);
  const side =
    Math.sign((pm.x - mid.x) * dn.x + (pm.y - mid.y) * dn.y) || 0;
  const bend =
    chordLen > 0
      ? (side * Math.hypot(pm.x - mid.x, pm.y - mid.y)) / chordLen
      : 0;

  const toMap = (p: Point) => ({
    x: g.x0 + p.x * g.cell,
    y: g.y0 + p.y * g.cell,
  });
  const P0 = toMap(p0);
  const P1 = toMap(p1);
  const C = toMap(ctrl);
  const Cm = toMap(pm);

  // SVG-y is down, grid-y is down — the chord angle IS the SVG
  // orientation; clamp into (−90, 90] so the text never reads
  // upside down.
  let angleDeg = (Math.atan2(p1.y - p0.y, p1.x - p0.x) * 180) / Math.PI;
  if (angleDeg > 90) angleDeg -= 180;
  if (angleDeg <= -90) angleDeg += 180;

  return {
    x: Cm.x,
    y: Cm.y,
    angleDeg,
    fontSize,
    letterSpacingEm: ls,
    width: W,
    height: H,
    bend,
    path: { x0: P0.x, y0: P0.y, cx: C.x, cy: C.y, x1: P1.x, y1: P1.y },
  };
}

/* ------------------------------------------------------------------ */
/* Layer-level assembly                                                */
/* ------------------------------------------------------------------ */

export interface StateSpec {
  /** Stable identity: nation id (uuid) or `#<index>` for history rows. */
  key: string;
  nation: MapNationDTO;
  /** Owned LAND province ids (valid manifest nodes only). */
  ids: number[];
}

/** nations + owners payload → per-state province lists. */
export function collectStates(
  state: MapStateDTO | null,
  validIds: { has(id: number): boolean },
): StateSpec[] {
  if (state === null) {
    return [];
  }
  const byIndex = new Map<number, number[]>();
  for (const [provinceId, nationIndex] of state.owners) {
    if (!validIds.has(provinceId)) {
      continue;
    }
    const list = byIndex.get(nationIndex);
    if (list) {
      list.push(provinceId);
    } else {
      byIndex.set(nationIndex, [provinceId]);
    }
  }
  const out: StateSpec[] = [];
  for (const [index, ids] of byIndex) {
    const nation = state.nations[index];
    if (nation === undefined || ids.length === 0) {
      continue;
    }
    out.push({ key: nation.id ?? `#${index}`, nation, ids });
  }
  return out;
}

/** sRGB relative luminance of #RRGGBB (0..1). */
export function luminance(hex: string): number {
  const m = /^#([0-9A-Fa-f]{6})$/.exec(hex);
  if (!m) {
    return 0;
  }
  const v = parseInt(m[1], 16);
  const ch = (b: number) => {
    const c = b / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return (
    0.2126 * ch((v >> 16) & 0xff) +
    0.7152 * ch((v >> 8) & 0xff) +
    0.0722 * ch(v & 0xff)
  );
}

/** Pick the inscription colour per `states.color_mode`. */
export function stateTextColor(
  colorHex: string,
  mode: MapStatesRulesDTO['color_mode'],
): string {
  if (mode === 'light') {
    return STATE_TEXT_LIGHT;
  }
  if (mode === 'dark') {
    return STATE_TEXT_DARK;
  }
  const lum = luminance(colorHex);
  const contrast = (a: number, b: number) =>
    (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  const light = contrast(lum, luminance(STATE_TEXT_LIGHT));
  const dark = contrast(lum, luminance(STATE_TEXT_DARK));
  return light >= dark ? STATE_TEXT_LIGHT : STATE_TEXT_DARK;
}

export interface StateNameCacheEntry {
  sig: string;
  names: PlacedStateName[];
}

export interface StateNameDeps {
  nodesById: Map<number, MapNodeDTO>;
  edges: MapEdgeDTO[];
  /** province id → its fill rings (map units). */
  ringsById: Map<number, Point[][]>;
  /** Monospace advance, em. */
  advanceEm: number;
  rules: MapStatesRulesDTO;
  /** Unreadable-everywhere floor, map units (min_px ÷ top scale). */
  minFontSize: number;
  /** Previous placements keyed by state key — reused on signature hit. */
  cache: Map<string, StateNameCacheEntry>;
}

export interface StateNameResult {
  names: PlacedStateName[];
  cache: Map<string, StateNameCacheEntry>;
  /** State keys whose placement ran this pass (diagnostics/tests). */
  computed: string[];
}

/** Rotated-rect overlap (SAT on the two rectangles' axes). */
export function boxesOverlap(a: PlacedStateName, b: PlacedStateName): boolean {
  const ra = (a.angleDeg * Math.PI) / 180;
  const rb = (b.angleDeg * Math.PI) / 180;
  const axes = [
    { x: Math.cos(ra), y: Math.sin(ra) },
    { x: -Math.sin(ra), y: Math.cos(ra) },
    { x: Math.cos(rb), y: Math.sin(rb) },
    { x: -Math.sin(rb), y: Math.cos(rb) },
  ];
  const cornersOf = (l: PlacedStateName, r: number) => {
    const du = { x: Math.cos(r), y: Math.sin(r) };
    const dn = { x: -du.y, y: du.x };
    const hw = l.width / 2;
    const hh = l.height / 2;
    return [
      { x: l.x + hw * du.x + hh * dn.x, y: l.y + hw * du.y + hh * dn.y },
      { x: l.x + hw * du.x - hh * dn.x, y: l.y + hw * du.y - hh * dn.y },
      { x: l.x - hw * du.x + hh * dn.x, y: l.y - hw * du.y + hh * dn.y },
      { x: l.x - hw * du.x - hh * dn.x, y: l.y - hw * du.y - hh * dn.y },
    ];
  };
  const ac = cornersOf(a, ra);
  const bc = cornersOf(b, rb);
  for (const axis of axes) {
    let aMin = Infinity;
    let aMax = -Infinity;
    let bMin = Infinity;
    let bMax = -Infinity;
    for (const p of ac) {
      const pr = p.x * axis.x + p.y * axis.y;
      if (pr < aMin) aMin = pr;
      if (pr > aMax) aMax = pr;
    }
    for (const p of bc) {
      const pr = p.x * axis.x + p.y * axis.y;
      if (pr < bMin) bMin = pr;
      if (pr > bMax) bMax = pr;
    }
    if (aMax <= bMin || bMax <= aMin) {
      return false;
    }
  }
  return true;
}

/**
 * Resolve screen-space collisions once, in map units (the rotated boxes
 * scale with the map, so overlap is zoom-invariant): when two
 * inscriptions overlap, the larger state's stays.
 */
export function resolveStateNameOverlaps(
  names: PlacedStateName[],
): PlacedStateName[] {
  if (names.length < 2) {
    return names;
  }
  const dropped = new Set<string>();
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      const a = names[i];
      const b = names[j];
      if (dropped.has(a.key) || dropped.has(b.key)) {
        continue;
      }
      if (!boxesOverlap(a, b)) {
        continue;
      }
      const loser =
        a.area !== b.area
          ? a.area < b.area
            ? a
            : b
          : a.groupArea !== b.groupArea
            ? a.groupArea < b.groupArea
              ? a
              : b
            : a.key < b.key
              ? a
              : b;
      dropped.add(loser.key);
    }
  }
  return names.filter((l) => !dropped.has(l.key));
}

/**
 * One inscription per qualifying group of every state, cached per
 * state signature (provenance set + name + colour + config + font
 * advance): an ownership change of one state recomputes only that
 * state's entries.
 */
export function placeStateNames(
  specs: StateSpec[],
  fingerprint: string,
  deps: StateNameDeps,
): StateNameResult {
  const cache = new Map<string, StateNameCacheEntry>();
  const computed: string[] = [];
  const all: PlacedStateName[] = [];

  for (const spec of specs) {
    const text = deps.rules.uppercase
      ? spec.nation.short_name.toUpperCase()
      : spec.nation.short_name;
    const ids = spec.ids.slice().sort((a, b) => a - b);
    const sig = `${fingerprint}|${spec.nation.name}|${spec.nation.color_hex}|${ids.join(',')}`;
    const hit = deps.cache.get(spec.key);
    if (hit !== undefined && hit.sig === sig) {
      cache.set(spec.key, hit);
      all.push(...hit.names);
      continue;
    }
    computed.push(spec.key);

    const nodes = spec.ids
      .map((id) => deps.nodesById.get(id))
      .filter((n): n is MapNodeDTO => n !== undefined);
    const totalArea = nodes.reduce((s, n) => s + n.area, 0);
    const color = stateTextColor(spec.nation.color_hex, deps.rules.color_mode);
    const widthEm = deps.advanceEm * Math.max(1, Array.from(text).length);
    const names: PlacedStateName[] = [];

    const groups = components(spec.ids, deps.edges);
    // Largest group always qualifies; others need the min share.
    let largest = -1;
    let largestArea = 0;
    const groupAreas = groups.map((g) =>
      g.reduce(
        (s, id) => s + (deps.nodesById.get(id)?.area ?? 0),
        0,
      ),
    );
    groupAreas.forEach((a, i) => {
      if (a > largestArea) {
        largestArea = a;
        largest = i;
      }
    });

    groups.forEach((group, gi) => {
      const share = totalArea > 0 ? groupAreas[gi] / totalArea : 0;
      if (gi !== largest && share < deps.rules.min_group_share) {
        return;
      }
      const rings: Point[][] = [];
      for (const id of group) {
        const rr = deps.ringsById.get(id);
        if (rr) {
          rings.push(...rr);
        }
      }
      const placed = placeStateLabel(
        rings,
        text,
        widthEm,
        deps.rules,
        deps.minFontSize,
      );
      if (placed !== null) {
        names.push({
          ...placed,
          key: `${spec.key}:${gi}`,
          stateKey: spec.key,
          text,
          color,
          area: totalArea,
          groupArea: groupAreas[gi],
          sig,
        });
      }
    });
    const entry: StateNameCacheEntry = { sig, names };
    cache.set(spec.key, entry);
    all.push(...names);
  }

  return {
    names: resolveStateNameOverlaps(all),
    cache,
    computed,
  };
}
