/**
 * PanelCreateNation — raw transport failure.
 *
 * The spec-code cases are covered by PanelCreateNation.test.tsx; this file
 * covers the other failure class: fetch rejects before any HTTP response
 * exists (server unreachable / offline), so no ErrorResponse.code arrives.
 * The panel must fall back to the generic FormStatus banner, not map it to
 * a field or die silently. The complete form is seeded through the draft —
 * some required fields have no inputs until Issues 13–15.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { PanelCreateNation } from '../PanelCreateNation';
import {
  goToTab,
  registerDefaultHandlers,
  renderWithProviders,
  seedRegistrationDraft,
} from './helpers';

beforeEach(registerDefaultHandlers);

describe('PanelCreateNation — network failure', () => {
  it('shows the generic FormStatus banner when fetch rejects outright', async () => {
    server.use(
      http.put('*/api/v1/applications/me', () => HttpResponse.error()),
    );
    const onSubmitted = vi.fn();
    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);

    const user = userEvent.setup();
    await goToTab(user, 4);
    await user.click(
      screen.getByRole('button', { name: /отправить анкету/i }),
    );

    await screen.findByText('Не удалось отправить анкету');
    expect(screen.getByText(/ошибка сети/i)).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
  });
});
