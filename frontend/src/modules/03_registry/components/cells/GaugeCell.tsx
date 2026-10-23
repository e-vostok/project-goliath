/**
 * GaugeCell — the `gauge` column (Spec 3.6, the players table's
 * «Рейтинг»): a number on a signed scale (`scale_min`/`scale_max`,
 * −100…+100). PNG 09 renders it as a plain JetBrains Mono figure in
 * `signal-ink` — no bar; the scale still arrives in the DTO and stays
 * the cell's contract (positive values carry «+»).
 */

import type { RegistryCell } from '../../types';
import { FONTS, tokenVar } from '../../../../shared/ui';
import { REGISTRY_TEXTS } from '../../texts';

export function GaugeCell({
  value,
  // The scale still arrives in the DTO — the number needs no
  // normalisation now that PNG 09 dropped the bar.
  scaleMin: _scaleMin,
  scaleMax: _scaleMax,
}: {
  value: RegistryCell;
  scaleMin: number | null;
  scaleMax: number | null;
}) {
  const num = typeof value === 'number' ? value : null;
  return (
    <span
      title={num === null ? undefined : String(num)}
      style={{
        fontFamily: FONTS.mono,
        color: tokenVar('signal-ink'),
      }}
    >
      {num === null
        ? REGISTRY_TEXTS.emptyValue
        : num > 0
          ? `+${num}`
          : `${num}`}
    </span>
  );
}
