/**
 * Flag placeholder (UI Spec 6, элемент 8): a `surface-inset` block —
 * 96×64 on the nation card (`card`), 180×120 at registration
 * (`registration`), 48×32 on the player subscreen (`sub`), 28×19 in a
 * tooltip heading (`row`), 22×14 in a table cell (`cell`). With
 * `color` the block is filled with the nation's colour instead —
 * the flag stub IS the nation colour (UI Spec 6, элемент 8).
 */

import { RADII, tokenVar } from './tokens';

const VARIANTS = {
  card: { width: 96, height: 64, radius: RADII['radius-sm'] },
  registration: { width: 180, height: 120, radius: RADII['radius-md'] },
  sub: { width: 48, height: 32, radius: RADII['radius-sm'] },
  row: { width: 28, height: 19, radius: RADII['radius-sm'] },
  cell: { width: 22, height: 14, radius: RADII['radius-sm'] },
} as const;

export function FlagStub({
  variant = 'card',
  color,
}: {
  variant?: keyof typeof VARIANTS;
  /** The nation's `#RRGGBB` — the stub is a block in its colour. */
  color?: string;
}) {
  const { width, height, radius } = VARIANTS[variant];
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Заглушка флага"
      style={{ flexShrink: 0, display: 'block', borderRadius: radius }}
    >
      <rect
        width={width}
        height={height}
        fill={color ?? tokenVar('surface-inset')}
      />
    </svg>
  );
}
