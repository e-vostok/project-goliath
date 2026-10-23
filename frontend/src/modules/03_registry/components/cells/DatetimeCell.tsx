/**
 * DatetimeCell — `datetime` column: the game date and time on ONE
 * JetBrains Mono line (PNG 10 — «22.10.2026 14:10», font-size 12).
 * An overdue mark (`mark: "overdue"`) turns the text negative and,
 * when no time came, appends the «по графику сдан» hint.
 */

import { isDatetimeCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function DatetimeCell({ value }: { value: RegistryCell }) {
  const dt = isDatetimeCell(value) ? value : null;
  const overdue = dt?.mark === 'overdue';
  const title = dt?.date
    ? `${dt.date} ${dt.time ?? ''}`.trim()
    : undefined;

  return (
    <span
      data-overdue={overdue || undefined}
      title={title}
      style={{
        display: 'block',
        fontSize: 12,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        color: overdue ? 'var(--vkui--color_text_negative)' : undefined,
      }}
    >
      {dt === null
        ? REGISTRY_TEXTS.emptyValue
        : [dt.date, dt.time ?? (overdue ? REGISTRY_TEXTS.overdueMark : '')]
            .filter((part) => part !== '')
            .join(' ')}
    </span>
  );
}
