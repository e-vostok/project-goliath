/**
 * Portrait placeholder (UI Spec 6, элемент 8): `surface-inset` with an
 * `ink-faint` silhouette — 72×88 in the leader block, a 22×22 circle in
 * a table row. Silhouette matches the approved mockup.
 */

import { RADII, tokenVar } from './tokens';

export function PortraitStub({
  variant = 'block',
}: {
  variant?: 'block' | 'row';
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
  return (
    <svg
      width={72}
      height={88}
      viewBox="0 0 72 88"
      role="img"
      aria-label="Заглушка портрета"
      style={{ flexShrink: 0, display: 'block', borderRadius: RADII['radius-md'] }}
    >
      <rect width={72} height={88} fill={tokenVar('surface-inset')} />
      <circle cx={36} cy={32} r={13} fill={tokenVar('ink-faint')} />
      <path
        d="M12 88c2-22 12-30 24-30s22 8 24 30z"
        fill={tokenVar('ink-faint')}
      />
    </svg>
  );
}
