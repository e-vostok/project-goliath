/**
 * Seam cover (map2_13, per-node in map2_14): the nodes <g> carries a
 * thin land-coloured world-scaled stroke inherited by every fill, so
 * anti-aliasing hairlines between neighbours show land colour, never
 * the sea. Compared to the old under-fill seam layer, each stroke is
 * rasterised inside its node's own bounding box, which the browser
 * culls far better; an ownership change never rebuilds the stroke —
 * only the fill colour of the affected nodes changes (the DOM nodes
 * keep identity).
 */

import { render } from '@testing-library/react';

import { MapView } from '../components/MapView';
import { SEAM_STROKE_W } from '../constants';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_RULES,
  MINI_STATE,
} from '../fixtures/miniMap';
import type { MapStateDTO } from '../types';

const OTHER_STATE: MapStateDTO = {
  ...MINI_STATE,
  owners: [
    [1003, 0],
    [1004, 0],
    [1005, 0],
  ],
};

function nodesGroup(): SVGGElement {
  const el = document.querySelector<SVGGElement>(
    'g[data-layer="nodes"]',
  );
  expect(el).not.toBeNull();
  return el!;
}

function nodePaths(): SVGPathElement[] {
  const els = [
    ...document.querySelectorAll<SVGPathElement>('path[data-id]'),
  ];
  expect(els.length).toBeGreaterThan(0);
  return els;
}

describe('MapView — seam cover via node strokes (map2_13, map2_14)', () => {
  it('strokes every fill with the land colour in world units', () => {
    const { rerender } = render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        state={MINI_STATE}
      />,
    );

    expect(
      document.querySelector('g[data-layer="land-underlay"]'),
    ).toBeNull();
    const g = nodesGroup();
    expect(g.getAttribute('stroke')).toBe(
      MINI_RULES.colors.land_underlay,
    );
    expect(g.getAttribute('stroke-width')).toBe(String(SEAM_STROKE_W));
    // No non-scaling-stroke: the world-scaled width is what keeps the
    // per-frame re-raster inside the frame budget.
    expect(g.getAttribute('vector-effect')).toBeNull();
    const paths = nodePaths();
    for (const p of paths) {
      // Colour and width are inherited from the group — no per-path
      // stroke attributes (writeView owns the group width).
      expect(p.getAttribute('stroke')).toBeNull();
      expect(p.getAttribute('stroke-width')).toBeNull();
      expect(p.getAttribute('vector-effect')).toBeNull();
    }

    // An ownership refresh keeps the group stroke identical and the
    // DOM nodes themselves — only fills may change colour.
    rerender(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        state={OTHER_STATE}
      />,
    );
    const after = nodePaths();
    expect(after).toHaveLength(paths.length);
    after.forEach((p, i) => {
      expect(p).toBe(paths[i]);
    });
    expect(nodesGroup().getAttribute('stroke')).toBe(
      MINI_RULES.colors.land_underlay,
    );
  });
});
