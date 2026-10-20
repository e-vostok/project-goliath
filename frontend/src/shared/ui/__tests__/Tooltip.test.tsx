/**
 * Tooltip — the «Подсказка» (UI Spec 3.4, version 0.9.0 unit 11):
 * opens at the cursor after 500 ms, follows the pointer one update
 * per animation frame, closes on leave / pointerdown / scroll / Esc /
 * blur, is clamped to the app root container (right-edge inset,
 * bottom flip, top clamp), renders hidden-then-measured and is
 * `pointer-events: none`. Portaled INTO `[data-testid="app-root"]`.
 */

import {
  act,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ReactNode } from 'react';

import { Tooltip, TOOLTIP_DELAY_MS } from '../Tooltip';
import { applyThemeVars } from '../tokens';

// jsdom has no PointerEvent — MouseEvent carries clientX/Y and
// relatedTarget, everything the pointer handlers under test read.
if (window.PointerEvent === undefined) {
  vi.stubGlobal('PointerEvent', window.MouseEvent);
}

/* ------------------------------------------------- deterministic rAF */

const rafQueue = new Map<number, FrameRequestCallback>();
let rafSeq = 0;

vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
  const id = ++rafSeq;
  rafQueue.set(id, cb);
  return id;
});
vi.stubGlobal('cancelAnimationFrame', (id: number) => {
  rafQueue.delete(id);
});

/** Runs the queued animation frame callbacks once. */
function flushFrames() {
  act(() => {
    const cbs = [...rafQueue.values()];
    rafQueue.clear();
    for (const cb of cbs) {
      cb(0);
    }
  });
}

/* --------------------------------------------------------- harness */

function Harness({
  content = 'Подсказка',
  delayMs,
  theme,
}: {
  content?: ReactNode | (() => ReactNode);
  delayMs?: number;
  theme?: 'dark' | 'light';
}) {
  return (
    <div
      data-testid="app-root"
      ref={(el) => {
        if (el !== null && theme !== undefined) {
          applyThemeVars(el, theme);
        }
      }}
      style={{ position: 'relative' }}
    >
      <Tooltip content={content} delayMs={delayMs}>
        <button type="button" data-testid="trigger">
          trigger
        </button>
      </Tooltip>
    </div>
  );
}

const appRoot = () => screen.getByTestId('app-root');
const trigger = () => screen.getByTestId('trigger');
const tip = () => screen.queryByTestId('tooltip');

function enter(x = 10, y = 10) {
  fireEvent.pointerOver(trigger(), { clientX: x, clientY: y });
}

function leave() {
  fireEvent.pointerOut(trigger(), { relatedTarget: document.body });
}

function openTip(x = 10, y = 10) {
  enter(x, y);
  act(() => {
    vi.advanceTimersByTime(TOOLTIP_DELAY_MS);
  });
}

/* --------------------------------------- getBoundingClientRect mock */

const asRect = (
  x: number,
  y: number,
  width: number,
  height: number,
): DOMRect =>
  ({
    x,
    y,
    width,
    height,
    top: y,
    left: x,
    right: x + width,
    bottom: y + height,
    toJSON: () => ({}),
  }) as DOMRect;

/** The app root and the tip box get sizes; everything else is zero. */
function mockRects(
  hostWidth: number,
  hostHeight: number,
  tipWidth: number,
  tipHeight: number,
) {
  return vi
    .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    .mockImplementation(function (this: HTMLElement) {
      if (this.dataset?.testid === 'app-root') {
        return asRect(0, 0, hostWidth, hostHeight);
      }
      if (this.getAttribute('role') === 'tooltip') {
        return asRect(0, 0, tipWidth, tipHeight);
      }
      return asRect(0, 0, 0, 0);
    });
}

afterEach(() => {
  vi.useRealTimers();
  rafQueue.clear();
  vi.restoreAllMocks();
});

describe('Tooltip — open and close', () => {
  it('does not open before the delay; opens after 500 ms', () => {
    vi.useFakeTimers();
    render(<Harness />);

    enter();
    act(() => {
      vi.advanceTimersByTime(TOOLTIP_DELAY_MS - 1);
    });
    expect(tip()).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(tip()).toBeInTheDocument();
    expect(tip()).toHaveAttribute('role', 'tooltip');
  });

  it('leaving before the delay never opens; leaving while open closes at once', () => {
    vi.useFakeTimers();
    render(<Harness />);

    enter();
    act(() => {
      vi.advanceTimersByTime(TOOLTIP_DELAY_MS - 1);
    });
    leave();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(tip()).toBeNull();

    openTip();
    expect(tip()).toBeInTheDocument();
    leave();
    expect(tip()).toBeNull();
  });

  it('a pointerdown, a scroll, Esc and a window blur close it', () => {
    vi.useFakeTimers();
    render(<Harness />);

    openTip();
    fireEvent.pointerDown(trigger());
    expect(tip()).toBeNull();

    openTip();
    fireEvent.scroll(appRoot());
    expect(tip()).toBeNull();

    openTip();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(tip()).toBeNull();

    openTip();
    act(() => {
      window.dispatchEvent(new Event('blur'));
    });
    expect(tip()).toBeNull();
  });
});

