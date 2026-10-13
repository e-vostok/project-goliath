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
  font: 'pt_mono',
  sea_font: 'pt_mono',
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
  max_angle_deg: 60,
  max_bend: 0.1,
  thickness_ratio: 0.55,
  length_ratio: 0.85,
  letter_spacing_min_em: -0.02,
  letter_spacing_max_em: 0.3,
  land_opacity: 0.6,
  sea_opacity: 0.4,
  sea_curved: true,
};

/** A label box plus a centred horizontal spine covering 80% of it —
 *  what the pipeline emits for an oblong territory. */
const labelBox = (
  x: number,
  y: number,
  w: number,
  h: number,
): MapNodeDTO['label'] => ({
  x,
  y,
  w,
  h,
  spine: [x - 0.4 * w, y, x + 0.4 * w, y, 0],
  len: 0.8 * w,
  thick: h,
});

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
  label: labelBox(0, 0, 10, 10),
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
      label: labelBox(0, 0, 4, 10),
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
      label: labelBox(0, 0, 20, 6),
    });
    const placed = layoutLabels([group], 10, RULES, MEASURER, 10);
    expect(placed.map((l) => l.id)).toEqual([1]);
    // Same node with a single-part-size box stays hidden at this zoom.
    const tiny = { ...group, label: labelBox(0, 0, 1, 1) };
    expect(layoutLabels([tiny], 10, RULES, MEASURER, 10)).toEqual([]);
  });
});

describe('spine labels (map2_20)', () => {
  // A 40×8 territory at scale 40: chord 32 u = 1280 px, cap by
  // thickness 8 u → heightCap = 0.55·8·40 = 176 px.
  const oblong = node(1, {
    name: 'Abcdefgh',
    label: {
      x: 0, y: 0, w: 40, h: 8,
      spine: [-16, 0, 16, 0, 0], len: 32, thick: 8,
    },
  });

  it('spreads letters up to length_ratio of the chord, opacity 0.6', () => {
    const placed = layoutLabels([oblong], 40, RULES, MEASURER, 40);
    expect(placed).toHaveLength(1);
    const l = placed[0];
    expect(l.path).not.toBeNull();
    // w0 = 4 per px; target = 0.85·32·40 = 1088 px; size capped at 15
    // → spacing = (1088/15 − 4)/7 ≈ 9.79 → clamped to 0.3.
    expect(l.letterSpacingEm).toBeLessThanOrEqual(
      RULES.letter_spacing_max_em,
    );
    expect(l.letterSpacingEm).toBeGreaterThanOrEqual(
      RULES.letter_spacing_min_em,
    );
    expect(l.sizePx).toBe(15);
    expect(l.opacity).toBe(RULES.land_opacity);
  });

  it('shrinks the font when even the tightest spacing overflows', () => {
    // len 10 → target 340 px; 50 chars (w0 25) at the min spacing
    // still overflow at 15 px → size drops to 340/(25−0.98) ≈ 14.2.
    const n = node(1, {
      name: 'Abcdefghij'.repeat(5),
      label: {
        x: 0, y: 0, w: 10, h: 8,
        spine: [-5, 0, 5, 0, 0], len: 10, thick: 8,
      },
    });
    const placed = layoutLabels([n], 40, RULES, MEASURER, 40);
    expect(placed).toHaveLength(1);
    const l = placed[0];
    expect(l.letterSpacingEm).toBe(RULES.letter_spacing_min_em);
    expect(l.sizePx).toBeLessThan(15);
    expect(l.sizePx).toBeGreaterThanOrEqual(RULES.land_min_px);
    // exactly fills the target: size · (w0 + min·gaps) = 0.85·len·scale
    expect(l.sizePx * (25 + RULES.letter_spacing_min_em * 49)).toBeCloseTo(
      RULES.length_ratio * 10 * 40,
      5,
    );
  });

  it('hides a name that cannot reach land_min_px along the spine', () => {
    // len 1 u → target 34 px; the name needs ≥ 9·(17−0.66) ≈ 147 px.
    const tiny = node(1, {
      name: 'AbcdefghijklmnopqrstuvwxyzAbcdefghij',
      label: {
        x: 0, y: 0, w: 1, h: 0.5, // box too small for a two-line save
        spine: [-0.5, 0, 0.5, 0, 0], len: 1, thick: 0.5,
      },
    });
    expect(layoutLabels([tiny], 40, RULES, MEASURER, 40)).toEqual([]);
  });

  it('falls back to two horizontal lines when the spine is too short', () => {
    const n = node(1, {
      name: 'Abcdef Ghijkl',
      // the spine offers ~8.8 px, hopeless for 13 glyphs; the box is
      // narrow (w 2 u) so one line caps at 11 px but two lines reach
      // the 15 px cap — the map2_6 two-line fit wins.
      label: {
        x: 0, y: 0, w: 2, h: 4,
        spine: [-0.13, 0, 0.13, 0, 0], len: 0.26, thick: 4,
      },
    });
    const placed = layoutLabels([n], 40, RULES, MEASURER, 40);
    expect(placed).toHaveLength(1);
    expect(placed[0].path).toBeNull();
    expect(placed[0].lines).toEqual(['Abcdef', 'Ghijkl']);
    expect(placed[0].sizePx).toBe(15);
    expect(placed[0].opacity).toBe(RULES.land_opacity);
  });

  it('bends the slice along the spine sagitta', () => {
    const bent = node(1, {
      name: 'Abcdefgh',
      label: {
        x: 0, y: 0, w: 40, h: 8,
        spine: [-16, 0, 16, 0, 1.6], len: 32, thick: 8,
      },
    });
    const placed = layoutLabels([bent], 40, RULES, MEASURER, 40);
    expect(placed).toHaveLength(1);
    const p = placed[0].path!;
    // control point along the chord's left normal (+y for a
    // left-to-right chord): s > 0 bends the slice that way
    expect(p.cy).toBeGreaterThan(0);
    // endpoints on the arc, symmetric around the midpoint
    expect(p.y0).toBeCloseTo(p.y1, 6);
    expect(p.x0).toBeLessThan(0);
    expect(p.x1).toBeGreaterThan(0);
  });

  it('rotated collision boxes do not falsely overlap', () => {
    // Two parallel 45° spines 2.2 units apart along their shared
    // normal: the thin oriented boxes never touch (hh+hh ≈ 17 px <
    // 22 px), but their axis-aligned bounds overlap — the old AABB
    // collision would have dropped the second label.
    const mk = (id: number, dx: number, dy: number) =>
      node(id, {
        name: `Aa${id}`,
        area: 100,
        label: {
          x: 0, y: 0, w: 1, h: 1,
          spine: [dx, dy, dx + 8, dy + 8, 0],
          len: Math.hypot(8, 8),
          thick: 2,
        },
      });
    const placed = layoutLabels(
      [mk(1, 0, 0), mk(2, -1.56, 1.56)],
      10,
      RULES,
      MEASURER,
      10,
    );
    expect(placed.map((l) => l.id).sort()).toEqual([1, 2]);
  });
});

