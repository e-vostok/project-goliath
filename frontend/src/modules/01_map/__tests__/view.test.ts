/**
 * Pure view math (Spec 3.8): fit scale, zoom around a fixed cursor
 * point, zoom limits, pan clamp at both extremes, bbox fit, centre
 * keeping on resize.
 */

import {
  bboxCenter,
  centerOn,
  clampPan,
  fitBBox,
  fitScale,
  fitView,
  scaleBounds,
  screenToWorld,
  worldToScreen,
  zoomAtPoint,
  rescaleOnResize,
  type BBox,
} from '../lib/view';

const BBOX: BBox = [100, 50, 500, 250]; // 400 × 200 world units
const VP = { width: 800, height: 600 };

describe('fitScale / fitView', () => {
  it('fits the smaller dimension ratio', () => {
    expect(fitScale(BBOX, VP)).toBeCloseTo(2); // min(800/400, 600/200) = 2
    expect(fitScale(BBOX, { width: 400, height: 600 })).toBeCloseTo(1);
  });

  it('centres the bbox in the viewport', () => {
    const v = fitView(BBOX, VP); // s=2
    const c = worldToScreen(v, bboxCenter(BBOX));
    expect(c.x).toBeCloseTo(VP.width / 2);
    expect(c.y).toBeCloseTo(VP.height / 2);
  });

  it('returns zero on degenerate input', () => {
    expect(fitScale(BBOX, { width: 0, height: 0 })).toBe(0);
  });
});

describe('zoomAtPoint — the point under the cursor stays fixed', () => {
  const view = fitView(BBOX, VP);
  it.each([
    [{ x: 400, y: 300 }, 2],
    [{ x: 0, y: 0 }, 1.25],
    [{ x: 800, y: 600 }, 0.8],
    [{ x: 137, y: 419 }, 4],
    [{ x: 751, y: 33 }, 0.5],
  ])('cursor %o, scale ×%s', (cursor, factor) => {
    const before = screenToWorld(view, cursor);
    const next = zoomAtPoint(view, cursor, view.s * factor);
    const after = screenToWorld(next, cursor);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });
});

describe('scaleBounds / zoom limits', () => {
  it('bounds scale by s_fit · zoom', () => {
    const [min, max] = scaleBounds(2, 1, 16);
    expect(min).toBe(2);
    expect(max).toBe(32);
  });
});

describe('clampPan — pan margin at both extremes', () => {
  const mu = 0.1;
  const view = { s: 2, tx: 0, ty: 0 };

  it('clamps a drag far to the right (bbox left edge past the margin)', () => {
    const clamped = clampPan({ ...view, tx: 10000 }, BBOX, VP, mu);
    // t_x ≤ −s·x0 + μ·W_v = -200 + 80 = -120
    expect(clamped.tx).toBeCloseTo(-120);
  });

  it('clamps a drag far to the left (bbox right edge past the margin)', () => {
    const clamped = clampPan({ ...view, tx: -10000 }, BBOX, VP, mu);
    // t_x ≥ W_v − s·x1 − μ·W_v = 800 − 1000 − 80 = -280
    expect(clamped.tx).toBeCloseTo(-280);
  });

  it('clamps vertically at both ends (zoomed-in view)', () => {
    const zoomed = { ...view, s: 4 }; // bbox 4·200 = 800 > 600 — non-empty band
    const up = clampPan({ ...zoomed, ty: 9999 }, BBOX, VP, mu);
    // t_y ≤ −s·y0 + μ·H_v = −200 + 60 = −140
    expect(up.ty).toBeCloseTo(-140);
    const down = clampPan({ ...zoomed, ty: -9999 }, BBOX, VP, mu);
    // t_y ≥ H_v − s·y1 − μ·H_v = 600 − 1000 − 60 = −460
    expect(down.ty).toBeCloseTo(-460);
  });

  it('centres content smaller than the viewport (empty clamp band)', () => {
    // s=2 → bbox height 400 < 600: the band inverts, midpoint = centred.
    const v = clampPan({ ...view, ty: 9999 }, BBOX, VP, mu);
    expect(v.ty).toBeCloseTo((600 - 2 * (50 + 250)) / 2); // = 0
  });

  it('leaves a legal transform untouched', () => {
    const legal = fitView(BBOX, VP);
    expect(clampPan(legal, BBOX, VP, mu)).toEqual(legal);
  });
});

describe('fitBBox — search-result focus', () => {
  it('fits a node bbox with margin, clamped to zoom bounds', () => {
    const node: BBox = [200, 100, 240, 140]; // 40×40
    const v = fitBBox(node, VP, 1.2, 2, 32);
    // fit = min(800/40, 600/40)/1.2 = 15/1.2 = 12.5 → within bounds
    expect(v.s).toBeCloseTo(12.5);
    const c = worldToScreen(v, bboxCenter(node));
    expect(c.x).toBeCloseTo(400);
    expect(c.y).toBeCloseTo(300);
  });

  it('clamps to sMax when the node is tiny', () => {
    const node: BBox = [200, 100, 201, 101];
    const v = fitBBox(node, VP, 1.2, 2, 32);
    expect(v.s).toBe(32);
  });

  it('clamps to sMin when the node is huge', () => {
    const node: BBox = [0, 0, 10000, 10000];
    const v = fitBBox(node, VP, 1.2, 2, 32);
    expect(v.s).toBe(2);
  });
});

describe('centerOn — neighbour navigation', () => {
  it('keeps the current scale and centres the point', () => {
    const view = { s: 8, tx: 0, ty: 0 };
    const next = centerOn(view, { x: 300, y: 150 }, VP, 2, 32);
    expect(next.s).toBe(8);
    const c = worldToScreen(next, { x: 300, y: 150 });
    expect(c.x).toBeCloseTo(400);
    expect(c.y).toBeCloseTo(300);
  });

  it('clamps an out-of-range scale', () => {
    const view = { s: 100, tx: 0, ty: 0 };
    expect(centerOn(view, { x: 0, y: 0 }, VP, 2, 32).s).toBe(32);
  });
});

describe('rescaleOnResize — keeps the view centre and user zoom', () => {
  it('preserves the centre world point and z across a resize', () => {
    const oldVp = { width: 800, height: 600 };
    const newVp = { width: 1920, height: 1080 };
    const view = { s: 4, tx: -300, ty: -100 }; // z = 4/2 = 2
    const centre = screenToWorld(view, { x: 400, y: 300 });

    const next = rescaleOnResize(view, BBOX, oldVp, newVp);
    const newFit = fitScale(BBOX, newVp); // min(1920/400, 1080/200)=4.8
    expect(next.s).toBeCloseTo(newFit * 2);
    const c = screenToWorld(next, {
      x: newVp.width / 2,
      y: newVp.height / 2,
    });
    expect(c.x).toBeCloseTo(centre.x);
    expect(c.y).toBeCloseTo(centre.y);
  });
});
