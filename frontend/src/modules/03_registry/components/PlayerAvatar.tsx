/**
 * PlayerAvatar — the round avatar of a `person` cell (Spec 3.6): the
 * VK photo at `size` px, or a neutral circle with the user icon when
 * `avatar_url` is null, `is_fallback` is set or the image fails to
 * load (version 0.10.0 unit 8b — shared by the person cell, the
 * player «Подсказка» and the «Игрок» subscreen).
 */

import { useState } from 'react';
import {
  Icon16User,
  Icon20User,
  Icon28User,
} from '@vkontakte/icons';

import type { RegistryPersonCell } from '../types';

/** The biggest user glyph that still fits the circle. */
function UserIcon({ size }: { size: number }) {
  const fill = 'var(--vkui--color_icon_secondary)';
  if (size <= 24) {
    return <Icon16User fill={fill} />;
  }
  if (size <= 40) {
    return <Icon20User fill={fill} />;
  }
  return <Icon28User fill={fill} />;
}

export function PlayerAvatar({
  person,
  size,
}: {
  person: RegistryPersonCell;
  /** Circle diameter, px. */
  size: number;
}) {
  // The failed URL, not a boolean — a new url gets a fresh try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = person.avatar_url;
  const showImage = url !== null && !person.is_fallback && failedUrl !== url;

  if (showImage) {
    return (
      <img
        src={url ?? ''}
        alt=""
        width={size}
        height={size}
        style={{ borderRadius: '50%', flexShrink: 0, display: 'block' }}
        onError={() => setFailedUrl(url)}
      />
    );
  }
  return (
    <span
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        flexShrink: 0,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--vkui--color_background_secondary)',
        border: '1px solid var(--vkui--color_separator_primary)',
      }}
    >
      <UserIcon size={size} />
    </span>
  );
}
