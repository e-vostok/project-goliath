/**
 * ModalConfirmDeleteNation — the DELETE must not fire until the confirm
 * button is explicitly clicked, and must carry { confirm: true }.
 */

import type { ReactElement } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  ModalRoot,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../../vitest.setup';
import { SessionProvider } from '../../hooks/useAuth';
import { ModalConfirmDeleteNation } from '../ModalConfirmDeleteNation';

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
          <SessionProvider session={SESSION}>
            <ModalRoot activeModal="confirm-delete">{ui}</ModalRoot>
          </SessionProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>,
  );
}

describe('ModalConfirmDeleteNation', () => {
  it('does not fire DELETE on mount — only on explicit confirm', async () => {
    let deleteCalls = 0;
    let deleteBody: unknown;
    server.use(
      http.delete('*/api/v1/nations/me', async ({ request }) => {
        deleteCalls += 1;
        deleteBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const onDeleted = vi.fn();
    renderWithProviders(
      <ModalConfirmDeleteNation
        id="confirm-delete"
        nationName="Testia"
        onClose={() => {}}
        onDeleted={onDeleted}
      />,
    );

    // Modal is open — the destructive call must not have happened yet.
    expect(
      await screen.findByText(/cannot be undone/i),
    ).toBeInTheDocument();
    expect(deleteCalls).toBe(0);

    const user = userEvent.setup();
    await user.click(
      screen.getByRole('button', { name: /delete permanently/i }),
    );

    await waitFor(() => expect(deleteCalls).toBe(1));
    expect(deleteBody).toEqual({ confirm: true });
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });
});
