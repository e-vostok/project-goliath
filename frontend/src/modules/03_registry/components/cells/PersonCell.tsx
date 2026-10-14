/**
 * PersonCell — `person` column: round 24px avatar with a neutral round
 * fallback when `avatar_url` is null or fails to load; name truncated
 * with the full name in `title` (Spec 5.5).
 */

import { useState } from 'react';
import { Icon16User } from '@vkontakte/icons';

import { isPersonCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function PersonCell({ value }: { value: RegistryCell }) {
  const [failed, setFailed] = useState(false);
  const person = isPersonCell(value) ? value : null;

  if (!person) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  const showImage = person.avatar_url !== null && !failed;

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
      {showImage ? (
        <img
          src={person.avatar_url ?? ''}
          alt=""
          width={24}
          height={24}
          style={{ borderRadius: '50%', flexShrink: 0 }}
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          aria-hidden
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--vkui--color_background_secondary)',
            border: '1px solid var(--vkui--color_separator_primary)',
          }}
        >
          <Icon16User fill="var(--vkui--color_icon_secondary)" />
        </span>
      )}
      <span
        title={person.name}
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {person.name}
      </span>
    </span>
  );
}
