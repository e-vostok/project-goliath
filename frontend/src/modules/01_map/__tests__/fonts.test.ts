/**
 * Map font registry (map2_21): the six bundled faces all stack onto
 * the generic family matching their type — `monospace` for the
 * terminal cuts, `sans-serif` for the condensed sans — so a missing or
 * still-loading bundle can never fall through to the browser's serif.
 * The client-side defaults pick the terminal face, and a face that
 * fails to load resolves `false` so the caller keeps the generic tail.
 */

import {
  ensureMapFont,
  MAP_FONT_KEYS,
  MAP_FONTS,
} from '../lib/fonts';
import { SPINE_DEFAULTS } from '../lib/labels';

describe('map font registry (map2_21)', () => {
  it('every stack ends with the generic family matching the face type', () => {
    for (const key of MAP_FONT_KEYS) {
      const spec = MAP_FONTS[key];
      const parts = spec.family.split(',');
      const tail = parts[parts.length - 1].trim();
      expect(tail, key).toBe(spec.mono ? 'monospace' : 'sans-serif');
      expect(spec.family.startsWith(`${spec.face},`), key).toBe(true);
    }
    // Three terminal cuts + three condensed sans cuts, nothing else.
    expect(MAP_FONT_KEYS).toHaveLength(6);
    expect(
      MAP_FONT_KEYS.filter((k) => MAP_FONTS[k].mono),
    ).toHaveLength(3);
  });

  it('the client-side defaults are the terminal monospace face', () => {
    // labels.font / labels.sea_font / states.font all default to the
    // terminal mono cut — configs/01_map.yaml is pinned by the backend
    // config test; here the client-side fallback must be a mono face
    // (Share Tech Mono ships no Cyrillic subset — the default is the
    // Cyrillic-complete PT Mono).
    expect(MAP_FONTS[SPINE_DEFAULTS.sea_font].mono).toBe(true);
  });

  it('a face that never loads resolves false within the timeout', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'fonts', {
      configurable: true,
      value: {
        load: () => new Promise(() => {}), // never resolves
        check: () => false,
        ready: Promise.resolve(),
        addEventListener: () => {},
        removeEventListener: () => {},
      },
    });
    try {
      const pending = ensureMapFont('"PT Mono"', 100);
      await vi.advanceTimersByTimeAsync(150);
      await expect(pending).resolves.toBe(false);
    } finally {
      vi.useRealTimers();
      delete (document as { fonts?: unknown }).fonts;
    }
  });
});
