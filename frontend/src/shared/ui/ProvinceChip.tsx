/**
 * Province chip (UI Spec 6, элемент 6 и п. 8): `surface-inset`,
 * `radius-sm`, ONE 24 px line — `inline-flex`, `align-items: center`,
 * `line-height` 16 px, `padding 0 8`, `border-box` — so every chip in
 * a block sits at the same height, star or no star, short name or
 * long. The capital chip carries «★» in `signal-ink` and always goes
 * first — the star is its own fixed-width (14 px) inline-flex element
 * with the same line-height, so the glyph cannot raise the line box.
 * When the capital name differs from its province name the chip shows
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
      ? `${capitalName} (${name})`
      : name;
  return (
    <span
      data-testid="province-chip"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 24,
        lineHeight: '16px',
        padding: '0 8px',
        boxSizing: 'border-box',
        background: tokenVar('surface-inset'),
        borderRadius: RADII['radius-sm'],
        color: capital ? tokenVar('signal-ink') : tokenVar('ink'),
        whiteSpace: 'nowrap',
      }}
    >
      {capital && (
        <span
          aria-hidden="true"
          style={{
            display: 'inline-flex',
            width: 14,
            flexShrink: 0,
            lineHeight: '16px',
          }}
        >
          ★
        </span>
      )}
      {capital ? ` ${label}` : label}
    </span>
  );
}
