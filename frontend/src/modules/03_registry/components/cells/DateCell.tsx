/**
 * DateCell — `date` column: shows the ready `text` from the server
 * (Spec 3.5/5.5 — the client never computes dates).
 */

import { isDateCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function DateCell({ value }: { value: RegistryCell }) {
  const date = isDateCell(value) ? value : null;
  return (
    <span
      title={date?.text}
      style={{
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {date ? date.text : REGISTRY_TEXTS.emptyValue}
    </span>
  );
}
