/**
 * IndexCell — `index` column: integer, right-aligned (Spec 5.5).
 */

import type { RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function IndexCell({ value }: { value: RegistryCell }) {
  const num = typeof value === 'number' ? value : null;
  return (
    <div
      title={num === null ? undefined : String(num)}
      style={{
        textAlign: 'right',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {num === null ? REGISTRY_TEXTS.emptyValue : num}
    </div>
  );
}
