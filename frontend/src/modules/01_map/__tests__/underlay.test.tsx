/**
 * Seam-cover underlay (map2_13): one compound path stroked with
 * `colors.land_underlay` along every shared edge, under the fills, so
 * anti-aliasing hairlines between neighbours show land colour, never
 * the sea. It must cover LAND–LAND pair edges only — no coast
 * polyline contributes — and must never be rebuilt on ownership
 * changes (the path depends on `borders.json` alone).
 */

import { render } from '@testing-library/react';

import { MapView } from '../components/MapView';
import { buildSeamCover } from '../lib/underlay';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_RULES,
  MINI_STATE,
} from '../fixtures/miniMap';
import type { MapStateDTO } from '../types';

vi.mock('../lib/underlay', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../lib/underlay')>();
  return { ...mod, buildSeamCover: vi.fn(mod.buildSeamCover) };
});

const EXPECTED_D = Object.values(MINI_BORDERS.pairs).join(' ');

const OTHER_STATE: MapStateDTO = {
  ...MINI_STATE,
  owners: [[1003, 0], [1004, 0], [1005, 0]],
};

describe('MapView — seam cover underlay (map2_13)', () => {
  it('covers LAND–LAND edges only, never coasts, and is built once', () => {
    vi.mocked(buildSeamCover).mockClear();

    const { rerender } = render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        state={MINI_STATE}
      />,
    );

    const underlay = document.querySelector(
      'path[data-layer="land-underlay"]',
    ) as SVGPathElement;
    expect(underlay).not.toBeNull();
    // Exactly the shared-edge polylines, joined — no coast polyline
    // and no node geometry contributes.
    expect(underlay.getAttribute('d')).toBe(EXPECTED_D);
    for (const coast of Object.values(MINI_BORDERS.coasts)) {
      expect(underlay.getAttribute('d')).not.toContain(coast);
    }
    for (const nodePath of Object.values(MINI_GEOMETRY.paths)) {
      expect(underlay.getAttribute('d')).not.toContain(nodePath);
    }
    expect(underlay.getAttribute('fill')).toBe('none');
    expect(underlay.getAttribute('stroke')).toBe(
      MINI_RULES.colors.land_underlay,
    );
    // No non-scaling-stroke: the world-scaled width is what keeps the
    // settle re-raster inside the frame budget.
    expect(underlay.getAttribute('vector-effect')).toBeNull();
    expect(underlay.getAttribute('pointer-events')).toBe('none');
    // It sits under the fills so only hairline gaps can expose it.
    expect(underlay.nextElementSibling?.firstElementChild?.tagName).toBe(
      'path',
    );
    expect(buildSeamCover).toHaveBeenCalledTimes(1);

    // An ownership refresh must not rebuild the cover: same path,
    // same DOM node, no second call.
    rerender(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        state={OTHER_STATE}
      />,
    );
    const underlayAfter = document.querySelector(
      'path[data-layer="land-underlay"]',
    ) as SVGPathElement;
    expect(underlayAfter).toBe(underlay);
    expect(underlayAfter.getAttribute('d')).toBe(EXPECTED_D);
    expect(buildSeamCover).toHaveBeenCalledTimes(1);
  });
});
