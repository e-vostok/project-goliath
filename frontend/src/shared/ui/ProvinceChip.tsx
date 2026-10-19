/**
 * Province chip (UI Spec 6, элемент 6 и п. 8): `surface-inset`,
 * `radius-sm`, padding 2×8. The capital chip carries «★» in
 * `signal-ink` and always goes first — the star needs no caption. When
 * the capital name differs from its province name the chip shows
 * «★ Столица (Провинция)».
 */

import { RADII, tokenVar } from './tokens';

export function ProvinceChip({
  name,
  capital,
  capitalName,
}: {
  name: string;
  capital?: boolean;
  capitalName?: string;
}) {
  const label =
    capital && capitalName && capitalName !== name
      ? `★ ${capitalName} (${name})`
      : capital
        ? `★ ${name}`
        : name;
  return (
    <span
      style={{
        background: tokenVar('surface-inset'),
        borderRadius: RADII['radius-sm'],
        padding: '2px 8px',
        color: capital ? tokenVar('signal-ink') : tokenVar('ink'),
      }}
    >
      {label}
    </span>
  );
}
