/**
 * TextCell — `text` column: truncated with the full value in `title`.
 */

import type { RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function TextCell({ value }: { value: RegistryCell }) {
  const text = typeof value === 'string' ? value : null;
  return (
    <span
      title={text ?? undefined}
      style={{
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {text ?? REGISTRY_TEXTS.emptyValue}
    </span>
  );
}
