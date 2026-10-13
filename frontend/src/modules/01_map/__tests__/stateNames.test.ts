/**
 * State-name placement (map2_7): synthetic territories through
 * `placeStateLabel` — a wide rectangle stays horizontal and inside, a
 * diagonal strip tilts within the angle limit, an L-shape takes the
 * longer arm, and a territory too small for `min_px` gets nothing.
 * Plus the layer-level cache: an ownership change recomputes only the
 * touched state.
 */

import {
  collectStates,
  parsePathRings,
  placeStateLabel,
  placeStateNames,
  stateTextColor,
  type StateNameDeps,
} from '../lib/stateNames';
import {
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_RULES,
} from '../fixtures/miniMap';
import type { MapStateDTO } from '../types';
import type { Point } from '../lib/view';

const RULES = MINI_RULES.states;
/** Every synthetic territory here is ≥ 10 map units thick. */
const MIN_FONT = 0.5;

function rect(x0: number, y0: number, x1: number, y1: number): Point[] {
  return [
    { x: x0, y: y0 },
    { x: x1, y: y0 },
    { x: x1, y: y1 },
    { x: x0, y: y1 },
  ];
}

/** Point-in-polygon (ray cast) for the synthetic rings. */
function inside(rings: Point[][], x: number, y: number): boolean {
  let insideAny = false;
  for (const ring of rings) {
    let inRing = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i];
      const b = ring[j];
      if (
        a.y > y !== b.y > y &&
        x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x
      ) {
        inRing = !inRing;
      }
    }
    insideAny = insideAny !== inRing;
  }
  return insideAny;
}

/** Curved text-box coverage against the true (non-rasterised) rings:
 *  the baseline is the quadratic Bézier `placed.path` (map2_7a), rows
 *  run along the local normal. */
function boxInsideShare(
  rings: Point[][],
  placed: {
    path: { x0: number; y0: number; cx: number; cy: number; x1: number; y1: number };
    height: number;
  },
): number {
  const { x0, y0, cx, cy, x1, y1 } = placed.path;
  const B = (u: number) => ({
    x: (1 - u) * (1 - u) * x0 + 2 * (1 - u) * u * cx + u * u * x1,
    y: (1 - u) * (1 - u) * y0 + 2 * (1 - u) * u * cy + u * u * y1,
  });
  const N = (u: number) => {
    const tx = 2 * (1 - u) * (cx - x0) + 2 * u * (x1 - cx);
    const ty = 2 * (1 - u) * (cy - y0) + 2 * u * (y1 - cy);
    const m = Math.hypot(tx, ty) || 1;
    return { x: -ty / m, y: tx / m };
  };
  let hit = 0;
  let total = 0;
  for (let i = 0; i <= 12; i++) {
    const p = B(i / 12);
    const n = N(i / 12);
    for (let j = 0; j <= 6; j++) {
      const v = (j / 6 - 0.5) * placed.height;
      total += 1;
      if (inside(rings, p.x + v * n.x, p.y + v * n.y)) {
        hit += 1;
      }
    }
  }
  return hit / total;
}

