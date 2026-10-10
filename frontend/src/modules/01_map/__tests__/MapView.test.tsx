/**
 * MapView sea_water layer (Spec 1.9, step 5a): one path directly above
 * the inland-water background and below `outside`, filled with
 * colors.sea, never interactive; an empty `sea_water` renders nothing.
 */

import { fireEvent, render, waitFor } from '@testing-library/react';

import { MapView } from '../components/MapView';
import {
  MINI_BORDERS,
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

describe('MapView — live-pan gestures (map2_14)', () => {
  // The container reports a real size so the view transform initialises
  // (jsdom rects are 0×0 otherwise).
  beforeEach(() => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800,
      height: 600,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 800,
      bottom: 600,
      toJSON: () => ({}),
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it('drag repaints the live transform every frame; nothing hides', async () => {
    render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        selectedIds={[1001]}
      />,
    );
    const container = document.querySelector(
      '[data-testid="map-view"]',
    ) as HTMLElement;
    const svg = container.querySelector('svg') as SVGSVGElement;
    const world = svg.querySelector('g') as SVGGElement;
    expect(world.getAttribute('transform')).toBe(
      'translate(-80 -120) scale(12)',
    );
    // The border layer exists as three LOD groups; only the matching
    // one is displayed (s = 12 → full geometry).
    const lodGroups = [
      ...document.querySelectorAll('[data-border-lod]'),
    ] as SVGGElement[];
    expect(lodGroups).toHaveLength(3);
    const shown = lodGroups.filter((g) => g.style.display !== 'none');
    expect(shown).toHaveLength(1);
    expect(shown[0].getAttribute('data-border-lod')).toBe('high');
    expect(
      shown[0].querySelector('[data-border="internal"] path'),
    ).not.toBeNull();

    fireEvent.mouseDown(container, { button: 0, clientX: 400, clientY: 300 });
    window.dispatchEvent(
      new MouseEvent('mousemove', { clientX: 440, clientY: 310 }),
    );

    await waitFor(() => {
      expect(container).toHaveAttribute('data-gesture');
    });
    // The live transform is repainted into the world attribute — no
    // CSS delta on the <svg>, no snapshot raster (x is clamp-locked,
    // y already moved by +10).
    await waitFor(() => {
      expect(world.getAttribute('transform')).toBe(
        'translate(-80 -110) scale(12)',
      );
    });
    expect(svg.style.transform).toBe('');
    // Nothing hides mid-gesture: labels keep drawing and no layer
    // group is switched off (inactive LOD copies are not layers).
    const labelsG = document.querySelector(
      '[data-layer="labels"]',
    ) as SVGGElement;
    expect(labelsG.style.display).not.toBe('none');
    expect(
      [...svg.querySelectorAll('g')].filter(
        (g) =>
          g.style.display === 'none' &&
          !g.hasAttribute('data-border-lod'),
      ),
    ).toHaveLength(0);
    // The pulse pause lives in the injected CSS, keyed by data-gesture.
    expect(
      [...document.querySelectorAll('style')].some((s) =>
        s.textContent?.includes('[data-gesture] .pg-map-selected-pulse'),
      ),
    ).toBe(true);

    window.dispatchEvent(new MouseEvent('mouseup'));
    await waitFor(
      () => {
        expect(container).not.toHaveAttribute('data-gesture');
      },
      { timeout: 1000 },
    );
    // Idle again: the same live transform — nothing re-baked, nothing
    // swapped, labels never left.
    expect(svg.style.transform).toBe('');
    expect(labelsG.style.display).not.toBe('none');
    expect(world.getAttribute('transform')).toBe(
      'translate(-80 -110) scale(12)',
    );
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
