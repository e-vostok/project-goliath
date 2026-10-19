/**
 * Flag placeholder (UI Spec 6, элемент 8): `surface-inset` block in
 * `radius-sm` until real flag images arrive — 96×64 on the nation card,
 * 32×22 in a table row.
 */

import { RADII, tokenVar } from './tokens';

const VARIANTS = {
  card: { width: 96, height: 64 },
  row: { width: 32, height: 22 },
} as const;

export function FlagStub({ variant = 'card' }: { variant?: keyof typeof VARIANTS }) {
  const { width, height } = VARIANTS[variant];
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Заглушка флага"
      style={{ flexShrink: 0, display: 'block', borderRadius: RADII['radius-sm'] }}
    >
      <rect width={width} height={height} fill={tokenVar('surface-inset')} />
    </svg>
  );
}
