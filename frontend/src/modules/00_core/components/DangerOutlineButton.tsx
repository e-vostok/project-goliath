/**
 * DangerOutlineButton — the danger-outline button of mockups 20/21
 * («.btn do» / «.btn do sm» of version 0.13.0): transparent body,
 * `danger` border and text. Shared by the admin window's action
 * buttons («Вернуть с причиной», «Удалить флаг/портрет») and the
 * player's «Отменить анкету» on the PENDING plate (13a).
 */

import type { ReactNode } from 'react';

import { RADII, SIZES, TEXT_STYLES, tokenVar } from '../../../shared/ui';

export function DangerOutlineButton({
  small = false,
  disabled = false,
  onClick,
  testId,
  children,
}: {
  small?: boolean;
  disabled?: boolean;
  onClick: () => void;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      style={{
        height: small ? SIZES['button-h-small'] : SIZES['button-h'],
        padding: small ? '0 12px' : '0 16px',
        boxSizing: 'border-box',
        borderRadius: RADII['radius-md'],
        border: `1px solid ${tokenVar('danger')}`,
        background: 'transparent',
        color: tokenVar('danger'),
        ...TEXT_STYLES['body'],
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  );
}