describe('placeStateLabel — synthetic territories', () => {
  it('wide rectangle: horizontal line, box inside', () => {
    const rings = [rect(0, 0, 100, 30)];
    const placed = placeStateLabel(rings, 'ТЕСТИЯ', 0.6 * 6, RULES, MIN_FONT);
    expect(placed).not.toBeNull();
    expect(Math.abs(placed!.angleDeg)).toBeLessThanOrEqual(5);
    // ~80 % of the free length at wide letter spacing.
    expect(placed!.width).toBeGreaterThan(60);
    expect(placed!.letterSpacingEm).toBeGreaterThan(0);
    expect(boxInsideShare(rings, placed!)).toBeGreaterThanOrEqual(0.97);
  });

  it('long diagonal strip: angle follows the strip within the limit', () => {
    // A 130×24 strip rotated 45°, handed in as its real polygon.
    const a = (45 * Math.PI) / 180;
    const u = { x: Math.cos(a), y: Math.sin(a) };
    const n = { x: -u.y, y: u.x };
    const corner = (uOff: number, nOff: number): Point => ({
      x: 200 + uOff * u.x + nOff * n.x,
      y: 200 + uOff * u.y + nOff * n.y,
    });
    const rings = [
      [corner(-65, -12), corner(65, -12), corner(65, 12), corner(-65, 12)],
    ];
    const placed = placeStateLabel(rings, 'ДИАГОНАЛЬ', 0.6 * 9, RULES, MIN_FONT);
    expect(placed).not.toBeNull();
    expect(Math.abs(placed!.angleDeg - 45)).toBeLessThanOrEqual(8);
    expect(boxInsideShare(rings, placed!)).toBeGreaterThanOrEqual(0.97);
  });

  it('L-shape: the longer arm hosts a horizontal inscription', () => {
    const rings = [rect(0, 0, 80, 10), rect(0, 0, 10, 50)];
    const placed = placeStateLabel(rings, 'УГОЛОК', 0.6 * 6, RULES, MIN_FONT);
    expect(placed).not.toBeNull();
    expect(Math.abs(placed!.angleDeg)).toBeLessThanOrEqual(8);
    // The long arm's midline.
    expect(placed!.y).toBeGreaterThan(0);
    expect(placed!.y).toBeLessThan(10);
    expect(boxInsideShare(rings, placed!)).toBeGreaterThanOrEqual(0.97);
  });

  it('crescent: the inscription bends gently along the arc', () => {
    // Annular sector (a rainbow band): outer R=200, inner R=170,
    // angle span 45°..135° — the straight chord across it exits the
    // band in the middle, so the arc wins.
    const crescent: Point[] = [];
    for (let i = 0; i <= 40; i++) {
      const t = ((45 + (90 * i) / 40) * Math.PI) / 180;
      crescent.push({ x: 200 * Math.cos(t), y: 200 * Math.sin(t) });
    }
    for (let i = 40; i >= 0; i--) {
      const t = ((45 + (90 * i) / 40) * Math.PI) / 180;
      crescent.push({ x: 170 * Math.cos(t), y: 170 * Math.sin(t) });
    }
    const rings = [crescent];
    const placed = placeStateLabel(
      rings,
      'СЕРПОЛАНДИЯ',
      0.6 * 10,
      RULES,
      MIN_FONT,
    );
    expect(placed).not.toBeNull();
    expect(Math.abs(placed!.bend)).toBeGreaterThanOrEqual(0.03);
    expect(Math.abs(placed!.bend)).toBeLessThanOrEqual(0.1);
    expect(boxInsideShare(rings, placed!)).toBeGreaterThanOrEqual(0.97);
  });

  it('rectangle: no bend (straight baseline)', () => {
    const rings = [rect(0, 0, 100, 30)];
    const placed = placeStateLabel(rings, 'ТЕСТИЯ', 0.6 * 6, RULES, MIN_FONT);
    expect(placed).not.toBeNull();
    expect(placed!.bend).toBe(0);
  });

  it('tiny territory: nothing below the min_px floor', () => {
    const rings = [rect(0, 0, 4, 4)];
    // minFontSize above anything a 4×4 patch can host.
    expect(
      placeStateLabel(rings, 'КРОХА', 0.6 * 5, RULES, 10),
    ).toBeNull();
  });
});

describe('placeStateNames — groups and caching', () => {
  const nodesById = new Map(MINI_MANIFEST.nodes.map((n) => [n.id, n]));
  const ringsById = new Map(
    MINI_MANIFEST.nodes.map((n) => [n.id, parsePathRings(MINI_GEOMETRY.paths[n.id] ?? '')]),
  );
  const state: MapStateDTO = {
    geometry_version: 'mini01',
    borders_version: 'minib01',
    turn: 3,
    nations: [
      { id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d', name: 'Альфа-Тест', color_hex: '#e64545' },
      { id: 'b2c3d4e5-0000-4b7e-9a1c-2e5f7a9b0c1d', name: 'Бета', color_hex: '#2b6cb0' },
    ],
    owners: [
      [1001, 0],
      [1002, 0],
      [1008, 0], // detached share of nation A — second group
      [1003, 1],
      [1004, 1],
    ],
  };
  const deps = (): StateNameDeps => ({
    nodesById,
    edges: MINI_MANIFEST.edges,
    ringsById,
    advanceEm: 0.6,
    rules: RULES,
    minFontSize: 0.05,
    cache: new Map(),
  });

  it('one inscription per group meeting the share rule', () => {
    const result = placeStateNames(
      collectStates(state, nodesById),
      'fp',
      deps(),
    );
    const aKeys = result.names
      .filter((l) => l.text === 'АЛЬФА-ТЕСТ')
      .map((l) => l.key);
    // Nation A: mainland {1001,1002} (largest) + detached {1008}
    // (36/236 ≈ 0.15 < 0.2 share → dropped) = one inscription.
    expect(aKeys).toHaveLength(1);
    expect(
      result.names.filter((l) => l.text === 'БЕТА'),
    ).toHaveLength(1);
    for (const l of result.names) {
      expect(l.text).toBe(l.text.toUpperCase());
      expect(Math.abs(l.angleDeg)).toBeLessThanOrEqual(90);
    }
  });

  it('recomputes only the state whose ownership changed', () => {
    const specs = collectStates(state, nodesById);
    const first = placeStateNames(specs, 'fp', deps());
    const next: MapStateDTO = {
      ...state,
      owners: [...state.owners, [1005, 1]], // nation B gains a province
    };
    const second = placeStateNames(
      collectStates(next, nodesById),
      'fp',
      { ...deps(), cache: first.cache },
    );
    expect(second.computed).toEqual([
      'b2c3d4e5-0000-4b7e-9a1c-2e5f7a9b0c1d',
    ]);
  });
});

describe('stateTextColor', () => {
  it('auto picks the more contrasting tone', () => {
    expect(stateTextColor('#101014', 'auto')).toBe('#F2F3F5');
    expect(stateTextColor('#F5F5F5', 'auto')).toBe('#101014');
    expect(stateTextColor('#123456', 'light')).toBe('#F2F3F5');
    expect(stateTextColor('#123456', 'dark')).toBe('#101014');
  });
});
