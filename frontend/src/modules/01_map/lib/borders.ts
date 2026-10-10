/**
 * Border-layer classification, spatial chunking and LOD (map2_4,
 * map2_13, map2_14), pure.
 *
 * `borders.json` gives one canonical polyline per adjacent land pair
 * (`pairs`, keyed "a-b") and one coastline per node (`coasts`, keyed by
 * node id — covers sea, excluded land and the map edge). The client
 * does not know which pair is a state border until ownership arrives
 * in the state payload, so the paths are classified here, not in the
 * pipeline:
 *
 * - pair → STATE when the two owners differ, counting a free province
 *   as «no owner»: owned-vs-free is a state border, free-vs-free and
 *   same-nation are INTERNAL;
 * - every coast entry → COAST, owned or free (there is no thick state
 *   line along the sea; island parts of a node are pure coast).
 *
 * Why chunks (map2_14): as three ~915 KB compound paths the browser
 * re-strokes ALL border geometry on every transform change — including
 * the 80 % far outside the viewport. The layer is therefore split into
 * a regular BORDER_GRID×BORDER_GRID cell grid over the map bounds:
 * every pair/coast piece lands in exactly one cell (chosen by its
 * bounding-box midpoint) and each class×cell is a small <path> the
 * browser can cull when the cell is off-screen.
 *
 * Why LOD: the border polylines are far denser than any zoom-out needs.
 * Two simplified copies of every piece are built once at load
 * (Douglas–Peucker): `low` and `mid`. `borderLOD` picks the coarsest
 * copy whose worst-case error stays under half a screen pixel at the
 * current scale, so the switch is never visible. `high` is the
 * untouched original geometry.
 *
 * Ownership changes call `reclassifyBorderLayer`: only the cells whose
 * pairs actually changed class are re-joined — unchanged cell strings
 * are reused by reference, so React touches no DOM for them.
 */

import type { MapBordersDTO, MapNationDTO } from '../types';
import type { BBox } from './view';

export type BorderClass = 'internal' | 'state' | 'coast';
export type BorderLOD = 'low' | 'mid' | 'high';

/** Cells per axis of the spatial chunk grid. */
export const BORDER_GRID = 8;

/** Largest allowed simplification error on screen, px — invisible. */
const LOD_MAX_ERROR_PX = 0.45;

/**
 * Simplification tolerance (world units) per LOD; `null` = original
 * geometry. `borderLOD` uses the coarsest copy whose error stays under
 * LOD_MAX_ERROR_PX at the current scale — the low copy is legal while
 * s ≤ 0.45/0.09 = 5 (zoom-out band), the mid copy while s ≤ 11.25,
 * the full geometry everywhere above.
 */
export const BORDER_LOD_TOLERANCES: ReadonlyArray<
  readonly [BorderLOD, number | null]
> = [
  ['low', 0.09],
  ['mid', 0.04],
  ['high', null],
];

export const BORDER_LODS: readonly BorderLOD[] = ['low', 'mid', 'high'];

/** The coarsest LOD whose error is under half a screen pixel at `s`. */
export function borderLOD(s: number): BorderLOD {
  for (const [lod, tol] of BORDER_LOD_TOLERANCES) {
    if (tol === null || s * tol <= LOD_MAX_ERROR_PX) {
      return lod;
    }
  }
  return 'high';
}

/* --------------------------------------------------- path parsing */

interface Subpath {
  pts: [number, number][];
  closed: boolean;
}

const PATH_TOKEN = /[a-zA-Z]|-?\d*\.?\d+(?:e[+-]?\d+)?/gi;

// Border polylines only ever carry M / implicit L / Z, but the scanner
// is lenient: any command letter is consumed, numbers attach to the
// current subpath.
function parsePath(d: string): Subpath[] {
  const subs: Subpath[] = [];
  let cur: Subpath | null = null;
  const toks = d.match(PATH_TOKEN) ?? [];
  for (let i = 0; i < toks.length; ) {
    const t = toks[i];
    if (/[a-zA-Z]/.test(t[0])) {
      const cmd = t.toUpperCase();
      i += 1;
      if (cmd === 'M') {
        cur = { pts: [], closed: false };
        subs.push(cur);
      } else if (cmd === 'Z' && cur) {
        cur.closed = true;
      }
      continue;
    }
    if (cur && i + 1 < toks.length) {
      cur.pts.push([Number(t), Number(toks[i + 1])]);
      i += 2;
    } else {
      i += 1;
    }
  }
  return subs.filter((s) => s.pts.length > 0);
}

