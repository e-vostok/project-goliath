/**
 * Stat tile (UI Spec 6, элемент 3): `surface-raised`, 1 px `line`
 * border, `radius-lg`; `label` on top, `figure-lg` value below. A key
 * figure (`accent`) keeps the brass `signal-ink` in both themes.
 */

import type { ReactNode } from 'react';

import { RADII, SPACING, TEXT_STYLES, tokenVar } from './tokens';

export function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: ReactNode;
  accent?: boolean;
}) {
  return (
    <div
      style={{
        background: tokenVar('surface-raised'),
        border: `1px solid ${tokenVar('line')}`,
        borderRadius: RADII['radius-lg'],
        padding: `${SPACING['space-3']}px ${SPACING['space-4']}px`,
      }}
    >
      <div style={{ ...TEXT_STYLES['label'], color: tokenVar('ink-muted') }}>
        {label}
      </div>
      <div
        style={{
          ...TEXT_STYLES['figure-lg'],
          color: accent ? tokenVar('signal-ink') : tokenVar('ink'),
        }}
      >
        {value}
      </div>
    </div>
  );
}
