/**
 * useWindowHeight — the single place that sizes the VK window
 * (UI Spec 2, unit 4b). The pure part clamps to 600–4050, rounds up
 * and reports «unchanged»; the hook debounces a ResizeObserver burst
 * into one VKWebAppResizeWindow call and stays silent while the
 * measured size does not change.
 */

import { renderHook } from '@testing-library/react';

// The hook calls VK Bridge; outside VK it would hit a real
// postMessage — stub it (same pattern as 03_registry tests).
vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

import bridge from '@vkontakte/vk-bridge';

import { nextWindowHeight, useWindowHeight } from '../useWindowHeight';

const sendMock = vi.mocked(bridge.send);

type ResizeCallback = () => void;

/** A ResizeObserver the test can fire by hand. */
class FakeResizeObserver {
  static callbacks: ResizeCallback[] = [];

  constructor(callback: ResizeCallback) {
    FakeResizeObserver.callbacks.push(callback);
  }

  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  FakeResizeObserver.callbacks = [];
  vi.stubGlobal('ResizeObserver', FakeResizeObserver);
  sendMock.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function fireResize() {
  for (const callback of FakeResizeObserver.callbacks) {
    callback();
  }
}

describe('nextWindowHeight', () => {
  it('clamps to 600…4050, rounds up and reports an unchanged value', () => {
    expect(nextWindowHeight(120, null)).toBe(600);
    expect(nextWindowHeight(0, null)).toBe(600);
    expect(nextWindowHeight(9999, null)).toBe(4050);
    expect(nextWindowHeight(900.2, null)).toBe(901);
    // Same resolved height as last sent → nothing to send.
    expect(nextWindowHeight(900.2, 901)).toBeNull();
    expect(nextWindowHeight(800, 800)).toBeNull();
  });
});

describe('useWindowHeight', () => {
  it('sends once for a burst of size changes and not again for an unchanged size', () => {
    vi.useFakeTimers();
    const el = document.createElement('div');
    let measured = 800;
    Object.defineProperty(el, 'offsetHeight', {
      configurable: true,
      get: () => measured,
    });

    renderHook(() => useWindowHeight({ current: el }));
    expect(FakeResizeObserver.callbacks).toHaveLength(1);

    // A burst collapses into a single debounced send.
    fireResize();
    fireResize();
    fireResize();
    vi.advanceTimersByTime(200);
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith('VKWebAppResizeWindow', {
      width: 910,
      height: 800,
    });

    // The same height again — VK hears nothing.
    fireResize();
    vi.advanceTimersByTime(200);
    expect(sendMock).toHaveBeenCalledTimes(1);

    // A real change goes out once more.
    measured = 1200;
    fireResize();
    vi.advanceTimersByTime(200);
    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock).toHaveBeenLastCalledWith('VKWebAppResizeWindow', {
      width: 910,
      height: 1200,
    });
  });
});
