/**
 * Loading screen (approved board «Loading», UI Spec 7, unit 12b) —
 * the one entry screen while POST /auth/vk resolves: `ground`
 * background, a centred column with the brand mark + wordmark, the
 * shared round spinner and the muted «Загрузка…» line. Works in both
 * themes through tokens only.
 *
 * `AuthErrorScreen` is the same board's error variant — wordmark on
 * top, a centred `surface` card with the shared «Ошибка / reason /
 * Повторить» state.
 */

import type { CSSProperties, ReactNode } from 'react';

import { BrandMark } from './BrandMark';
import { ErrorState } from './ErrorState';
import { LoadingState } from './LoadingState';
import { RADII, TEXT_STYLES, tokenVar } from './tokens';

const column: CSSProperties = {
  boxSizing: 'border-box',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 24,
  padding: 24,
  background: tokenVar('ground'),
};

function Screen({
  children,
  testId,
  minHeight,
}: {
  children: ReactNode;
  testId: string;
  /** '100vh' for the real gate; smaller inside the #ui-kit frame. */
  minHeight?: CSSProperties['minHeight'];
}) {
  return (
    <div
      data-testid={testId}
      style={{ ...column, minHeight: minHeight ?? '100vh' }}
    >
      <BrandMark />
      {children}
    </div>
  );
}

export function LoadingScreen({
  minHeight,
}: {
  minHeight?: CSSProperties['minHeight'];
}) {
  return (
    <Screen testId="loading-screen" minHeight={minHeight}>
      <LoadingState height={48} />
      <div
        style={{
          ...TEXT_STYLES['body'],
          color: tokenVar('ink-muted'),
          marginTop: -8,
        }}
      >
        Загрузка…
      </div>
    </Screen>
  );
}

export function AuthErrorScreen({
  reason,
  onRetry,
  minHeight,
}: {
  /** The auth failure text («Не удалось войти. <reason>»). */
  reason: string;
  onRetry: () => void;
  minHeight?: CSSProperties['minHeight'];
}) {
  return (
    <Screen testId="auth-error-screen" minHeight={minHeight}>
      <div
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: '8px 24px 20px',
          maxWidth: 420,
          textAlign: 'center',
        }}
      >
        <ErrorState
          reason={`Не удалось войти. ${reason}`}
          onRetry={onRetry}
        />
      </div>
    </Screen>
  );
}
