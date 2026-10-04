/**
 * Pure view math (Spec 3.8 v1.9): s_min = H_v / frame.height,
 * s = s_min·z with z ∈ [1, zoom_max]; cursor-fixed zoom; per-axis pan
 * clamp with centring when the visible axis exceeds the frame; initial
 * centred view; resize keeps z and the centre world point.
 */

import {
  bboxCenter,
  centerOn,
  clampOffset,
  fitBBox,
  fitScale,
  initialTransform,
  minScale,
  rescaleOnResize,
  scaleBounds,
  screenToWorld,
  worldToScreen,
  zoomAt,
  type BBox,
  type Frame,
  type Size,
  type ViewTransform,
} from '../lib/view';

// [x, y, width, height] in view_box units — one frame exercises both
// regimes: narrower than the window at fullscreen widths, wider than
// the window in the VK frame.
const FRAME: Frame = [100, 50, 400, 250];
const MU = 0.1;
const ZOOM_MAX = 10.8;

const VK_800 = { width: 1000, height: 800 };
const VK_1200 = { width: 1000, height: 1200 };
const FS_1080 = { width: 1920, height: 1080 };
const FS_1440 = { width: 2560, height: 1440 };
const PORTRAIT = { width: 600, height: 1000 };

describe('minScale — the frame height fills the window', () => {
  it.each([
    ['VK ~1000×800', VK_800, 800 / 250],
    ['VK ~1000×1200', VK_1200, 1200 / 250],
    ['fullscreen 1920×1080', FS_1080, 1080 / 250],
    ['fullscreen 2560×1440', FS_1440, 1440 / 250],
    ['window taller than wide', PORTRAIT, 1000 / 250],
  ])('%s', (_label, vp, expected) => {
    expect(minScale(FRAME, vp)).toBeCloseTo(expected);
  });

  it('ignores the window width entirely', () => {
    expect(minScale(FRAME, { width: 500, height: 800 })).toBeCloseTo(
      minScale(FRAME, { width: 5000, height: 800 }),
    );
  });

  it('returns zero on degenerate input', () => {
    expect(minScale(FRAME, { width: 0, height: 0 })).toBe(0);
    expect(minScale([0, 0, 100, 0], VK_800)).toBe(0);
  });
});

describe('initialTransform — z = 1, frame centred', () => {
  it.each([
    ['VK ~1000×800', VK_800],
    ['VK ~1000×1200', VK_1200],
    ['fullscreen 1920×1080', FS_1080],
    ['fullscreen 2560×1440', FS_1440],
    ['window taller than wide', PORTRAIT],
  ])('%s — frame centre lands on the window centre', (_label, vp) => {
    const v = initialTransform(FRAME, vp);
    expect(v.s).toBeCloseTo(minScale(FRAME, vp));
    const centre = worldToScreen(v, {
      x: FRAME[0] + FRAME[2] / 2,
      y: FRAME[1] + FRAME[3] / 2,
    });
    expect(centre.x).toBeCloseTo(vp.width / 2);
    expect(centre.y).toBeCloseTo(vp.height / 2);
    // The full frame height is exactly visible.
    expect(v.s * FRAME[3]).toBeCloseTo(vp.height);
  });

  it('fullscreen shows the frame bigger than the VK window', () => {
    expect(minScale(FRAME, FS_1080)).toBeGreaterThan(
      minScale(FRAME, VK_800),
    );
  });
});

describe('scaleBounds — s = s_min · z, z ∈ [1, zoom_max]', () => {
  it('bounds the total scale', () => {
    const sMin = minScale(FRAME, VK_800);
    const [lo, hi] = scaleBounds(sMin, ZOOM_MAX);
    expect(lo).toBeCloseTo(sMin);
    expect(hi).toBeCloseTo(sMin * ZOOM_MAX);
  });
});

