/**
 * Label layout (map2_6, Spec 3.9): a name is drawn only when it fits
 * its `label` box at the current scale; collisions resolve by area
 * priority (land before sea at equal area); two-line splits and the
 * group-width box of multi-part nodes behave per the fit rule.
 */

import { layoutLabels, type LabelMeasurer } from '../lib/labels';
import type { MapLabelsRulesDTO, MapNodeDTO } from '../types';

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
    const far = layoutLabels([n], 1, RULES, MEASURER);
    const near = layoutLabels([n], 10, RULES, MEASURER);
    expect(far).toEqual([]);
    expect(near.map((l) => l.id)).toEqual([1]);
    expect(near[0].sizePx).toBe(15); // capped at land_max_px
  });

  it('keeps only the higher-priority label of overlapping candidates', () => {
    const small = node(1, { name: 'Aa', area: 50 });
    const big = node(2, { name: 'Bb', area: 500 });
    const placed = layoutLabels([small, big], 10, RULES, MEASURER);
    expect(placed.map((l) => l.id)).toEqual([2]);
    // Sea loses to land at equal area.
    const sea = node(3, { kind: 'SEA', name: 'Cc', area: 500 });
    const placed2 = layoutLabels([sea, big], 10, RULES, MEASURER);
    expect(placed2.map((l) => l.id)).toEqual([2]);
  });

  it('uses a two-line split when only it fits', () => {
    // 'Alpha Beta' (10 chars, w1=5) cannot fit a w=4 box at min size,
    // but 'Alpha'/'Beta' (max line 2.5) fits at a readable size.
    const n = node(1, {
      name: 'Alpha Beta',
      label: { x: 0, y: 0, w: 4, h: 10 },
    });
    const placed = layoutLabels([n], 10, RULES, MEASURER);
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
    const placed = layoutLabels([group], 10, RULES, MEASURER);
    expect(placed.map((l) => l.id)).toEqual([1]);
    // Same node with a single-part-size box stays hidden at this zoom.
    const tiny = { ...group, label: { x: 0, y: 0, w: 1, h: 1 } };
    expect(layoutLabels([tiny], 10, RULES, MEASURER)).toEqual([]);
  });
});