describe('Tooltip — position and following', () => {
  it('opens at the CURRENT pointer position — the move during the delay wins', () => {
    mockRects(910, 600, 100, 40);
    vi.useFakeTimers();
    render(<Harness />);

    enter(10, 10);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    fireEvent.pointerMove(trigger(), { clientX: 200, clientY: 120 });
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // +12 right / +16 below the last known spot, not the entry point.
    expect(tip()!.style.left).toBe('212px');
    expect(tip()!.style.top).toBe('136px');
  });

  it('follows the pointer — at most one update per animation frame', () => {
    mockRects(910, 600, 100, 40);
    vi.useFakeTimers();
    render(<Harness />);
    openTip();

    fireEvent.pointerMove(trigger(), { clientX: 300, clientY: 200 });
    fireEvent.pointerMove(trigger(), { clientX: 400, clientY: 250 });
    // Two moves, one queued frame — the position updates once.
    expect(rafQueue.size).toBe(1);
    expect(tip()!.style.left).toBe('22px');

    flushFrames();
    expect(tip()!.style.left).toBe('412px');
    expect(tip()!.style.top).toBe('266px');
  });

  it('keeps following while its content changes', () => {
    mockRects(910, 600, 100, 40);
    vi.useFakeTimers();
    const { rerender } = render(<Harness content={<span>v1</span>} />);
    openTip();

    rerender(<Harness content={<span>v2 — wider content</span>} />);
    expect(tip()).toHaveTextContent('v2 — wider content');

    fireEvent.pointerMove(trigger(), { clientX: 150, clientY: 90 });
    flushFrames();
    expect(tip()!.style.left).toBe('162px');
    expect(tip()!.style.top).toBe('106px');
  });

  it('slides along the right edge — 8 px inset, continuously', () => {
    mockRects(300, 200, 100, 40);
    vi.useFakeTimers();
    render(<Harness />);

    // Pointer near the edge: 250 + 12 + 100 > 300 → shifts to the inset.
    openTip(250, 100);
    expect(tip()!.style.left).toBe('192px'); // 300 − 8 − 100

    fireEvent.pointerMove(trigger(), { clientX: 100, clientY: 100 });
    flushFrames();
    expect(tip()!.style.left).toBe('112px'); // back to cursor +12
  });

  it('flips above the pointer at the bottom and returns below when the pointer moves up', () => {
    mockRects(300, 200, 100, 40);
    vi.useFakeTimers();
    render(<Harness />);

    // 190 + 16 + 40 > 200 → above: 190 − 16 − 40.
    openTip(100, 190);
    expect(tip()!.style.top).toBe('134px');

    fireEvent.pointerMove(trigger(), { clientX: 100, clientY: 100 });
    flushFrames();
    expect(tip()!.style.top).toBe('116px'); // 100 + 16, below again
  });

  it('clamps to the container top — a tall tip near the bottom never goes above 0', () => {
    mockRects(300, 200, 100, 180);
    vi.useFakeTimers();
    render(<Harness />);

    // Flip: 190 − 16 − 180 = −6 → clamped to the top.
    openTip(100, 190);
    expect(tip()!.style.top).toBe('0px');
  });
});

describe('Tooltip — container, behaviour and look', () => {
  it('portals INTO the app root container, is absolute and pointer-events: none', () => {
    vi.useFakeTimers();
    render(<Harness />);
    openTip();

    const box = tip()!;
    expect(appRoot().contains(box)).toBe(true);
    expect(box.style.position).toBe('absolute');
    expect(box.style.pointerEvents).toBe('none');
  });

  it('links the trigger with aria-describedby while open only', () => {
    vi.useFakeTimers();
    render(<Harness />);

    const wrapper = trigger().parentElement!;
    expect(wrapper).not.toHaveAttribute('aria-describedby');

    openTip();
    expect(wrapper).toHaveAttribute('aria-describedby', tip()!.id);

    leave();
    expect(wrapper).not.toHaveAttribute('aria-describedby');
  });

  it.each(['dark', 'light'] as const)(
    'renders in the %s theme through tokens only',
    (theme) => {
      vi.useFakeTimers();
      render(<Harness theme={theme} />);
      openTip();

      const box = tip()!;
      expect(appRoot()).toHaveAttribute('data-theme', theme);
      expect(box.style.background).toBe('var(--pax-surface-raised)');
      expect(box.style.boxShadow).toBe('var(--pax-shadow-tip)');
    },
  );

  it('has no hard-coded colour in its source (UI Spec 5)', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/shared/ui/Tooltip.tsx'),
      'utf8',
    );
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(source).not.toMatch(/\brgba?\(/);
  });
});