describe('zoomAt — the point under the cursor stays fixed', () => {
  const view = initialTransform(FRAME, VK_800);
  it.each([
    [{ x: 500, y: 400 }, 2],
    [{ x: 0, y: 0 }, 1.25],
    [{ x: 1000, y: 800 }, 0.8],
    [{ x: 137, y: 419 }, 4],
    [{ x: 751, y: 33 }, 10.8],
  ])('cursor %o, scale ×%s', (cursor, factor) => {
    const before = screenToWorld(view, cursor);
    const next = zoomAt(view, cursor, view.s * factor);
    const after = screenToWorld(next, cursor);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it('z hits both limits through the bound clamp', () => {
    const sMin = minScale(FRAME, VK_800);
    const [lo, hi] = scaleBounds(sMin, ZOOM_MAX);
    const clampTo = (s: number) => Math.min(hi, Math.max(lo, s));
    // Zoom out at z = 1 stays at z = 1.
    expect(clampTo(sMin / 1.25)).toBeCloseTo(sMin);
    // Zoom in at z = zoom_max stays at z = zoom_max.
    expect(clampTo(hi * 1.25)).toBeCloseTo(hi);
  });
});

describe('clampOffset — per-axis margin and centring', () => {
  it('centres the x axis when the frame is narrower than the window', () => {
    // Fullscreen 1920×1080: frame is 1728 px wide < 1920 — centred, no pan.
    const v = initialTransform(FRAME, FS_1080);
    const dragged = clampOffset({ ...v, tx: 9999 }, FRAME, FS_1080, MU);
    expect(dragged.tx).toBeCloseTo(v.tx);
    const draggedLeft = clampOffset(
      { ...v, tx: -9999 },
      FRAME,
      FS_1080,
      MU,
    );
    expect(draggedLeft.tx).toBeCloseTo(v.tx);
  });

  it('keeps the y axis pannable within the margin at z = 1', () => {
    // 1080 == s·250 exactly: not exceeding -> the μ band applies.
    const v = initialTransform(FRAME, FS_1080);
    const up = clampOffset({ ...v, ty: 9999 }, FRAME, FS_1080, MU);
    // t_y ≤ −s·y0 + μ·H_v = −216 + 108 = −108
    expect(up.ty).toBeCloseTo(-108);
    const down = clampOffset({ ...v, ty: -9999 }, FRAME, FS_1080, MU);
    // t_y ≥ H_v − s·(y0+h) − μ·H_v = 1080 − 1296 − 108 = −324
    expect(down.ty).toBeCloseTo(-324);
    expect(clampOffset(v, FRAME, FS_1080, MU)).toEqual(v);
  });

  it('clamps pan at both ends when the frame is wider than the window', () => {
    // VK 1000×800: frame is 1280 px wide > 1000 — margin band on x.
    const v = initialTransform(FRAME, VK_800);
    const right = clampOffset({ ...v, tx: 9999 }, FRAME, VK_800, MU);
    // t_x ≤ −s·x0 + μ·W_v = −320 + 100 = −220
    expect(right.tx).toBeCloseTo(-220);
    const left = clampOffset({ ...v, tx: -9999 }, FRAME, VK_800, MU);
    // t_x ≥ W_v − s·(x0+w) − μ·W_v = 1000 − 1600 − 100 = −700
    expect(left.tx).toBeCloseTo(-700);
    expect(clampOffset(v, FRAME, VK_800, MU)).toEqual(v);
  });

  it('centres both axes once the window outgrows the frame', () => {
    // Zoomed out below z = 1 is impossible (bounds), but a portrait
    // window can exceed the frame on x while staying under on y.
    const v = initialTransform(FRAME, PORTRAIT); // s = 4, frame 1600 wide
    const dragged = clampOffset({ ...v, tx: 500 }, FRAME, PORTRAIT, MU);
    // x: 600 < 1600 → margin band, not centring.
    // t_x ≤ −4·100 + 60 = −340
    expect(dragged.tx).toBeCloseTo(-340);
    // y: 1000 == 4·250 → margin band: t_y ≤ −4·50 + 100 = −100
    const dy = clampOffset({ ...v, ty: 500 }, FRAME, PORTRAIT, MU);
    expect(dy.ty).toBeCloseTo(-100);
  });
});

describe('clampOffset — μ = 0 locks the view at the frame', () => {
  /** The μ = 0 invariant per axis: where the scaled frame is wider
   *  than the window it must cover the window edge to edge; where it
   *  is narrower the frame sits centred (and shows `outside`). */
  const expectFrameCovered = (v: ViewTransform, vp: Size) => {
    const axis = (t: number, vLen: number, fPos: number, fLen: number) => {
      if (vLen > v.s * fLen) {
        expect(t).toBe((vLen - v.s * (2 * fPos + fLen)) / 2);
      } else {
        expect(t).toBeLessThanOrEqual(-v.s * fPos + 1e-9);
        expect(t + v.s * (fPos + fLen)).toBeGreaterThanOrEqual(vLen - 1e-9);
      }
    };
    axis(v.tx, vp.width, FRAME[0], FRAME[2]);
    axis(v.ty, vp.height, FRAME[1], FRAME[3]);
  };

  // At z = 1 the y band degenerates to a single value in every window
  // (s·f_h == H_v); x is locked only where the scaled frame is not
  // wider than the window.
  it.each([
    // [label, viewport, x axis locked]
    ['fullscreen 1920×1080', FS_1080, true], // s·w = 1728 < 1920
    ['VK ~1000×800', VK_800, false], // s·w = 1280 > 1000
    ['VK ~1000×1200', VK_1200, false], // s·w = 1920 > 1000
    ['fullscreen 2560×1440', FS_1440, true], // s·w = 2304 < 2560
  ])('%s — a drag cannot move the locked axes', (_label, vp, xLocked) => {
    const v = initialTransform(FRAME, vp);
    for (const [dx, dy] of [
      [5000, 0],
      [-5000, 0],
      [0, 5000],
      [0, -5000],
      [5000, 5000],
      [-5000, -5000],
    ]) {
      const dragged = clampOffset(
        { ...v, tx: v.tx + dx, ty: v.ty + dy },
        FRAME,
        vp,
        0,
      );
      if (xLocked) {
        expect(dragged.tx).toBe(v.tx);
      }
      expect(dragged.ty).toBe(v.ty);
      expectFrameCovered(dragged, vp);
    }
    if (!xLocked) {
      // The pannable axis still drags inside the frame band.
      const nudged = clampOffset({ ...v, tx: v.tx + 100 }, FRAME, vp, 0);
      expect(nudged.tx).toBe(v.tx + 100);
    }
  });

  it.each([
    ['fullscreen 1920×1080', FS_1080, 2.5],
    ['VK ~1000×800', VK_800, 4],
    ['fullscreen 2560×1440', FS_1440, ZOOM_MAX],
  ])(
    '%s at z = %s — pan works, the frame cannot be left',
    (_label, vp, z) => {
      const v0 = initialTransform(FRAME, vp);
      const centre = { x: vp.width / 2, y: vp.height / 2 };
      const zoomed = clampOffset(
        zoomAt(v0, centre, v0.s * z),
        FRAME,
        vp,
        0,
      );
      expect(zoomed.s).toBeCloseTo(v0.s * z);
      expectFrameCovered(zoomed, vp);
      // Hard drags pin the frame edges to the window edges, never past.
      for (const [dx, dy] of [
        [99999, 0],
        [-99999, 0],
        [0, 99999],
        [0, -99999],
      ]) {
        const dragged = clampOffset(
          { ...zoomed, tx: zoomed.tx + dx, ty: zoomed.ty + dy },
          FRAME,
          vp,
          0,
        );
        expectFrameCovered(dragged, vp);
      }
      // …and an ordinary drag really moves the view.
      const panned = clampOffset(
        { ...zoomed, tx: zoomed.tx - 40, ty: zoomed.ty - 40 },
        FRAME,
        vp,
        0,
      );
      expect(panned.tx).toBe(zoomed.tx - 40);
      expect(panned.ty).toBe(zoomed.ty - 40);
    },
  );

  it('zooming back out to z = 1 restores the exact initial view', () => {
    const v0 = initialTransform(FRAME, FS_1080);
    const zoomed = clampOffset(
      zoomAt(v0, { x: 700, y: 200 }, v0.s * 4),
      FRAME,
      FS_1080,
      0,
    );
    const back = clampOffset(
      zoomAt(zoomed, { x: 700, y: 200 }, minScale(FRAME, FS_1080)),
      FRAME,
      FS_1080,
      0,
    );
    expect(back).toEqual(v0);
  });

  it.each([
    ['VK 1000×800 → fullscreen 1920×1080', VK_800, FS_1080],
    ['fullscreen 1920×1080 → QHD 2560×1440', FS_1080, FS_1440],
  ])(
    'fullscreen switch %s at z = 1 lands on the exact new initial view',
    (_label, vpA, vpB) => {
      const v0 = initialTransform(FRAME, vpA);
      const wide = clampOffset(
        rescaleOnResize(v0, FRAME, vpA, vpB),
        FRAME,
        vpB,
        0,
      );
      expect(wide).toEqual(initialTransform(FRAME, vpB));
      const back = clampOffset(
        rescaleOnResize(wide, FRAME, vpB, vpA),
        FRAME,
        vpA,
        0,
      );
      expect(back.s).toBe(v0.s);
      // The locked axis snaps back bit-exact; the still-pannable x
      // axis of the VK window keeps the same world centre.
      expect(back.ty).toBe(v0.ty);
      expect(back.tx).toBeCloseTo(v0.tx, 10);
    },
  );

  it('search «show on map» and neighbour focus respect the same lock', () => {
    const [sMin, sMax] = scaleBounds(minScale(FRAME, FS_1080), ZOOM_MAX);
    // A corner node: centring it raw would pull the frame's far edge
    // inside the window — the clamp must pull it back.
    const corner: BBox = [460, 270, 500, 300];
    const fitted = clampOffset(
      fitBBox(corner, FS_1080, 1.2, sMin, sMax),
      FRAME,
      FS_1080,
      0,
    );
    const centred = clampOffset(
      centerOn(
        { s: sMax, tx: 0, ty: 0 },
        bboxCenter(corner),
        FS_1080,
        sMin,
        sMax,
      ),
      FRAME,
      FS_1080,
      0,
    );
    expectFrameCovered(fitted, FS_1080);
    expectFrameCovered(centred, FS_1080);
    // A fit landing back on sMin snaps to the exact initial view.
    const whole: BBox = [
      FRAME[0],
      FRAME[1],
      FRAME[0] + FRAME[2],
      FRAME[1] + FRAME[3],
    ];
    expect(
      clampOffset(fitBBox(whole, FS_1080, 1.2, sMin, sMax), FRAME, FS_1080, 0),
    ).toEqual(initialTransform(FRAME, FS_1080));
  });
});

describe('fitBBox — search-result focus', () => {
  const [sMin, sMax] = scaleBounds(minScale(FRAME, VK_800), ZOOM_MAX);

  it('fits a node bbox with margin, then re-clamps to the frame', () => {
    const node: BBox = [200, 100, 240, 140]; // 40×40
    const v = fitBBox(node, VK_800, 1.2, sMin, sMax);
    // fit = min(1000/40, 800/40)/1.2 = 20/1.2 ≈ 16.67 → within bounds
    expect(v.s).toBeCloseTo(20 / 1.2);
    const c = worldToScreen(v, bboxCenter(node));
    expect(c.x).toBeCloseTo(500);
    expect(c.y).toBeCloseTo(400);
    // ...and clampOffset may still adjust the offset legally.
    const clamped = clampOffset(v, FRAME, VK_800, MU);
    expect(clamped.s).toBeCloseTo(v.s);
  });

  it('clamps to sMax when the node is tiny', () => {
    const node: BBox = [200, 100, 201, 101];
    expect(fitBBox(node, VK_800, 1.2, sMin, sMax).s).toBe(sMax);
  });

  it('clamps to sMin when the node is huge', () => {
    const node: BBox = [0, 0, 10000, 10000];
    expect(fitBBox(node, VK_800, 1.2, sMin, sMax).s).toBe(sMin);
  });
});

describe('centerOn — neighbour navigation', () => {
  const [sMin, sMax] = scaleBounds(minScale(FRAME, VK_800), ZOOM_MAX);

  it('keeps the current scale and centres the point', () => {
    const view = { s: 8, tx: 0, ty: 0 };
    const next = centerOn(view, { x: 300, y: 150 }, VK_800, sMin, sMax);
    expect(next.s).toBe(8);
    const c = worldToScreen(next, { x: 300, y: 150 });
    expect(c.x).toBeCloseTo(500);
    expect(c.y).toBeCloseTo(400);
  });

  it('clamps an out-of-range scale', () => {
    const view = { s: 100, tx: 0, ty: 0 };
    expect(centerOn(view, { x: 0, y: 0 }, VK_800, sMin, sMax).s).toBe(
      sMax,
    );
  });
});

describe('rescaleOnResize — keeps z and the centre world point', () => {
  it.each([
    ['VK → fullscreen', VK_800, FS_1080],
    ['fullscreen → VK', FS_1080, VK_800],
    ['fullscreen → QHD', FS_1080, FS_1440],
    ['VK 800 → VK 1200', VK_800, VK_1200],
    ['landscape → portrait', VK_800, PORTRAIT],
  ])('%s preserves z and the centre', (_label, oldVp, newVp) => {
    const sMinOld = minScale(FRAME, oldVp);
    const view = { s: sMinOld * 2.5, tx: -300, ty: -100 }; // z = 2.5
    const centre = screenToWorld(view, {
      x: oldVp.width / 2,
      y: oldVp.height / 2,
    });

    const next = rescaleOnResize(view, FRAME, oldVp, newVp);
    expect(next.s).toBeCloseTo(minScale(FRAME, newVp) * 2.5);
    const c = screenToWorld(next, {
      x: newVp.width / 2,
      y: newVp.height / 2,
    });
    expect(c.x).toBeCloseTo(centre.x);
    expect(c.y).toBeCloseTo(centre.y);
  });

  it('round trip returns to the original scale and centre', () => {
    const v0 = initialTransform(FRAME, VK_800);
    const fs = rescaleOnResize(v0, FRAME, VK_800, FS_1080);
    const back = rescaleOnResize(fs, FRAME, FS_1080, VK_800);
    expect(back.s).toBeCloseTo(v0.s);
    expect(back.tx).toBeCloseTo(v0.tx);
    expect(back.ty).toBeCloseTo(v0.ty);
  });
});

describe('fitScale — retained for node fit', () => {
  it('fits the smaller dimension ratio', () => {
    const bbox: BBox = [100, 50, 500, 250];
    // min(1000/400, 800/200) = min(2.5, 4)
    expect(fitScale(bbox, VK_800)).toBeCloseTo(2.5);
  });
});
