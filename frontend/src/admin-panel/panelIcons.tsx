/**
 * Panel icons (0.11.0 unit 5a) — the approved panel mockups
 * (docs/06_DESIGN/0.11.0, screens 02 and 09). Two sizes: 18 px /
 * stroke 1.6 for the side menu, 24 px / stroke 1.5 for the gate
 * cards. Colour is inherited (`currentColor`); the caller picks the
 * token — menu items pass `accent` for the active row's signal-ink.
 */

import type { ReactNode } from 'react';

import { tokenVar } from '../shared/ui/tokens';

export type PanelIconName =
  | 'clock'
  | 'players'
  | 'flag'
  | 'pin'
  | 'document'
  | 'shield'
  | 'list';

const PANEL_PATHS: Record<PanelIconName, ReactNode> = {
  clock: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" />
    </>
  ),
  players: (
    <>
      <circle cx="6" cy="5.5" r="2.5" />
      <path d="M1.8 13c.4-2.4 2.2-3.8 4.2-3.8s3.8 1.4 4.2 3.8" />
      <path d="M10.5 3.4a2.4 2.4 0 0 1 0 4.2M12.5 9.6c1 .6 1.7 1.7 1.9 3.4" />
    </>
  ),
  flag: <path d="M3.5 14V2.5M3.5 3h8l-1.6 2.8L11.5 8.5h-8" />,
  pin: (
    <>
      <path d="M8 14.5s4.5-4.2 4.5-7.7a4.5 4.5 0 0 0-9 0c0 3.5 4.5 7.7 4.5 7.7z" />
      <circle cx="8" cy="6.8" r="1.6" />
    </>
  ),
  document: (
    <>
      <path d="M3.8 1.8h5.7l3 3.1v9.3H3.8z" />
      <path d="M9.5 1.8v3.1h3M6 8.2h4.5M6 10.8h4.5" />
    </>
  ),
  shield: (
    <>
      <path d="M8 1.8l5 1.8v4.2c0 3-2.2 5-5 6.4-2.8-1.4-5-3.4-5-6.4V3.6z" />
      <path d="M5.8 8l1.7 1.7L10.5 6.4" />
    </>
  ),
  list: (
    <>
      <path d="M5.5 4h8M5.5 8h8M5.5 12h8" />
      <path
        d="M2.5 4h.01M2.5 8h.01M2.5 12h.01"
        strokeWidth={2.2}
      />
    </>
  ),
};

/** Side-menu / section-title icon: 18 px, stroke 1.6. */
export function PanelIcon({
  name,
  accent = false,
  size = 18,
}: {
  name: PanelIconName;
  /** Active/menu-title colour — `signal-ink` instead of inherited. */
  accent?: boolean;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke={accent ? tokenVar('signal-ink') : 'currentColor'}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block', flexShrink: 0 }}
    >
      {PANEL_PATHS[name]}
    </svg>
  );
}

export type GateIconName = 'lock' | 'shield' | 'offline' | 'clock' | 'logout';

const GATE_PATHS: Record<GateIconName, ReactNode> = {
  lock: (
    <>
      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
    </>
  ),
  shield: (
    <>
      <path d="M8 1.8l5 1.8v4.2c0 3-2.2 5-5 6.4-2.8-1.4-5-3.4-5-6.4V3.6z" />
      <path d="M5.8 8l1.7 1.7L10.5 6.4" />
    </>
  ),
  offline: (
    <>
      <path d="M2.5 6.4a8.5 8.5 0 0 1 11 0M5 9.4a5 5 0 0 1 6 0" />
      <circle cx="8" cy="12.4" r="0.9" />
      <path d="M1.8 1.8l12.4 12.4" />
    </>
  ),
  clock: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" />
    </>
  ),
  logout: (
    <>
      <path d="M9.5 2.5h-5A1.5 1.5 0 0 0 3 4v8a1.5 1.5 0 0 0 1.5 1.5h5" />
      <path d="M6.5 8h7M11 5.5L13.5 8 11 10.5" />
    </>
  ),
};

/** Gate-card icon: 24 px, stroke 1.5, inherits the tile's signal-ink. */
export function GateIcon({ name }: { name: GateIconName }) {
  return (
    <svg
      width={24}
      height={24}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      {GATE_PATHS[name]}
    </svg>
  );
}
