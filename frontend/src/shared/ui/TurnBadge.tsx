/**
 * Turn badge (UI Spec 6, элемент 4): `signal` fill, `on-signal` text,
 * mono 12 px, `radius-sm` — «ХОД 1 · ЯНВАРЬ 2040» in the top bar.
 */

import type { ReactNode } from 'react';

import { FONTS, RADII, tokenVar } from './tokens';

export function TurnBadge({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        fontFamily: FONTS.mono,
        fontSize: 12,
        lineHeight: '16px',
        background: tokenVar('signal'),
        color: tokenVar('on-signal'),
        padding: '4px 8px',
        borderRadius: RADII['radius-sm'],
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  );
}
