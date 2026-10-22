/**
 * Design tokens — the ONLY file in the frontend with colour and size
 * values (UI Spec `docs/02_SYSTEM_SPECS/00_core_ui.md`, п. 5). Every
 * window reads colours through `tokenVar` / CSS variables; hard-coded
 * hex outside this file is forbidden.
 */

import type { CSSProperties } from 'react';

export type ThemeName = 'dark' | 'light';

/** Spec 5.1 — every colour token exists in both themes. */
export const THEME_COLORS = {
  dark: {
    'ground': '#141414',
    'surface': '#222222',
    'surface-raised': '#292929',
    'surface-inset': '#333333',
    'line': '#363738',
    'ink': '#e1e3e6',
    'ink-muted': '#939393',
    'ink-faint': '#828282',
    'action': '#71aaeb',
    'link': '#71aaeb',
    'signal': '#e3b04b',
    'on-signal': '#241a06',
    'signal-ink': '#e3b04b',
    'danger': '#ff5c5c',
    'positive': '#4bb34b',
    'warning-bg': '#473315',
    'swatch-edge': 'rgba(255,255,255,0.18)',
  },
  light: {
    'ground': '#edeef0',
    'surface': '#ffffff',
    'surface-raised': '#ffffff',
    'surface-inset': '#f0f2f5',
    'line': '#dce1e6',
    'ink': '#000000',
    'ink-muted': '#626d7a',
    'ink-faint': '#818c99',
    'action': '#447bba',
    'link': '#2a5885',
    'signal': '#e3b04b',
    'on-signal': '#241a06',
    'signal-ink': '#7a5200',
    'danger': '#b83232',
    'positive': '#2a7230',
    'warning-bg': '#fff2d6',
    'swatch-edge': 'rgba(0,0,0,0.15)',
  },
} as const;

export type ColorToken = keyof (typeof THEME_COLORS)['dark'];

/** Spec 5.2 — shadows differ per theme (black 50 %/18 % and 45 %/16 %). */
export const THEME_SHADOWS = {
  dark: {
    'shadow-popup': '0 8px 24px rgba(0,0,0,0.5)',
    'shadow-tip': '0 4px 12px rgba(0,0,0,0.45)',
  },
  light: {
    'shadow-popup': '0 8px 24px rgba(0,0,0,0.18)',
    'shadow-tip': '0 4px 12px rgba(0,0,0,0.16)',
  },
} as const;

export type ShadowToken = keyof (typeof THEME_SHADOWS)['dark'];

/** Spec 5.2 — spacing scale, px. */
export const SPACING = {
  'space-1': 4,
  'space-2': 8,
  'space-3': 12,
  'space-4': 16,
  'space-5': 24,
  'space-6': 32,
} as const;

/** Spec 5.2 — corner radii, px. */
export const RADII = {
  'radius-sm': 4,
  'radius-md': 8,
  'radius-lg': 12,
  'radius-pill': 999,
} as const;

/** Spec 5.2 — window and control sizes, px. */
export const SIZES = {
  'win-screen': 910,
  'win-popup-s': 480,
  'win-popup-m': 640,
  'win-popup-l': 880,
  'win-tooltip-max': 320,
  'topbar-h': 48,
  'row-compact': 36,
  'button-h': 36,
  'button-h-small': 32,
} as const;

/** Spec 5.3 — font stacks. */
export const FONTS = {
  heading: "'Fira Sans Condensed','Roboto Condensed',sans-serif",
  mono: "'JetBrains Mono',ui-monospace,monospace",
  body: "-apple-system,BlinkMacSystemFont,'Roboto','Helvetica Neue',arial,sans-serif",
  wordmark:
    "'Big Shoulders Display','Fira Sans Condensed','Roboto Condensed',sans-serif",
} as const;

/** Spec 5.3 — named text styles, ready to spread into `style`. */
export const TEXT_STYLES = {
  'title-uppercase': {
    fontFamily: FONTS.heading,
    fontWeight: 500,
    fontSize: 18,
    lineHeight: '22px',
    letterSpacing: '.06em',
    textTransform: 'uppercase',
  },
  'display-lg': {
    fontFamily: FONTS.heading,
    fontWeight: 500,
    fontSize: 26,
    lineHeight: '30px',
  },
  'heading': {
    fontFamily: FONTS.heading,
    fontWeight: 500,
    fontSize: 16,
    lineHeight: '20px',
  },
  'body': {
    fontFamily: FONTS.body,
    fontWeight: 400,
    fontSize: 14,
    lineHeight: '20px',
  },
  'caption': {
    fontFamily: FONTS.body,
    fontWeight: 400,
    fontSize: 12,
    lineHeight: '16px',
  },
  'label': {
    fontFamily: FONTS.heading,
    fontWeight: 500,
    fontSize: 11,
    lineHeight: '14px',
    letterSpacing: '.06em',
    textTransform: 'uppercase',
  },
  'figure': {
    fontFamily: FONTS.mono,
    fontWeight: 400,
    fontSize: 14,
    lineHeight: '20px',
  },
  'figure-lg': {
    fontFamily: FONTS.mono,
    fontWeight: 400,
    fontSize: 22,
    lineHeight: '28px',
  },
} as const satisfies Record<string, CSSProperties>;

export type TextStyleName = keyof typeof TEXT_STYLES;

/** `tokenVar('surface')` → `var(--pax-surface)` — colours only. */
export function tokenVar(token: ColorToken): string {
  return `var(--pax-${token})`;
}

/** `shadowVar('shadow-popup')` → `var(--pax-shadow-popup)`. */
export function shadowVar(token: ShadowToken): string {
  return `var(--pax-${token})`;
}

/**
 * The single place where a theme becomes CSS: sets every `--pax-*`
 * colour and shadow variable plus the `data-theme` attribute and
 * `color-scheme` on the given element (Spec 5.4).
 */
export function applyThemeVars(element: HTMLElement, theme: ThemeName): void {
  const colors = THEME_COLORS[theme];
  for (const name of Object.keys(colors) as ColorToken[]) {
    element.style.setProperty(`--pax-${name}`, colors[name]);
  }
  const shadows = THEME_SHADOWS[theme];
  for (const name of Object.keys(shadows) as ShadowToken[]) {
    element.style.setProperty(`--pax-${name}`, shadows[name]);
  }
  element.dataset.theme = theme;
  element.style.colorScheme = theme;
}