/* ------------------------------------------------- simplification */

/** Douglas–Peucker on an open polyline; both endpoints are kept. */
function simplify(
  pts: [number, number][],
  tol: number,
): [number, number][] {
  if (pts.length <= 2) {
    return pts;
  }
  const keep = new Uint8Array(pts.length);
  keep[0] = 1;
  keep[pts.length - 1] = 1;
  const stack: [number, number][] = [[0, pts.length - 1]];
  while (stack.length > 0) {
    const [a, z] = stack.pop()!;
    const [x1, y1] = pts[a];
    const [x2, y2] = pts[z];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const invLen = 1 / (Math.hypot(dx, dy) || 1e-12);
    let max = -1;
    let at = -1;
    for (let i = a + 1; i < z; i += 1) {
      const [x, y] = pts[i];
      const dist = Math.abs(dy * x - dx * y + x2 * y1 - y2 * x1) * invLen;
      if (dist > max) {
        max = dist;
        at = i;
      }
    }
    if (max > tol) {
      keep[at] = 1;
      stack.push([a, at], [at, z]);
    }
  }
  return pts.filter((_, i) => keep[i] === 1);
}

const fmt = (v: number): string => {
  const r = Math.round(v * 100) / 100;
  return r === 0 ? '0' : String(r);
};

function emitSubpath(s: Subpath): string {
  return `M ${s.pts.map((p) => `${fmt(p[0])} ${fmt(p[1])}`).join(' ')}${
    s.closed ? ' Z' : ''
  }`;
}

/* ------------------------------------------------------- the layer */

interface BorderPiece {
  /** `d` per LOD, in BORDER_LOD_TOLERANCES order (high = original). */
  d: readonly [string, string, string];
  cell: number;
}

interface BorderLayerCtx {
  pairs: Map<string, BorderPiece>;
  /** key → class as last classified; mutated by reclassify only. */
  pairClass: Map<string, 'internal' | 'state'>;
  /** cell → pair keys whose midpoint falls in it (fixed at load). */
  pairsByCell: string[][];
}

export interface BorderLayer {
  /** The borders payload this layer was built from (identity check). */
  borders: MapBordersDTO;
  grid: number;
  /** lod → class → cell → combined `d` (null = empty cell). */
  chunks: Record<BorderLOD, Record<BorderClass, (string | null)[]>>;
  /** Incremental-rebuild bookkeeping — never rendered directly. */
  _ctx: BorderLayerCtx;
}

function cellIndex(
  subs: Subpath[],
  bounds: BBox,
  grid: number,
): number {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const s of subs) {
    for (const [x, y] of s.pts) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const w = bounds[2] > 0 ? bounds[2] : 1;
  const h = bounds[3] > 0 ? bounds[3] : 1;
  const col = Math.min(
    grid - 1,
    Math.max(0, Math.floor(((cx - bounds[0]) / w) * grid)),
  );
  const row = Math.min(
    grid - 1,
    Math.max(0, Math.floor(((cy - bounds[1]) / h) * grid)),
  );
  return row * grid + col;
}

function makePiece(d: string, bounds: BBox, grid: number): BorderPiece {
  const subs = parsePath(d);
  // d per LOD, in BORDER_LOD_TOLERANCES order — the original string
  // for the `null` (high) entry, a simplified copy otherwise.
  const ds = BORDER_LOD_TOLERANCES.map(([, tol]) =>
    tol === null
      ? d
      : subs
          .map((s) =>
            emitSubpath({ pts: simplify(s.pts, tol), closed: s.closed }),
          )
          .join(' '),
  ) as [string, string, string];
  return { d: ds, cell: cellIndex(subs, bounds, grid) };
}

const LOD_INDEX: Record<BorderLOD, 0 | 1 | 2> = { low: 0, mid: 1, high: 2 };

function emptyCells(n: number): (string | null)[] {
  return new Array<string | null>(n).fill(null);
}

function joinCells(
  pieces: string[][],
  cellCount: number,
): (string | null)[] {
  const out = emptyCells(cellCount);
  for (let c = 0; c < cellCount; c += 1) {
    if (pieces[c] !== undefined && pieces[c].length > 0) {
      out[c] = pieces[c].join(' ');
    }
  }
  return out;
}

