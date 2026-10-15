/**
 * DatetimeCell — `datetime` column: two lines, date over time (Spec
 * 1.2 / 04_orders Appendix A). With `mark` set the cell gets the
 * overdue style (negative colour); an empty cell carrying the mark
 * shows the mark text on the second line instead of a bare dash.
 */

import { isDatetimeCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function DatetimeCell({ value }: { value: RegistryCell }) {
  const dt = isDatetimeCell(value) ? value : null;
  const overdue = dt?.mark === 'overdue';
  const overdueStyle = overdue
    ? { color: 'var(--vkui--color_text_negative)' }
    : undefined;
  const title = dt?.date
    ? `${dt.date} ${dt.time ?? ''}`.trim()
    : undefined;

  return (
    <div
      data-overdue={overdue || undefined}
      title={title}
      style={{
        lineHeight: '15px',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          ...overdueStyle,
        }}
      >
        {dt?.date ?? REGISTRY_TEXTS.emptyValue}
      </div>
      <div
        style={{
          fontSize: 11,
          ...(overdueStyle ?? {
            color: 'var(--vkui--color_text_secondary)',
          }),
        }}
      >
        {dt?.time ?? (overdue ? REGISTRY_TEXTS.overdueMark : '')}
      </div>
    </div>
  );
}
