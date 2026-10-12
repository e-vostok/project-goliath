/**
 * Label layout (map2_6, Spec 3.9) + map2_6c rules: a name is drawn only
 * when it fits its `label` box at the current scale; collisions resolve
 * by area priority; two-line splits and the group-width box of
 * multi-part nodes behave per the fit rule. Province names exist only
 * at the maximum zoom, sea names only below it. The rendered set
 * follows the viewport during a pan (map2_6 bug: provinces scrolled
 * into view were left unlabelled).
 */

import {
  labelMostlyInView,
  layoutLabels,
  mergeRendered,
  selectRendered,
  windowCoversView,
  type LabelMeasurer,
  type PlacedLabel,
} from '../lib/labels';
import type { MapLabelsRulesDTO, MapNodeDTO } from '../types';
import type { ViewTransform } from '../lib/view';

/** Deterministic measurer: 0.5 px per character at font-size 1. */
const MEASURER: LabelMeasurer = {
  measure: (text, spacingEm) =>
    text.length * 0.5 + spacingEm * Math.max(0, text.length - 1),
};

const RULES: MapLabelsRulesDTO = {
  font: 'fira_sans_condensed',
  land_min_px: 9,
  land_max_px: 15,
  sea_min_px: 10,
  sea_max_px: 19,
  fit_ratio: 0.9,
  collision_padding_px: 3,
  halo_width_px: 2.5,
  halo_color: '#101014',
  land_color: '#F2F3F5',
  sea_color: '#C4E0F5',
  sea_letter_spacing_em: 0.08,
  province_zoom_ratio: 0.98,
  fade_ms: 120,
};

const node = (
  id: number,
  opts: Partial<MapNodeDTO> = {},
): MapNodeDTO => ({
  id,
  key: `n${id}`,
  kind: 'LAND',
  name: `N${id}`,
  name_ru: null,
  anchor: [0, 0],
  bbox: [0, 0, 10, 10],
  area: 100,
  label: { x: 0, y: 0, w: 10, h: 10 },
  ...opts,
});

describe('layoutLabels', () => {
  it('hides at a smaller zoom a name that fits at a larger one', () => {
    const n = node(1, { name: 'Alpha' }); // 5 chars → 2.5 per-px width
    // scale == maxScale keeps the test inside the province zoom.
    const far = layoutLabels([n], 1, RULES, MEASURER, 1);
    const near = layoutLabels([n], 10, RULES, MEASURER, 10);
    expect(far).toEqual([]);
    expect(near.map((l) => l.id)).toEqual([1]);
    expect(near[0].sizePx).toBe(15); // capped at land_max_px
  });

  it('keeps only the higher-priority label of overlapping candidates', () => {
    const small = node(1, { name: 'Aa', area: 50 });
    const big = node(2, { name: 'Bb', area: 500 });
    const placed = layoutLabels([small, big], 10, RULES, MEASURER, 10);
    expect(placed.map((l) => l.id)).toEqual([2]);
    // Sea names compete among themselves below the maximum zoom.
    const seaA = node(3, { kind: 'SEA', name: 'Cc', area: 50 });
    const seaB = node(4, { kind: 'SEA', name: 'Dd', area: 500 });
    const below = 5; // < 0.98 × maxScale 10
    expect(
      layoutLabels([seaA, seaB], below, RULES, MEASURER, 10).map(
        (l) => l.id,
      ),
    ).toEqual([4]);
  });

  it('uses a two-line split when only it fits', () => {
    // 'Alpha Beta' (10 chars, w1=5) cannot fit a w=4 box at min size,
    // but 'Alpha'/'Beta' (max line 2.5) fits at a readable size.
    const n = node(1, {
      name: 'Alpha Beta',
      label: { x: 0, y: 0, w: 4, h: 10 },
    });
    const placed = layoutLabels([n], 10, RULES, MEASURER, 10);
    expect(placed).toHaveLength(1);
    expect(placed[0].lines).toEqual(['Alpha', 'Beta']);
  });

  it('fits a multi-part node by its group label box, not its bbox', () => {
    // A scattered island group: tiny part bboxes, but the pipeline
    // stores the group-wide label box — the name fits over the group.
    const group = node(1, {
      name: 'Cyclades Islands',
      bbox: [0, 0, 1, 1],
      label: { x: 0, y: 0, w: 20, h: 6 },
    });
    const placed = layoutLabels([group], 10, RULES, MEASURER, 10);
    expect(placed.map((l) => l.id)).toEqual([1]);
    // Same node with a single-part-size box stays hidden at this zoom.
    const tiny = { ...group, label: { x: 0, y: 0, w: 1, h: 1 } };
    expect(layoutLabels([tiny], 10, RULES, MEASURER, 10)).toEqual([]);
  });
});

describe('zoom gating (map2_6c)', () => {
  const land = node(1, { name: 'Alpha', area: 100 });
  const sea = node(2, {
    kind: 'SEA',
    name: 'Sea',
    area: 500,
    label: { x: 0, y: 0, w: 40, h: 20 },
  });

  it('renders provinces only at the maximum zoom, seas only below', () => {
    const maxScale = 40;
    const atMax = layoutLabels([land, sea], maxScale, RULES, MEASURER, maxScale);
    expect(atMax.map((l) => l.id)).toEqual([1]);
    const below = layoutLabels(
      [land, sea],
      maxScale * RULES.province_zoom_ratio * 0.99,
      RULES,
      MEASURER,
      maxScale,
    );
    expect(below.map((l) => l.id)).toEqual([2]);
  });
});

