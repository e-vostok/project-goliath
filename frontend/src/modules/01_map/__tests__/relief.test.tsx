/**
 * Relief underlay (map2_5): a lazy raster below the province fills.
 * The map must work identically without it — disabled config or a
 * failed image load means no layer, no errors, one console warning —
 * and once loaded, land fills multiply over the picture while sea
 * keeps its plain colour.
 */

import { act, render } from '@testing-library/react';

import { MapView } from '../components/MapView';
import { MINI_GEOMETRY, MINI_MANIFEST, MINI_RULES } from '../fixtures/miniMap';
import type { MapManifestDTO } from '../types';

/** Real images never fire load events under jsdom — capture them. */
class StubImage {
  static instances: StubImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = '';
  constructor() {
    StubImage.instances.push(this);
  }
}

const RULES_ON = {
  ...MINI_RULES,
  relief: { ...MINI_RULES.relief, enabled: true },
};
const MANIFEST_ON: MapManifestDTO = { ...MINI_MANIFEST, rules: RULES_ON };

function lastImage(): StubImage {
  expect(StubImage.instances.length).toBeGreaterThan(0);
  return StubImage.instances[StubImage.instances.length - 1];
}

describe('MapView — relief layer (map2_5)', () => {
  beforeEach(() => {
    StubImage.instances = [];
    vi.stubGlobal('Image', StubImage);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders nothing and loads nothing when disabled', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    render(<MapView manifest={MINI_MANIFEST} geometry={MINI_GEOMETRY} />);

    expect(document.querySelector('[data-layer="relief"]')).toBeNull();
    expect(document.querySelector('[data-layer="relief-dim"]')).toBeNull();
    expect(StubImage.instances).toHaveLength(0);
    expect(warn).not.toHaveBeenCalled();
    // outside keeps its classic inactive colour, fills stay unblended.
    expect(
      document
        .querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.outside);
    expect(
      document.querySelector('[data-layer="nodes"]')?.getAttribute('style'),
    ).toBeFalsy();
  });

  it('warns once and keeps the classic map when the image fails', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    render(<MapView manifest={MANIFEST_ON} geometry={MINI_GEOMETRY} />);
    act(() => lastImage().onerror?.());

    expect(warn).toHaveBeenCalledTimes(1);
    expect(document.querySelector('[data-layer="relief"]')).toBeNull();
    expect(
      document
        .querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.outside);
  });

  it('mounts the raster under the fills after load and blends land', () => {
    render(<MapView manifest={MANIFEST_ON} geometry={MINI_GEOMETRY} />);
    // Map is already usable before the image arrives.
    expect(document.querySelector('[data-layer="relief"]')).toBeNull();
    act(() => lastImage().onload?.());

    const img = document.querySelector(
      '[data-layer="relief"]',
    ) as SVGImageElement;
    expect(img).not.toBeNull();
    expect(img.getAttribute('href')).toContain('/assets/map/relief.');
    expect(img.getAttribute('pointer-events')).toBe('none');

    // Land outside provinces shows through the tint mask.
    const dim = document.querySelector(
      '[data-layer="relief-dim"]',
    ) as SVGPathElement;
    expect(dim).not.toBeNull();
    expect(dim.getAttribute('fill')).toBe(
      MANIFEST_ON.rules.relief.inactive_tint,
    );

    // The `outside` shape becomes sea colour under the picture.
    expect(
      document
        .querySelectorAll(`path[d="${MINI_GEOMETRY.outside}"]`)[0]
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.sea);

    // A second relief copy sits above the land fills and multiplies
    // them — masked to the complement of `outside` so only playable
    // land is shaded; the fills group itself stays unblended.
    const mult = document.querySelector(
      '[data-layer="relief-mult"]',
    ) as SVGImageElement;
    expect(mult).not.toBeNull();
    expect(mult.getAttribute('mask')).toBe('url(#pg-relief-playable)');
    expect(mult.getAttribute('style')).toContain(
      'mix-blend-mode: multiply',
    );
    expect(mult.getAttribute('style')).toContain(
      `opacity: ${MANIFEST_ON.rules.relief.strength_playable}`,
    );
    const nodes = document.querySelector(
      '[data-layer="nodes"]',
    ) as SVGGElement;
    expect(nodes.getAttribute('style')).toBeNull();
    expect(nodes.querySelectorAll('path').length).toBe(8);
    const seaGroup = document.querySelector(
      '[data-layer="sea-nodes"]',
    ) as SVGGElement;
    expect(seaGroup.querySelectorAll('path').length).toBe(2);

    // Draw order: outside < relief < dim < sea-nodes < nodes < mult.
    const layers = [
      '[data-layer="inland-water"]',
      '[data-layer="relief"]',
      '[data-layer="relief-dim"]',
      '[data-layer="sea-nodes"]',
      '[data-layer="nodes"]',
      '[data-layer="relief-mult"]',
    ];
    const order = layers.map(
      (sel) =>
        Array.from(document.querySelectorAll('[data-layer]')).findIndex(
          (el) => el.matches(sel),
        ),
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});
