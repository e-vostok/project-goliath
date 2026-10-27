/**
 * Portrait placeholder (UI Spec 6, элемент 8): `surface-inset` with an
 * `ink-faint` silhouette — 72×96 in the leader block (`block`), 120×160
 * at registration (`registration`), a 22×22 circle in a table row
 * (`row`). Silhouette matches the approved 0.12.0 mockups (boards
 * 13б/14б): head circle cx 36 cy 35 r 14, shoulders curve to the base.
 */

import { RADII, tokenVar } from './tokens';

const BLOCK_VARIANTS = {
  block: { width: 72, height: 96 },
  registration: { width: 120, height: 160 },
} as const;

export function PortraitStub({
  variant = 'block',
}: {
  variant?: keyof typeof BLOCK_VARIANTS | 'row';
}) {
  if (variant === 'row') {
    return (
      <svg
        width={22}
        height={22}
        viewBox="0 0 22 22"
        role="img"
        aria-label="Заглушка портрета"
        style={{ flexShrink: 0, display: 'block', borderRadius: '50%' }}
      >
        <circle cx={11} cy={11} r={11} fill={tokenVar('surface-inset')} />
        <circle cx={11} cy={8.5} r={3.6} fill={tokenVar('ink-faint')} />
        <path
          d="M4 22c1-5.6 3.7-7.6 7-7.6s6 2 7 7.6z"
          fill={tokenVar('ink-faint')}
        />
      </svg>
    );
  }
  const { width, height } = BLOCK_VARIANTS[variant];
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 72 96"
      role="img"
      aria-label="Заглушка портрета"
      style={{ flexShrink: 0, display: 'block', borderRadius: RADII['radius-md'] }}
    >
      <rect width={72} height={96} fill={tokenVar('surface-inset')} />
      <circle cx={36} cy={35} r={14} fill={tokenVar('ink-faint')} />
      <path
        d="M10 96c2-24 13-33 26-33s24 9 26 33z"
        fill={tokenVar('ink-faint')}
      />
    </svg>
  );
}
