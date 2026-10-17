/**
 * FlagCell — `flag` column: colour square, or the uploaded image when
 * `image_url` is present (Spec 5.5; stub shows the nation colour).
 */

import { useState } from 'react';

import { isFlagCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function FlagCell({ value }: { value: RegistryCell }) {
  const [failed, setFailed] = useState(false);
  const flag = isFlagCell(value) ? value : null;

  if (!flag) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  if (flag.image_url && !failed) {
    return (
      <img
        src={flag.image_url}
        alt=""
        width={24}
        height={24}
        style={{ borderRadius: 4, display: 'block' }}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 24,
        height: 24,
        borderRadius: 4,
        background: flag.color,
        border: '1px solid var(--vkui--color_separator_primary)',
      }}
    />
  );
}
