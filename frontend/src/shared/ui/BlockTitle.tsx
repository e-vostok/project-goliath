/**
 * Block title (UI Spec 5.3 / 6, элемент 2): block icon in `signal-ink`,
 * `title-uppercase` text and a thin `line` filling the rest of the row.
 * `trailing` sits after the line (mockup: the «Подать приказ» button).
 * `line={false}` drops the filling line — for screen titles whose row
 * already carries content (mockup «Registry»: the table tabs sit right
 * after the title).
 */

import type { ReactNode } from 'react';

import { BlockIcon } from './icons';
import type { BlockIconName } from './icons';
import { TEXT_STYLES, tokenVar } from './tokens';

export function BlockTitle({
  icon,
  title,
  trailing,
  line = true,
}: {
  icon: BlockIconName;
  title: string;
  trailing?: ReactNode;
  line?: boolean;
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
      {line && (
        <span
          data-testid="block-title-line"
          style={{
            flexGrow: 1,
            height: 1,
            background: tokenVar('line'),
            marginLeft: 4,
          }}
        />
      )}
      {trailing}
    </h2>
  );
}