describe('zoom gating (map2_6c)', () => {
  const land = node(1, { name: 'Alpha', area: 100 });
  const sea = node(2, {
    kind: 'SEA',
    name: 'Sea',
    area: 500,
    label: labelBox(0, 0, 40, 20),
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
      label: labelBox(i * 20 + 9, 9, 18, 18),
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
    path: null,
    letterSpacingEm: 0,
    opacity: 0.6,
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
    path: null,
    letterSpacingEm: 0,
    opacity: 0.6,
    bbox: [x - 5, 25, x + 5, 35],
  });

  it('keeps continuing labels untouched; onscreen leavers fade out, offscreen go ghost', () => {
    const stay = l(1, 40); // onscreen, stays
    const onscreen = l(2, 60); // onscreen (x·s = 600 px), leaves → exiting copy
    const farOff = l(3, 2000); // offscreen, leaves → ghost exit (map2_21:
    // kept mounted display:none so a mass leave is never one big commit)
    const prev = [stay, onscreen, farOff];
    const next = [stay];
    const merged = mergeRendered(prev, next, v, viewport, 1000, 120);
    expect(merged[0]).toBe(stay);
    const exiting = merged.filter((m) => m.exiting !== undefined);
    expect(exiting.map((m) => m.id)).toEqual([2, 3]);
    expect(exiting.find((m) => m.id === 3)?.ghost).toBe(true);
    expect(exiting.find((m) => m.id === 2)?.ghost).toBeUndefined();
    // No exiting entries when the fade is disabled.
    expect(
      mergeRendered(prev, next, v, viewport, 1000, 0).filter(
        (m) => m.exiting !== undefined,
      ),
    ).toEqual([]);
  });
});
