/**
 * NationCell — `nation` column: colour dot + name, or a dash when the
 * cell is null (Spec 5.5).
 */

import { isNationCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function NationCell({ value }: { value: RegistryCell }) {
  const nation = isNationCell(value) ? value : null;

  if (!nation) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0,
        maxWidth: '100%',
      }}
    >
      <span
        aria-hidden
        style={{
          width: 10,
          height: 10,
          borderRadius: '50%',
          flexShrink: 0,
          background: nation.color,
        }}
      />
      <span
        title={nation.name}
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {nation.name}
      </span>
    </span>
  );
}
