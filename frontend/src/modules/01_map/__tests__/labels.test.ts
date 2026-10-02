/**
 * Label rule (Spec 3.9): a node is labelled iff s·w ≥ label_min_width_px.
 */

import { labelVisible, visibleLabelNodes } from '../lib/labels';
import type { MapNodeDTO } from '../types';

const node = (id: number, width: number): MapNodeDTO => ({
  id,
  key: `n${id}`,
  kind: 'LAND',
  name: `N${id}`,
  name_ru: null,
  anchor: [0, 0],
  bbox: [0, 0, width, 10],
  area: width * 10,
});

const MIN = 48;

describe('labelVisible', () => {
  it('shows the label exactly at the boundary s·w = min', () => {
    expect(labelVisible(node(1, 10), 4.8, MIN)).toBe(true); // 48.0
  });
  it('hides it one epsilon below', () => {
    expect(labelVisible(node(1, 10), 4.79, MIN)).toBe(false); // 47.9
  });
  it('shows it above', () => {
    expect(labelVisible(node(1, 10), 10, MIN)).toBe(true);
  });
});

describe('visibleLabelNodes', () => {
  it('filters the node set and handles degenerate scales', () => {
    const nodes = [node(1, 5), node(2, 10), node(3, 20)];
    expect(visibleLabelNodes(nodes, 4.8, MIN).map((n) => n.id)).toEqual([
      2, 3,
    ]);
    expect(visibleLabelNodes(nodes, 0, MIN)).toEqual([]);
    expect(visibleLabelNodes(nodes, Number.NaN, MIN)).toEqual([]);
  });
});
