/**
 * useWindowHeight — the ONLY place that sets the VK window height
 * (UI Spec 2, version 0.9.0 unit 4b).
 *
 * A ResizeObserver on the app's root container (the wrapper around
 * the top bar and the layout — NOT the page: VKUI pins the page to
 * the window, so the page is never shorter than it) reports the
 * content height. After a 200 ms debounce the hook sends
 * `VKWebAppResizeWindow` at width 910 with the height rounded up and
 * clamped to 600–4050 px — only when it differs from the last sent
 * value. Outside VK the bridge never answers; errors are swallowed.
 *
 * Paused while the page is fullscreen (the map's «Развернуть на весь
 * экран»): `document.fullscreenElement` means the window is the
 * monitor, not the app; on `fullscreenchange` the content is
 * measured again.
 *
 * Nothing else may call `VKWebAppResizeWindow` — the hand probe in
 * `AdminBlock`/`useAdminProbe` is the sanctioned exception.
 */

import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import bridge from '@vkontakte/vk-bridge';

import { SIZES } from '../shared/ui';

export const WINDOW_HEIGHT_MIN = 600;
export const WINDOW_HEIGHT_MAX = 4050;
export const RESIZE_DEBOUNCE_MS = 200;

/**
 * The pure part: a measured pixel height → the height to send, or
 * `null` when it equals `lastSent` (nothing to tell VK).
 */
export function nextWindowHeight(
  measured: number,
  lastSent: number | null,
): number | null {
  if (!Number.isFinite(measured)) {
    return null;
  }
  const height = Math.min(
    WINDOW_HEIGHT_MAX,
    Math.max(WINDOW_HEIGHT_MIN, Math.ceil(measured)),
  );
  return height === lastSent ? null : height;
}

export function useWindowHeight(
  rootRef: RefObject<HTMLElement | null>,
): void {
  const lastSent = useRef<number | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === 'undefined') {
      return;
    }

    let timer: ReturnType<typeof setTimeout> | null = null;

    const send = () => {
      if (document.fullscreenElement) {
        return;
      }
      const height = nextWindowHeight(root.offsetHeight, lastSent.current);
      if (height === null) {
        return;
      }
      lastSent.current = height;
      try {
        void bridge
          .send('VKWebAppResizeWindow', {
            width: SIZES['win-screen'],
            height,
          })
          .catch(() => {});
      } catch {
        // No bridge at all — outside VK nothing answers.
      }
    };

    const schedule = () => {
      if (timer !== null) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = null;
        send();
      }, RESIZE_DEBOUNCE_MS);
    };

    const observer = new ResizeObserver(schedule);
    observer.observe(root);
    // Entering fullscreen the send above is skipped; leaving it the
    // content height is measured again.
    document.addEventListener('fullscreenchange', schedule);

    return () => {
      observer.disconnect();
      document.removeEventListener('fullscreenchange', schedule);
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [rootRef]);
}
