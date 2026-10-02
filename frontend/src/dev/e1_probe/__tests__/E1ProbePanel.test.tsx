/**
 * E1ProbePanel — rendered through AdminBlock it inherits the «Админ» gate:
 * invisible for non-admins, visible once GET /admin/me allows it.
 * Probe buttons append blocks to the monospace report; «Очистить» resets it.
 */

import type { ReactElement, ReactNode } from 'react';
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

import { server } from '../../../../vitest.setup';
import { SessionProvider } from '../../../modules/00_core/hooks/useAuth';
import { AdminBlock } from '../../../admin/AdminBlock';
import { E1ProbePanel } from '../E1ProbePanel';
import type { BridgeLike } from '../probes';

const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 424242,
    created_at: '2026-09-01T12:00:00Z',
  },
};

function withVkui(ui: ReactElement) {
  return (
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>{ui}</AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>
  );
}

function renderAdminBlock() {
  const ui: ReactNode = <AdminBlock onWorldChanged={() => {}} />;
  return render(
    withVkui(<SessionProvider session={SESSION}>{ui}</SessionProvider>),
  );
}

const stubBridge: BridgeLike = {
  supports: () => true,
  send: async (method: string) =>
    method === 'VKWebAppGetLaunchParams'
      ? { vk_app_id: 777, vk_platform: 'desktop_web', sign: 'SECRET' }
      : { app: 'vk-app', appearance: 'light' },
};

describe('E1ProbePanel — «Админ» visibility gate', () => {
  it('is not rendered for a non-admin', async () => {
    let probed = 0;
    server.use(
      http.get('*/api/v1/admin/me', () => {
        probed += 1;
        return HttpResponse.json(
          { detail: 'Admin privileges required', code: 'ADMIN_REQUIRED' },
          { status: 403 },
        );
      }),
    );

    renderAdminBlock();

    await waitFor(() => expect(probed).toBe(1));
    expect(screen.queryByText('Админ')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Проба большого окна (E1)'),
    ).not.toBeInTheDocument();
  });

  it('is rendered for an admin, with all probe buttons', async () => {
    server.use(
      http.get('*/api/v1/admin/me', () =>
        HttpResponse.json({ is_admin: true }),
      ),
    );

    renderAdminBlock();

    await screen.findByText('Проба большого окна (E1)');
    for (const name of [
      'Среда',
      'Полный экран: этот блок',
      'Полный экран: вся страница',
      'Новая вкладка (наш адрес)',
      'Новая вкладка (адрес приложения во ВК)',
      'Выйти из полного экрана',
      'Скопировать отчёт',
      'Очистить',
      '1400×1200',
    ]) {
      expect(
        screen.getByRole('button', { name }),
      ).toBeInTheDocument();
    }
  });
});

describe('E1ProbePanel — report log', () => {
  it('«Среда» appends a block; the run label lands in the header', async () => {
    const user = userEvent.setup();
    render(withVkui(<E1ProbePanel bridge={stubBridge} />));

    await user.type(
      screen.getByPlaceholderText('например, wide_off'),
      'wide_off',
    );
    await user.click(screen.getByRole('button', { name: 'Среда' }));

    const log = screen.getByTestId('e1-report') as HTMLTextAreaElement;
    expect(log.value).toContain('E1-1');
    expect(log.value).toContain('Метка прогона: wide_off');
    expect(log.value).toContain('"probe": "A"');
    expect(log.value).toContain('"ok": true');
    // whitelist only — the injected secret never reaches the report
    expect(log.value).not.toContain('SECRET');
  });

  it('«Очистить» resets the accumulated blocks', async () => {
    const user = userEvent.setup();
    render(withVkui(<E1ProbePanel bridge={stubBridge} />));

    await user.click(screen.getByRole('button', { name: 'Среда' }));
    const log = screen.getByTestId('e1-report') as HTMLTextAreaElement;
    expect(log.value).toContain('"probe": "A"');

    await user.click(screen.getByRole('button', { name: 'Очистить' }));
    expect(log.value).not.toContain('"probe": "A"');
    expect(log.value).toContain('(проб ещё нет)');
  });
});
