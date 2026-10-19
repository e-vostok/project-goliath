/**
 * Error state (UI Spec 7): the single component for network and server
 * errors — the word «Ошибка» in `danger`, the reason in Russian, the
 * «Повторить» button. NETWORK_ERROR_TEXT is the default phrase; copying
 * it into other files is forbidden.
 */

import { RADII, SIZES, TEXT_STYLES, tokenVar } from './tokens';

export const NETWORK_ERROR_TEXT = 'Ошибка сети — попробуйте ещё раз.';

export function ErrorState({
  reason = NETWORK_ERROR_TEXT,
  onRetry,
}: {
  reason?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 8,
        padding: '24px 16px',
        textAlign: 'center',
      }}
    >
      <div style={{ ...TEXT_STYLES['heading'], color: tokenVar('danger') }}>
        Ошибка
      </div>
      <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink-muted') }}>
        {reason}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          style={{
            marginTop: 4,
            height: SIZES['button-h'],
            boxSizing: 'border-box',
            padding: '0 16px',
            border: 'none',
            borderRadius: RADII['radius-md'],
            background: tokenVar('surface-inset'),
            color: tokenVar('ink'),
            ...TEXT_STYLES['body'],
            cursor: 'pointer',
          }}
        >
          Повторить
        </button>
      )}
    </div>
  );
}