/**
 * Full build: parse every piece once, assign cells, classify pairs
 * under `owners` and join the three classes per LOD and cell.
 */
export function buildBorderLayer(
  borders: MapBordersDTO,
  owners: ReadonlyMap<number, MapNationDTO>,
  bounds: BBox,
  grid: number = BORDER_GRID,
): BorderLayer {
  const cellCount = grid * grid;
  const ctx: BorderLayerCtx = {
    pairs: new Map(),
    pairClass: new Map(),
    pairsByCell: Array.from({ length: cellCount }, () => [] as string[]),
  };

  const acc: Record<BorderLOD, Record<'internal' | 'state', string[][]>> =
    {
      low: { internal: [], state: [] },
      mid: { internal: [], state: [] },
      high: { internal: [], state: [] },
    };

  for (const [key, d] of Object.entries(borders.pairs)) {
    const piece = makePiece(d, bounds, grid);
    ctx.pairs.set(key, piece);
    ctx.pairsByCell[piece.cell].push(key);

    const [a, b] = key.split('-').map(Number);
    const cls = owners.get(a) === owners.get(b) ? 'internal' : 'state';
    ctx.pairClass.set(key, cls);
    for (const lod of BORDER_LODS) {
      const cells = (acc[lod][cls][piece.cell] ??= []);
      cells.push(piece.d[LOD_INDEX[lod]]);
    }
  }

  const coastAcc: Record<BorderLOD, string[][]> = {
    low: [],
    mid: [],
    high: [],
  };
  for (const d of Object.values(borders.coasts)) {
    const piece = makePiece(d, bounds, grid);
    for (const lod of BORDER_LODS) {
      (coastAcc[lod][piece.cell] ??= []).push(piece.d[LOD_INDEX[lod]]);
    }
  }

  return {
    borders,
    grid,
    chunks: {
      low: {
        internal: joinCells(acc.low.internal, cellCount),
        state: joinCells(acc.low.state, cellCount),
        coast: joinCells(coastAcc.low, cellCount),
      },
      mid: {
        internal: joinCells(acc.mid.internal, cellCount),
        state: joinCells(acc.mid.state, cellCount),
        coast: joinCells(coastAcc.mid, cellCount),
      },
      high: {
        internal: joinCells(acc.high.internal, cellCount),
        state: joinCells(acc.high.state, cellCount),
        coast: joinCells(coastAcc.high, cellCount),
      },
    },
    _ctx: ctx,
  };
}

/**
 * Ownership moved: reclassify every pair (cheap — id lookups), then
 * re-join ONLY the cells that contain a pair whose class flipped.
 * Unchanged cells keep their string references, so React writes no
 * `d` attribute for them. Returns `prev` itself when nothing flipped.
 */
export function reclassifyBorderLayer(
  prev: BorderLayer,
  owners: ReadonlyMap<number, MapNationDTO>,
): BorderLayer {
  const dirty = new Set<number>();
  for (const [key, piece] of prev._ctx.pairs) {
    const [a, b] = key.split('-').map(Number);
    const cls = owners.get(a) === owners.get(b) ? 'internal' : 'state';
    if (prev._ctx.pairClass.get(key) !== cls) {
      prev._ctx.pairClass.set(key, cls);
      dirty.add(piece.cell);
    }
  }
  if (dirty.size === 0) {
    return prev;
  }

  const next: BorderLayer = {
    ...prev,
    chunks: {} as BorderLayer['chunks'],
  };
  for (const lod of BORDER_LODS) {
    next.chunks[lod] = {
      internal: prev.chunks[lod].internal.slice(),
      state: prev.chunks[lod].state.slice(),
      coast: prev.chunks[lod].coast,
    };
    for (const cell of dirty) {
      const joined: Record<'internal' | 'state', string[]> = {
        internal: [],
        state: [],
      };
      for (const key of prev._ctx.pairsByCell[cell]) {
        const cls = prev._ctx.pairClass.get(key)!;
        joined[cls].push(
          prev._ctx.pairs.get(key)!.d[LOD_INDEX[lod]],
        );
      }
      next.chunks[lod].internal[cell] =
        joined.internal.length > 0 ? joined.internal.join(' ') : null;
      next.chunks[lod].state[cell] =
        joined.state.length > 0 ? joined.state.join(' ') : null;
    }
  }
  return next;
}
