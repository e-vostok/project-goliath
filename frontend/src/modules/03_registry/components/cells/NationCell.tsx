/**
 * NationCell — `nation` column: the nation's flag image when the cell
 * carries `flag_url`, otherwise the colour dot as before; plus the
 * name, or a dash when the cell is null (Spec 5.5 / 1.2).
 */

import { useState } from 'react';

import { isNationCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function NationCell({ value }: { value: RegistryCell }) {
  // The failed URL, not a flag — a different row landing here after a
  // re-sort must get a fresh try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
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
      {nation.flag_url && failedUrl !== nation.flag_url ? (
        <img
          src={nation.flag_url}
          alt=""
          width={18}
          height={12}
          style={{ borderRadius: 2, flexShrink: 0, display: 'block' }}
          onError={() => setFailedUrl(nation.flag_url)}
        />
      ) : (
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
      )}
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
