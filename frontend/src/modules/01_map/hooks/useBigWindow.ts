/**
 * useBigWindow — full-page fullscreen mode (Spec «Режим большого окна»).
 *
 * The state comes ONLY from the `fullscreenchange` event and
 * `document.fullscreenElement` — never from the request promise (it may
 * resolve before/without the mode actually applying) and never from a
 * timer. A rejected request or `fullscreenerror` leaves the normal view
 * and surfaces a short message. The button is hidden upstream when
 * `document.fullscreenEnabled` is false or `rules.big_window_enabled`.
 */

import { useCallback, useEffect, useState } from 'react';

export interface BigWindow {
  supported: boolean;
  isFullscreen: boolean;
  /** Short user-facing error after a rejected/failed transition. */
  error: string | null;
  enter: () => void;
  exit: () => void;
}

export function useBigWindow(): BigWindow {
  const [supported] = useState(
    () =>
      typeof document !== 'undefined' && Boolean(document.fullscreenEnabled),
  );
  const [isFullscreen, setIsFullscreen] = useState(() =>
    Boolean(document.fullscreenElement),
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onChange = () => {
      const active = document.fullscreenElement != null;
      setIsFullscreen(active);
      if (active) {
        setError(null);
      }
    };
    const onError = () => {
      setError('Браузер не разрешил полноэкранный режим');
    };
    document.addEventListener('fullscreenchange', onChange);
    document.addEventListener('fullscreenerror', onError);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      document.removeEventListener('fullscreenerror', onError);
    };
  }, []);

  const enter = useCallback(() => {
    try {
      const promise = document.documentElement.requestFullscreen();
      // The state flips on fullscreenchange only; the catch just reports.
      promise?.catch(() =>
        setError('Браузер не разрешил полноэкранный режим'),
      );
    } catch {
      setError('Браузер не разрешил полноэкранный режим');
    }
  }, []);

  const exit = useCallback(() => {
    if (document.fullscreenElement != null && document.exitFullscreen) {
      void document.exitFullscreen().catch(() => {});
    }
  }, []);

  return { supported, isFullscreen, error, enter, exit };
}
