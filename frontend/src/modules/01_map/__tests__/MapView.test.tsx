/**
 * MapView sea_water layer (Spec 1.9, step 5a): one path directly above
 * the inland-water background and below `outside`, filled with
 * colors.sea, never interactive; an empty `sea_water` renders nothing.
 */

import { render } from '@testing-library/react';

import { MapView } from '../components/MapView';
import {
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_RULES,
} from '../fixtures/miniMap';
import type { MapGeometryDTO } from '../types';

const WITH_BAY: MapGeometryDTO = {
  ...MINI_GEOMETRY,
  sea_water: 'M 42 42 L 44 42 L 44 44 L 42 44 Z',
};

function background(): Element {
  const el = document.querySelector('[data-layer="inland-water"]');
  expect(el).not.toBeNull();
  return el as Element;
}

describe('MapView — sea_water layer', () => {
  it.each(['view', 'select'] as const)(
    'mode=%s: sits between background and outside, sea fill, inert',
    (mode) => {
      render(
        <MapView
          mode={mode}
          manifest={MINI_MANIFEST}
          geometry={WITH_BAY}
        />,
      );

      const seaWater = background().nextElementSibling as SVGPathElement;
      expect(seaWater.getAttribute('data-layer')).toBe('sea-water');
      expect(seaWater.getAttribute('d')).toBe(WITH_BAY.sea_water);
      expect(seaWater.getAttribute('fill')).toBe(
        MINI_MANIFEST.rules.colors.sea,
      );
      expect(seaWater.getAttribute('pointer-events')).toBe('none');
      expect(seaWater.getAttribute('data-id')).toBeNull();

      const outside = seaWater.nextElementSibling as SVGPathElement;
      expect(outside.getAttribute('d')).toBe(WITH_BAY.outside);
      expect(outside.getAttribute('fill')).toBe(
        MINI_MANIFEST.rules.colors.outside,
      );
    },
  );

  it('renders no layer when sea_water is empty', () => {
    render(<MapView manifest={MINI_MANIFEST} geometry={MINI_GEOMETRY} />);
    expect(
      document.querySelector('path[data-layer="sea-water"]'),
    ).toBeNull();
    // `outside` still directly follows the background.
    expect(
      background().nextElementSibling?.getAttribute('d'),
    ).toBe(MINI_GEOMETRY.outside);
  });
});

describe('MapView — hover overlay (map2_0)', () => {
  it('fills with colors.hover at the rule opacity, no stroke when disabled', () => {
    render(<MapView manifest={MINI_MANIFEST} geometry={MINI_GEOMETRY} />);
    const overlay = document.querySelector('path[data-layer="hover"]');
    expect(overlay).not.toBeNull();
    expect(overlay!.getAttribute('fill')).toBe(
      MINI_MANIFEST.rules.colors.hover,
    );
    // The fixture opacity differs from the shipped config — a
    // hardcoded constant would fail here.
    expect(overlay!.getAttribute('fill-opacity')).toBe(
      String(MINI_RULES.hover_fill_opacity),
    );
    expect(overlay!.getAttribute('stroke')).toBe('none');
    // The overlay lives in the pointer-events:none group, so it can
    // never swallow the delegated node hit-testing.
    expect(
      overlay!.parentElement?.getAttribute('pointer-events'),
    ).toBe('none');
  });
});
