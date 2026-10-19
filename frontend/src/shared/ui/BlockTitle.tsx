/**
 * Block title (UI Spec 5.3 / 6, элемент 2): block icon in `signal-ink`,
 * `title-uppercase` text and a thin `line` filling the rest of the row.
 * `trailing` sits after the line (mockup: the «Подать приказ» button).
 */

import type { ReactNode } from 'react';

import { BlockIcon } from './icons';
import type { BlockIconName } from './icons';
import { TEXT_STYLES, tokenVar } from './tokens';

export function BlockTitle({
  icon,
  title,
  trailing,
}: {
  icon: BlockIconName;
  title: string;
  trailing?: ReactNode;
}) {
  return (
    <h2
      style={{
        margin: '0 0 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        ...TEXT_STYLES['title-uppercase'],
        color: tokenVar('ink'),
      }}
    >
      <BlockIcon name={icon} />
      {title}
      <span
        style={{
          flexGrow: 1,
          height: 1,
          background: tokenVar('line'),
          marginLeft: 4,
        }}
      />
      {trailing}
    </h2>
  );
}
