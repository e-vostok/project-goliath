/**
 * Line icons (UI Spec 6, элемент 2): 18 px, stroke 1.6, colour
 * `signal-ink` — the token that equals `signal` in the dark theme and
 * keeps the brass readable in the light one. Paths come from the
 * approved mockups (Main.dc.html / MainLight.dc.html); `list` (Реестр)
 * is drawn in the same style, the mockups do not show it.
 */

import type { ReactNode } from 'react';

import { tokenVar } from './tokens';

export type BlockIconName =
  | 'person'
  | 'map'
  | 'lines'
  | 'text'
  | 'document'
  | 'list'
  | 'scales';

const BLOCK_PATHS: Record<BlockIconName, ReactNode> = {
  person: (
    <>
      <circle cx="8" cy="5.2" r="2.6" />
      <path d="M2.8 14c.4-3.1 2.5-4.8 5.2-4.8s4.8 1.7 5.2 4.8" />
    </>
  ),
  map: (
    <>
      <path d="M1.8 3.8l4.1-1.5 4.2 1.5 4.1-1.5v9.9l-4.1 1.5-4.2-1.5-4.1 1.5z" />
      <path d="M5.9 2.3v9.9M10.1 3.8v9.9" />
    </>
  ),
  lines: (
    <path d="M2.5 3.5h11M2.5 6.8h11M2.5 10.1h11M2.5 13.4h6.5" />
  ),
  text: (
    <path d="M4 4h8M4 7.4h8M4 10.8h8M4 13.6h5" />
  ),
  document: (
    <>
      <path d="M3.8 1.8h5.7l3 3.1v9.3H3.8z" />
      <path d="M9.5 1.8v3.1h3M6 8.2h4.5M6 10.8h4.5" />
    </>
  ),
  list: (
    <path d="M2.2 4h1.4M2.2 8h1.4M2.2 12h1.4M5.8 4h8.4M5.8 8h8.4M5.8 12h8.4" />
  ),
  scales: (
    <>
      <path d="M8 2v11.5M5 14h6M3 4.5h10" />
      <path d="M3 4.5L1.4 8.6h3.2zM13 4.5l-1.6 4.1h3.2z" />
    </>
  ),
};

export function BlockIcon({ name }: { name: BlockIconName }) {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block', flexShrink: 0 }}
    >
      {BLOCK_PATHS[name]}
    </svg>
  );
}

/** Theme toggle icons — 18 px, stroke 1.5, inherit `currentColor`. */
export function MoonIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d="M12.6 9.8A5.4 5.4 0 0 1 6.2 3.4a5.4 5.4 0 1 0 6.4 6.4z" />
    </svg>
  );
}

export function SunIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <circle cx="8" cy="8" r="2.8" />
      <path d="M8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1" />
    </svg>
  );
}

/** Small edit pencil — 18 px, stroke 1.5, inherit `currentColor`. */
export function PencilIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d="M9.9 2.4l3.7 3.7-8.4 8.4-4 .3.3-4z" />
      <path d="M8.9 3.4l3.7 3.7" />
    </svg>
  );
}
