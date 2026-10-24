/**
 * GaugeCell — the `gauge` column (Spec 3.6, the players table's
 * «Рейтинг»): a number on a signed scale (`scale_min`/`scale_max`,
 * −100…+100). PNG 09 renders it as a plain JetBrains Mono figure in
 * `signal-ink` — no bar (positive values carry «+»). Since unit 13b
 * the scale shows in the cell's `title`: «<число> · шкала −100…+100»
 * (the numbers come from the column's DTO; a null scale leaves the
 * plain number).
 */

import type { RegistryCell } from '../../types';
import { FONTS, tokenVar } from '../../../../shared/ui';
import { REGISTRY_TEXTS } from '../../texts';

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
  return (
    <span
      title={
        num === null
          ? undefined
          : scaleMin !== null && scaleMax !== null
            ? REGISTRY_TEXTS.gaugeScaleTitle(num, scaleMin, scaleMax)
            : String(num)
      }
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
