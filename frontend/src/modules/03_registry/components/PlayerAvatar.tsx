/**
 * PlayerAvatar — the round avatar of a `person` cell (Spec 3.6): the
 * VK photo at `size` px, or the neutral silhouette when `avatar_url`
 * is null, `is_fallback` is set or the image fails to load (version
 * 0.10.0 unit 8b — shared by the person cell, the player «Подсказка»
 * and the «Игрок» subscreen; the silhouette is the approved mockup's —
 * `surface-inset` circle, `ink-faint` head and shoulders).
 */

import { useState } from 'react';

import { tokenVar } from '../../../shared/ui';
import type { RegistryPersonCell } from '../types';

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
    // Decorative — the name sits right next to it in every context
    // (a labelled svg would leak into the cell button's name).
    <svg
      width={size}
      height={size}
      viewBox="0 0 22 22"
      aria-hidden="true"
      style={{ borderRadius: '50%', flexShrink: 0, display: 'block' }}
    >
      <circle cx={11} cy={11} r={11} fill={tokenVar('surface-inset')} />
      <circle cx={11} cy={9} r={4} fill={tokenVar('ink-faint')} />
      <path
        d="M3 22c1-6 5-8 8-8s7 2 8 8z"
        fill={tokenVar('ink-faint')}
      />
    </svg>
  );
}
