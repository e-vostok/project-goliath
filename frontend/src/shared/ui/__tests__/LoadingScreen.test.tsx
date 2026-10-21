/**
 * LoadingScreen / AuthErrorScreen (approved board «Loading», unit
 * 12b): the entry screen shows the brand mark + wordmark, the shared
 * round spinner and «Загрузка…»; the error variant shows the wordmark,
 * a surface card «Ошибка / Не удалось войти. <reason>» and a
 * «Повторить» button that calls its handler.
 */

import type { ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AuthErrorScreen, LoadingScreen } from '../LoadingScreen';
import { ThemeProvider } from '../theme';

function renderScreen(ui: ReactElement) {
  // BrandMark reads the resolved theme — the screens only live under
  // ThemeProvider anyway.
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

describe('LoadingScreen', () => {
  it('shows the wordmark, the round spinner and «Загрузка…»', () => {
    renderScreen(<LoadingScreen />);

    expect(screen.getByTestId('loading-screen')).toBeInTheDocument();
    expect(screen.getByText('PAX ATOMICA')).toBeInTheDocument();
    expect(screen.getByAltText('Логотип PAX ATOMICA'))
      .toBeInTheDocument();
    expect(screen.getByText('Загрузка…')).toBeInTheDocument();
    expect(screen.getByTestId('loading-screen').style.background)
      .toBe('var(--pax-ground)');
  });
});

describe('AuthErrorScreen', () => {
  it('shows «Ошибка / Не удалось войти. <reason>» and calls retry', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    renderScreen(
      <AuthErrorScreen
        reason="Ошибка сети — попробуйте ещё раз."
        onRetry={onRetry}
      />,
    );

    expect(screen.getByTestId('auth-error-screen')).toBeInTheDocument();
    expect(screen.getByText('PAX ATOMICA')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(
      screen.getByText('Не удалось войти. Ошибка сети — попробуйте ещё раз.'),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Повторить' }),
    );
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
