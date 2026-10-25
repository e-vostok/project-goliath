/**
 * Theme mechanism (UI Spec 5.4): three modes «авто / светлая / тёмная»,
 * persisted in localStorage under `pax.theme`, «авто» follows the scheme
 * reported by VK when there is one. The resolved theme is applied in one
 * place — `--pax-*` variables on the provider's wrapper element plus the
 * `appearance` parameter of the VKUI ConfigProvider.
 *
 * The wrapper is content-sized on purpose (UI Spec 2): the VK window
 * follows the content height — nothing may pin it to the window. The
 * `#ui-kit` catalogue keeps its own full-height look in UiKitPage.
 */

import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { ConfigProvider, Platform } from '@vkontakte/vkui';

import { MoonIcon, SunIcon } from './icons';
import { applyThemeVars, RADII, tokenVar } from './tokens';
import type { ThemeName } from './tokens';

export type ThemeMode = 'auto' | 'light' | 'dark';
export type ResolvedTheme = ThemeName;

const STORAGE_KEY = 'pax.theme';

const MODE_TITLES: Record<ThemeMode, string> = {
  auto: 'Тема: авто',
  light: 'Тема: светлая',
  dark: 'Тема: тёмная',
};

const NEXT_MODE: Record<ThemeMode, ThemeMode> = {
  auto: 'light',
  light: 'dark',
  dark: 'auto',
};

/** Schemes VK is known to report for a light interface. */
const KNOWN_LIGHT_SCHEMES = new Set([
  'bright_light',
  'client_light',
  'vkcom_light',
  'light',
]);

export function readStoredMode(): ThemeMode {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' || value === 'auto'
      ? value
      : 'auto';
  } catch {
    return 'auto';
  }
}

export function writeStoredMode(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Storage unavailable — the choice lives until the window closes.
  }
}

/**
 * Spec 5.4: a scheme containing «dark» or equal to `space_gray` (the
 * legacy dark name) means dark; other schemes VK is known to report mean
 * light; an unknown or missing scheme falls back to dark.
 */
export function schemeToTheme(scheme: string | null | undefined): ResolvedTheme {
  if (!scheme) {
    return 'dark';
  }
  if (scheme.includes('dark') || scheme === 'space_gray') {
    return 'dark';
  }
  if (KNOWN_LIGHT_SCHEMES.has(scheme)) {
    return 'light';
  }
  return 'dark';
}

export interface ThemeContextValue {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  /** Raw scheme reported by VK, null when VK reports none. */
  vkScheme: string | null;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error('useTheme must be used inside ThemeProvider');
  }
  return value;
}

export function ThemeProvider({
  children,
  listenVkScheme = true,
}: {
  children: ReactNode;
  /**
   * Whether to subscribe the resolved theme to the scheme VK reports
   * over vk-bridge (Spec 5.4). The admin panel page lives in a bare
   * browser tab and must not import vk-bridge at all — it passes
   * `false`, so «авто» holds the dark fallback there.
   */
  listenVkScheme?: boolean;
}) {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode);
  const [vkScheme, setVkScheme] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Ask VK for its scheme once and keep listening for changes; outside
  // VK both calls simply never answer (Spec 5.4 — «не проверено»).
  // The bridge reaches this provider only through a dynamic import of
  // ./vkScheme: bundles that never run inside VK (the /admin page)
  // pass `listenVkScheme={false}` and neither import vk-bridge nor
  // ever execute this effect.
  useEffect(() => {
    if (!listenVkScheme) {
      return;
    }
    let cancelled = false;
    let unsubscribe: (() => void) | null = null;
    void import('./vkScheme')
      .then((mod) => {
        if (cancelled) {
          return;
        }
        try {
          unsubscribe = mod.subscribeVkScheme((scheme) => {
            if (!cancelled) {
              setVkScheme(scheme);
            }
          });
        } catch {
          // No bridge at all — «авто» stays on the dark fallback.
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [listenVkScheme]);

  const resolved: ResolvedTheme =
    mode === 'auto' ? schemeToTheme(vkScheme) : mode;

  const setMode = (next: ThemeMode) => {
    writeStoredMode(next);
    setModeState(next);
  };

  useLayoutEffect(() => {
    if (wrapRef.current) {
      applyThemeVars(wrapRef.current, resolved);
    }
  }, [resolved]);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, vkScheme }}>
      <ConfigProvider platform={Platform.VKCOM} colorScheme={resolved}>
        <div
          ref={wrapRef}
          style={{
            background: tokenVar('ground'),
            color: tokenVar('ink'),
          }}
        >
          {children}
        </div>
      </ConfigProvider>
    </ThemeContext.Provider>
  );
}

/**
 * Spec 5.4: one quiet 32×32 button; the 18 px icon shows the theme in
 * effect (moon/sun), in «авто» a dot sits next to it; `title` names the
 * mode. Clicking cycles авто → светлая → тёмная.
 */
export function ThemeToggle() {
  const { mode, resolved, setMode } = useTheme();
  const title = MODE_TITLES[mode];
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={() => setMode(NEXT_MODE[mode])}
      style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 32,
        height: 32,
        padding: 0,
        border: 'none',
        borderRadius: RADII['radius-md'],
        background: 'transparent',
        color: tokenVar('ink-muted'),
        cursor: 'pointer',
        flexShrink: 0,
      }}
    >
      {resolved === 'dark' ? <MoonIcon /> : <SunIcon />}
      {mode === 'auto' && (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            right: 4,
            bottom: 4,
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: tokenVar('signal'),
          }}
        />
      )}
    </button>
  );
}
