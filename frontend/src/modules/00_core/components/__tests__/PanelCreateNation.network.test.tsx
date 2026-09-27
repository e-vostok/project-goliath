/**
 * PanelCreateNation — raw transport failure.
 *
 * The spec-code cases are covered by PanelCreateNation.test.tsx; this file
 * covers the other failure class: fetch rejects before any HTTP response
 * exists (server unreachable / offline), so no ErrorResponse.code arrives.
 * The panel must fall back to the generic FormStatus banner, not map it to
 * a field or die silently.
 */

import type { ReactElement } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../../vitest.setup';
import { SessionProvider } from '../../hooks/useAuth';
import { PanelCreateNation } from '../PanelCreateNation';

const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 123456,
    created_at: '2026-09-01T12:00:00Z',
  },
};

function renderWithProviders(ui: ReactElement) {
  return render(
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <SessionProvider session={SESSION}>{ui}</SessionProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get('*/api/v1/provinces', () =>
      HttpResponse.json([
        { id: 1, nation_id: null },
        { id: 2, nation_id: null },
      ]),
    ),
  );
});

describe('PanelCreateNation — network failure', () => {
  it('shows the generic FormStatus banner when fetch rejects outright', async () => {
    server.use(
      http.post('*/api/v1/nations', () => HttpResponse.error()),
    );
    const onCreated = vi.fn();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Nation name'), 'Testia');
    const chipsInput = screen.getByPlaceholderText(
      'Type a province ID and press Enter',
    );
    await user.type(chipsInput, '1{Enter}');
    await user.click(screen.getByRole('button', { name: /found nation/i }));

    await screen.findByText('Could not create nation');
    expect(screen.getByText(/network error/i)).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });
});
