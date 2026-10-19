/**
 * Empty state (UI Spec 7): a short phrase in `ink-muted` and, when
 * there is one, an action («Приказов на рассмотрении нет»). Every empty
 * table and list looks the same.
 */

import type { ReactNode } from 'react';

import { TEXT_STYLES, tokenVar } from './tokens';

export function EmptyState({
  text,
  action,
}: {
  text: string;
  action?: ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 8,
        padding: '24px 16px',
        textAlign: 'center',
      }}
    >
      <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink-muted') }}>
        {text}
      </div>
      {action}
    </div>
  );
}
