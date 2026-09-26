/**
 * PanelCreateNation — field-level error mapping.
 *
 * msw returns real Spec Part 5 ErrorResponse codes; the panel must surface
 * them inline on the correct FormItem (NAME_TAKEN → name field,
 * PROVINCE_COUNT_OUT_OF_RANGE → provinces field), not as a generic banner.
 */

import type { ReactElement } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
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

async function fillAndSubmitForm(name = 'Testia') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Nation name'), name);
  const chipsInput = screen.getByPlaceholderText(
    'Type a province ID and press Enter',
  );
  await user.type(chipsInput, '1{Enter}');
  await user.click(screen.getByRole('button', { name: /found nation/i }));
  return user;
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

describe('PanelCreateNation', () => {
  it('shows NAME_TAKEN inline on the name FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          {
            detail: "Nation name 'Testia' is already taken",
            code: 'NAME_TAKEN',
          },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await fillAndSubmitForm();

    const nameItem = await screen.findByTestId('form-item-name');
    await waitFor(() =>
      expect(
        within(nameItem).getByText(/already taken/i),
      ).toBeInTheDocument(),
    );
    // The error must NOT leak into the generic banner or other fields.
    expect(screen.getByTestId('form-item-provinces')).not.toHaveTextContent(
      /already taken/i,
    );
  });

  it('shows PROVINCE_COUNT_OUT_OF_RANGE inline on the provinces FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          {
            detail:
              'Province count 12 is out of range (must be between 1 and 5)',
            code: 'PROVINCE_COUNT_OUT_OF_RANGE',
          },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await fillAndSubmitForm();

    const provincesItem = await screen.findByTestId('form-item-provinces');
    await waitFor(() =>
      expect(
        within(provincesItem).getByText(/out of range/i),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId('form-item-name')).not.toHaveTextContent(
      /out of range/i,
    );
  });

  it('calls onCreated with the NationDTO on a 201 response', async () => {
    const nation = {
      id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
      name: 'Testia',
      color_hex: '#e64545',
      owner_player_id: SESSION.player.id,
      province_ids: [1],
      created_at: '2026-09-27T00:00:00Z',
    };
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(nation, { status: 201 }),
      ),
    );
    const onCreated = vi.fn();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    await fillAndSubmitForm('Testia');

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(nation));
  });
});
