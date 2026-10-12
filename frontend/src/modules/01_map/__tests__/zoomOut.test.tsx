/**
 * Zoom-out relayout gating + bundled-font fallback (map2_21): a wheel
 * storm from the maximum zoom runs NO label layout per step — at most
 * the single threshold-crossing build, then one re-fit at settle — and
 * the LAND↔SEA swap is a fade of the two kind groups, not per-label
 * animations. A bundled face that never loads leaves the generic tail
 * of its stack (monospace, never serif) and logs exactly one warning.
 */

import { render, waitFor } from '@testing-library/react';

import { MapView } from '../components/MapView';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
} from '../fixtures/miniMap';
import { FONT_LOAD_TIMEOUT_MS } from '../lib/fonts';

interface LabelStat {
  scale: number;
  ms: number;
  placed: number;
}

const stats = (): LabelStat[] => {
  const g = globalThis as { __pgLabelStats?: LabelStat[] };
  g.__pgLabelStats ??= [];
  return g.__pgLabelStats;
};

const container = () =>
  document.querySelector('[data-testid="map-view"]') as HTMLElement;

// Wheel at the mini map's mid chain — provinces 1003/1004 keep their
// labels in view at the maximum zoom (map point ~(25,25) sits at
// screen (220,180) under the initial fit transform).
const wheel = (deltaY: number) =>
  container().dispatchEvent(
    new WheelEvent('wheel', {
      deltaY,
      clientX: 220,
      clientY: 180,
      bubbles: true,
      cancelable: true,
    }),
  );

describe('MapView — zoom-out layout gating and group crossfade (map2_21)', () => {
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

  it('wheel storm defers layout to settle; kind groups swap as one transition', async () => {
    render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
      />,
    );
    // Zoom in to the clamp (zoom_max 8 ≈ 10 notches) and let the
    // settle window fire — the province set is laid out once.
    for (let i = 0; i < 12; i += 1) {
      wheel(-100);
    }
    const landG = document.querySelector(
      'g[data-labelkind="LAND"]',
    ) as SVGGElement;
    const seaG = document.querySelector(
      'g[data-labelkind="SEA"]',
    ) as SVGGElement;
    expect(landG).not.toBeNull();
    expect(seaG).not.toBeNull();
    await waitFor(
      () => {
        expect(stats().length).toBeGreaterThan(0);
        expect(landG.hasAttribute('data-off')).toBe(false);
        expect(seaG.hasAttribute('data-off')).toBe(true);
      },
      { timeout: 1500 },
    );

    // A wheel-out storm: the very first step crosses the 0.98·max
    // threshold — ONE mid-gesture layout builds the incoming kind's
    // set — and the next steps run no layout at all while the gesture
    // continues. The province group fades out as ONE element.
    stats().length = 0;
    for (let i = 0; i < 8; i += 1) {
      wheel(100);
    }
    await waitFor(() => {
      expect(landG.hasAttribute('data-off')).toBe(true);
      expect(stats().length).toBe(1);
    });
    // The fade lives on the two kind groups — one CSS transition each —
    // not on the individual <text> elements.
    const css = [...document.querySelectorAll('style')]
      .map((s) => s.textContent ?? '')
      .join('\n');
    expect(css).toContain("g[data-labelkind][data-off]");
    expect(css).not.toContain(
      "g[data-layer='labels'] > text[data-off]",
    );

    // Settle: exactly one more layout re-fits the sea set at the
    // settled scale — the gesture ran at most one layout per 120 ms.
    await waitFor(
      () => expect(stats().length).toBe(2),
      { timeout: 1500 },
    );
  });
});

describe('MapView — bundled font loading (map2_21)', () => {
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
  afterEach(() => {
    vi.restoreAllMocks();
    delete (document as { fonts?: unknown }).fonts;
  });

  it('a face that never loads warns once and keeps the generic family', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    Object.defineProperty(document, 'fonts', {
      configurable: true,
      value: {
        // load() never resolves — the face never arrives.
        load: () => new Promise(() => {}),
        check: () => false,
        ready: Promise.resolve(),
        addEventListener: () => {},
        removeEventListener: () => {},
      },
    });
    render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
      />,
    );
    await vi.advanceTimersByTimeAsync(FONT_LOAD_TIMEOUT_MS + 200);
    // All three keys default to the same face → exactly one warning.
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toContain('PT Mono');
    // The stack's generic tail is what draws — it must be monospace,
    // never a serif and never an unset family.
    const text = document.querySelector(
      'text.pg-map-label',
    ) as SVGTextElement | null;
    if (text !== null) {
      expect(text.getAttribute('font-family')).toMatch(/monospace$/);
    }
    vi.useRealTimers();
  });
});
