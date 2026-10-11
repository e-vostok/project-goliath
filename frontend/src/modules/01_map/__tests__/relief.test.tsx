/**
 * Relief underlay (map2_16): two lazy rasters — the near-black inactive
 * world and the playable relief — below the province fills. The map
 * must work identically without them — disabled config or a failed
 * image load means no layers, no errors, one console warning — and
 * once loaded, land fills multiply over the playable picture while
 * the sea keeps its plain colour everywhere.
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

async function fireAll(event: 'onload' | 'onerror') {
  // Async act: the hook resolves the load promises on a microtask,
  // then commits the state — await flushes both.
  await act(async () => {
    for (const img of StubImage.instances) {
      img[event]?.();
    }
  });
}

describe('MapView — relief layers (map2_16)', () => {
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

    expect(
      document.querySelector('[data-layer="relief-inactive"]'),
    ).toBeNull();
    expect(
      document.querySelector('[data-layer="relief-playable"]'),
    ).toBeNull();
    expect(StubImage.instances).toHaveLength(0);
    expect(warn).not.toHaveBeenCalled();
    // outside keeps its classic inactive colour.
    expect(
      document
        .querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.outside);
  });

  it('warns once and keeps the classic map when both images fail', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    render(<MapView manifest={MANIFEST_ON} geometry={MINI_GEOMETRY} />);
    await fireAll('onerror');

    expect(warn).toHaveBeenCalledTimes(1);
    expect(
      document.querySelector('[data-layer="relief-inactive"]'),
    ).toBeNull();
    expect(
      document.querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.outside);
  });

  it('keeps working when only the world image fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    render(<MapView manifest={MANIFEST_ON} geometry={MINI_GEOMETRY} />);
    await act(async () => {
      StubImage.instances[0].onerror?.();
      StubImage.instances[1].onload?.();
    });

    expect(warn).not.toHaveBeenCalled();
    expect(
      document.querySelector('[data-layer="relief-inactive"]'),
    ).toBeNull();
    expect(
      document.querySelector('[data-layer="relief-playable"]'),
    ).not.toBeNull();
    // No world image → `outside` keeps the classic flat colour rather
    // than going transparent-sea with nothing painted under it.
    expect(
      document
        .querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.outside);
  });

  it('mounts both rasters in order and multiplies playable land', async () => {
    render(<MapView manifest={MANIFEST_ON} geometry={MINI_GEOMETRY} />);
    // Map is already usable before the images arrive.
    expect(
      document.querySelector('[data-layer="relief-inactive"]'),
    ).toBeNull();
    await fireAll('onload');

    const inactive = document.querySelector(
      '[data-layer="relief-inactive"]',
    ) as SVGImageElement;
    const playable = document.querySelector(
      '[data-layer="relief-playable"]',
    ) as SVGImageElement;
    expect(inactive).not.toBeNull();
    expect(playable).not.toBeNull();
    expect(inactive.getAttribute('href')).toContain(
      '/assets/map/relief.inactive.',
    );
    expect(playable.getAttribute('href')).toContain(
      '/assets/map/relief.playable.',
    );
    expect(inactive.getAttribute('pointer-events')).toBe('none');

    // No masks anywhere — alpha is baked into both images.
    expect(document.querySelector('mask')).toBeNull();
    expect(
      document.querySelector('[data-layer="relief-dim"]'),
    ).toBeNull();

    // `outside` drops to sea colour: the world image paints the land.
    expect(
      document
        .querySelector(`path[d="${MINI_GEOMETRY.outside}"]`)
        ?.getAttribute('fill'),
    ).toBe(MINI_RULES.colors.sea);

    // A copy of the playable raster sits above the fills in multiply —
    // unmasked (its alpha already ends at the province edge).
    const mult = document.querySelector(
      '[data-layer="relief-mult"]',
    ) as SVGImageElement;
    expect(mult).not.toBeNull();
    expect(mult.getAttribute('mask')).toBeNull();
    expect(mult.getAttribute('style')).toContain(
      'mix-blend-mode: multiply',
    );
    expect(mult.getAttribute('style')).toContain(
      `opacity: ${MANIFEST_ON.rules.relief.strength_playable}`,
    );
    const nodes = document.querySelector(
      '[data-layer="nodes"]',
    ) as SVGGElement;
    // Anti-aliased fills are back (map2_16 removed optimizeSpeed).
    expect(nodes.getAttribute('shape-rendering')).toBeNull();
    expect(nodes.querySelectorAll('path').length).toBe(8);
    const seaGroup = document.querySelector(
      '[data-layer="sea-nodes"]',
    ) as SVGGElement;
    expect(seaGroup.querySelectorAll('path').length).toBe(2);

    // Draw order: sea < inactive < playable < fills < mult.
    const layers = [
      '[data-layer="inland-water"]',
      '[data-layer="relief-inactive"]',
      '[data-layer="relief-playable"]',
      '[data-layer="sea-nodes"]',
      '[data-layer="nodes"]',
      '[data-layer="relief-mult"]',
    ];
    const order = layers.map((sel) =>
      Array.from(document.querySelectorAll('[data-layer]')).findIndex(
        (el) => el.matches(sel),
      ),
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});
