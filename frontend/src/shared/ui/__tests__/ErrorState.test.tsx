/**
 * ErrorState (UI Spec 7): shows the word «Ошибка», the reason and the
 * «Повторить» button, which calls the retry handler.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ErrorState, NETWORK_ERROR_TEXT } from '../ErrorState';

describe('ErrorState', () => {
  it('shows «Ошибка» with the reason and calls the retry handler', async () => {
    const onRetry = vi.fn();
    render(<ErrorState reason={NETWORK_ERROR_TEXT} onRetry={onRetry} />);

    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText(NETWORK_ERROR_TEXT)).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole('button', { name: 'Повторить' }),
    );
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
