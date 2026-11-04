/**
 * GaugeCell — the `gauge` column (Spec 3.6, the players table's
 * «Рейтинг»; mockups 26/26б, unit 11b): the signed number
 * (JetBrains Mono, right-aligned, min-width 34 px) and the 72 px
 * RatingScale after an 8 px gap. A null cell is «—»; a column
 * without `scale_min`/`scale_max` keeps the bare signed figure.
 */

import type { RegistryCell } from '../../types';
import { FONTS, tokenVar } from '../../../../shared/ui';
import { REGISTRY_TEXTS } from '../../texts';
import { RatingScale } from '../RatingScale';

export function GaugeCell({
  value,
  scaleMin,
  scaleMax,
}: {
  value: RegistryCell;
  scaleMin: number | null;
  scaleMax: number | null;
}) {
  const num = typeof value === 'number' ? value : null;
  if (num === null) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }
  if (scaleMin === null || scaleMax === null) {
    return (
      <span title={String(num)} style={{ fontFamily: FONTS.mono }}>
        {REGISTRY_TEXTS.ratingNumber(num)}
      </span>
    );
  }
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span
        style={{
          fontFamily: FONTS.mono,
          fontSize: 13,
          lineHeight: '16px',
          minWidth: 34,
          textAlign: 'right',
          color: tokenVar('ink'),
          flexShrink: 0,
        }}
      >
        {REGISTRY_TEXTS.ratingNumber(num)}
      </span>
      <RatingScale value={num} min={scaleMin} max={scaleMax} />
    </span>
  );
}