describe('rendered set follows the viewport (map2_6c pan bug)', () => {
  // A long row of provinces at the closest zoom: each label fits.
  const MAX = 50;
  const provinces = Array.from({ length: 30 }, (_, i) =>
    node(i + 1, {
      name: `P${i + 1}`,
      area: 100,
      bbox: [i * 20, 0, i * 20 + 18, 18],
      label: { x: i * 20 + 9, y: 9, w: 18, h: 18 },
    }),
  );
  const viewport = { width: 800, height: 600 };

  it('labels of provinces scrolled into view exist and are visible', () => {
    const placed = layoutLabels(provinces, MAX, RULES, MEASURER, MAX);
    const v0: ViewTransform = { s: MAX, tx: 0, ty: 0 };
    const first = selectRendered(placed, v0, viewport);
    // Only P1 (x·s = 450 px) sits inside the ±0.5-screen window.
    expect(first.items.map((l) => l.id)).toEqual([1]);

    // Drag a full screen to the right: viewport covers map x ∈ [16,32].
    const v1: ViewTransform = { s: MAX, tx: -800, ty: 0 };
    // The quarter-screen lead is gone — the set must be re-selected.
    expect(windowCoversView(first.window, v1, viewport)).toBe(false);
    const second = selectRendered(placed, v1, viewport);
    // P2 (anchor at screen x=650) must already exist in the DOM…
    const ids = second.items.map((l) => l.id);
    expect(ids).toContain(2);
    // …and report visible while most of its province is in view.
    const p2 = second.items.find((l) => l.id === 2) as PlacedLabel;
    expect(labelMostlyInView(p2, v1, viewport)).toBe(true);
  });

  it('does not re-select while the quarter-screen lead still holds', () => {
    const placed = layoutLabels(provinces, MAX, RULES, MEASURER, MAX);
    const v0: ViewTransform = { s: MAX, tx: 0, ty: 0 };
    const first = selectRendered(placed, v0, viewport);
    const halfScreen: ViewTransform = { s: MAX, tx: -100, ty: 0 };
    expect(windowCoversView(first.window, halfScreen, viewport)).toBe(true);
  });
});

describe('labelMostlyInView (map2_6c)', () => {
  const viewport = { width: 800, height: 600 };
  const base: ViewTransform = { s: 10, tx: 0, ty: 0 };

  const label = (
    id: number,
    bbox: [number, number, number, number],
    x: number,
    y: number,
  ): PlacedLabel => ({
    id,
    kind: 'LAND',
    x,
    y,
    fontSize: 1,
    sizePx: 10,
    haloW: 0.25,
    lines: ['X'],
    textW: 5,
    textH: 1.2,
    bbox,
  });

  it('a normal province is visible once most of it is in view', () => {
    const l = label(1, [0, 0, 10, 10], 5, 5); // fully onscreen
    expect(labelMostlyInView(l, base, viewport)).toBe(true);
    // Slid right until <50% of the bbox is visible and the anchor is out.
    const out: ViewTransform = { s: 10, tx: -60, ty: 0 };
    expect(labelMostlyInView(l, out, viewport)).toBe(false);
    // Back to a position where ≥50% shows → visible again.
    const half: ViewTransform = { s: 10, tx: -45, ty: 0 };
    expect(labelMostlyInView(l, half, viewport)).toBe(true);
  });

  it('a province larger than the screen follows its label anchor', () => {
    // Bbox vastly bigger than the viewport: share ≪ 0.5 always — only
    // the anchor-inside-shrunk-viewport rule can show the label.
    const l = label(2, [-100, -100, 500, 500], 200, 200);
    // Anchor at (2000, 2000) px — outside.
    expect(labelMostlyInView(l, base, viewport)).toBe(false);
    // Pan until the anchor lands in the shrunken viewport.
    const v: ViewTransform = { s: 10, tx: -1600, ty: -1700 };
    expect(labelMostlyInView(l, v, viewport)).toBe(true);
  });
});

describe('mergeRendered (map2_6c)', () => {
  const viewport = { width: 800, height: 600 };
  const v: ViewTransform = { s: 10, tx: 0, ty: 0 };
  const l = (id: number, x: number): PlacedLabel => ({
    id,
    kind: 'LAND',
    x,
    y: 30,
    fontSize: 1,
    sizePx: 10,
    haloW: 0.25,
    lines: ['X'],
    textW: 5,
    textH: 1.2,
    bbox: [x - 5, 25, x + 5, 35],
  });

  it('keeps continuing labels untouched; only onscreen leavers fade out', () => {
    const stay = l(1, 40); // onscreen, stays
    const onscreen = l(2, 60); // onscreen (x·s = 600 px), leaves → exiting copy
    const farOff = l(3, 2000); // offscreen, leaves → dropped at once
    const prev = [stay, onscreen, farOff];
    const next = [stay];
    const merged = mergeRendered(prev, next, v, viewport, 1000, 120);
    expect(merged[0]).toBe(stay);
    const exiting = merged.filter((m) => m.exiting !== undefined);
    expect(exiting.map((m) => m.id)).toEqual([2]);
    // No exiting entries when the fade is disabled.
    expect(
      mergeRendered(prev, next, v, viewport, 1000, 0).filter(
        (m) => m.exiting !== undefined,
      ),
    ).toEqual([]);
  });
});
