/**
 * IndexCell — `index` column: integer, right-aligned (Spec 5.5).
 */

import type { RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function IndexCell({ value }: { value: RegistryCell }) {
  return (
    <div style={{ textAlign: 'right' }}>
      {typeof value === 'number' ? value : REGISTRY_TEXTS.emptyValue}
    </div>
  );
}
