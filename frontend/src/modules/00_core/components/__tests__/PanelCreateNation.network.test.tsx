/**
 * PanelCreateNation — raw transport failure.
 *
 * The spec-code cases are covered by PanelCreateNation.test.tsx; this file
 * covers the other failure class: fetch rejects before any HTTP response
 * exists (server unreachable / offline), so no ErrorResponse.code arrives.
 * The panel must fall back to the generic FormStatus banner, not map it to
 * a field or die silently.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { PanelCreateNation } from '../PanelCreateNation';
import {
  fillStep1,
  fillStep2,
  registerDefaultHandlers,
  renderWithProviders,
} from './helpers';

beforeEach(registerDefaultHandlers);

describe('PanelCreateNation — network failure', () => {
  it('shows the generic FormStatus banner when fetch rejects outright', async () => {
    server.use(
      http.post('*/api/v1/nations', () => HttpResponse.error()),
    );
    const onCreated = vi.fn();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    const user = userEvent.setup();
    await fillStep1(user);
    await fillStep2(user);
    await user.click(
      screen.getByRole('button', { name: /основать государство/i }),
    );

    await screen.findByText('Не удалось создать государство');
    expect(screen.getByText(/ошибка сети/i)).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });
});
