/**
 * AdminBlock — visibility is gated by the GET /admin/me probe and every
 * action goes through the real api-client with msw on the HTTP boundary.
 *
 * Non-admins (403, network failure) must see nothing — no flash, no banner.
 * Mutating actions (tick, reset) report back via onWorldChanged.
 */

import type { ReactElement } from 'react';
import {
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../vitest.setup';
import { SessionProvider } from '../../modules/00_core/hooks/useAuth';
import { AdminBlock } from '../AdminBlock';

const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 424242,
    created_at: '2026-09-01T12:00:00Z',
  },
};

const TICK_RUN_RESULT = {
  ok: true,
  current_turn: 1,
  next_tick_at: '2026-09-30T00:00:00+00:00',
  tick_log: {
    id: 7,
    turn_number: 1,
    started_at: '2026-09-29T12:00:00+00:00',
    finished_at: '2026-09-29T12:00:01+00:00',
    status: 'COMPLETED',
    error_message: null,
  },
};

function renderBlock(onWorldChanged: () => void = () => {}) {
  const ui: ReactElement = <AdminBlock onWorldChanged={onWorldChanged} />;
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

function allowAdmin() {
  server.use(
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true }),
    ),
  );
}

async function renderAsAdmin(onWorldChanged: () => void = () => {}) {
  allowAdmin();
  renderBlock(onWorldChanged);
  // Probe resolved — the block is interactive.
  await screen.findByRole('button', { name: 'Состояние' });
  return userEvent.setup();
}

describe('AdminBlock — visibility', () => {
  it('stays hidden when /admin/me returns 403', async () => {
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

    renderBlock();

    await waitFor(() => expect(probed).toBe(1));
    expect(screen.queryByText('Админ')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Состояние' }),
    ).not.toBeInTheDocument();
  });

  it('stays hidden when /admin/me fails at the network level', async () => {
    let probed = 0;
    server.use(
      http.get('*/api/v1/admin/me', () => {
        probed += 1;
        return HttpResponse.error();
      }),
    );

    renderBlock();

    await waitFor(() => expect(probed).toBe(1));
    expect(screen.queryByText('Админ')).not.toBeInTheDocument();
  });

  it('renders the four action buttons when /admin/me returns 200', async () => {
    allowAdmin();
    renderBlock();

    await screen.findByRole('button', { name: 'Состояние' });
    expect(
      screen.getByRole('button', { name: 'Журнал ходов' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Запустить ход' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Сбросить мир' }),
    ).toBeInTheDocument();
  });
});

describe('AdminBlock — actions', () => {
  it('«Состояние» fetches GET /admin/state and renders pretty JSON', async () => {
    server.use(
      http.get('*/api/v1/admin/state', () =>
        HttpResponse.json({
          modules: { '00_core': { counts: { players: 1, nations: 0 } } },
        }),
      ),
    );
    const user = await renderAsAdmin();

    await user.click(screen.getByRole('button', { name: 'Состояние' }));

    const output = await screen.findByTestId('admin-output');
    expect(output).toHaveTextContent('"modules"');
    expect(output).toHaveTextContent('"00_core"');
    expect(screen.getByText('Результат: Состояние')).toBeInTheDocument();
  });

  it('«Журнал ходов» fetches GET /admin/tick-log and renders JSON', async () => {
    server.use(
      http.get('*/api/v1/admin/tick-log', () =>
        HttpResponse.json([
          {
            id: 3,
            turn_number: 3,
            started_at: '2026-09-28T00:00:00+00:00',
            finished_at: '2026-09-28T00:00:02+00:00',
            status: 'COMPLETED',
            error_message: null,
          },
        ]),
      ),
    );
    const user = await renderAsAdmin();

    await user.click(screen.getByRole('button', { name: 'Журнал ходов' }));

    const output = await screen.findByTestId('admin-output');
    expect(output).toHaveTextContent('"turn_number": 3');
    expect(screen.getByText('Результат: Журнал ходов')).toBeInTheDocument();
  });

  it('«Запустить ход» posts to /admin/tick/run, shows ok:true and fires onWorldChanged', async () => {
    server.use(
      http.post('*/api/v1/admin/tick/run', () =>
        HttpResponse.json(TICK_RUN_RESULT),
      ),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.click(screen.getByRole('button', { name: 'Запустить ход' }));

    const output = await screen.findByTestId('admin-output');
    expect(output).toHaveTextContent('"ok": true');
    await waitFor(() => expect(onWorldChanged).toHaveBeenCalledTimes(1));
  });

  it('«Сбросить мир» sends nothing until «Да, сбросить», and «Отмена» aborts', async () => {
    let resetCalls = 0;
    let resetBody: unknown;
    server.use(
      http.post('*/api/v1/admin/state/reset', async ({ request }) => {
        resetCalls += 1;
        resetBody = await request.json();
        return HttpResponse.json({ reset: ['00_core'] });
      }),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.click(screen.getByRole('button', { name: 'Сбросить мир' }));
    expect(
      screen.getByText(
        /Будут удалены все государства, запланированные действия и журнал ходов/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Игроки сохранятся/)).toBeInTheDocument();
    expect(resetCalls).toBe(0);

    // «Отмена» closes the confirmation without any request.
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(resetCalls).toBe(0);
    expect(
      screen.queryByText(/Будут удалены все государства/),
    ).not.toBeInTheDocument();

    // Re-open and confirm: the request carries { confirm: true }.
    await user.click(screen.getByRole('button', { name: 'Сбросить мир' }));
    await user.click(screen.getByRole('button', { name: 'Да, сбросить' }));

    await waitFor(() => expect(resetCalls).toBe(1));
    expect(resetBody).toEqual({ confirm: true });
    await waitFor(() => expect(onWorldChanged).toHaveBeenCalledTimes(1));
  });

  it('shows RESET_FAILED inline and does not fire onWorldChanged', async () => {
    server.use(
      http.post('*/api/v1/admin/state/reset', () =>
        HttpResponse.json(
          {
            detail: "Reset failed while running module '00_core'",
            code: 'RESET_FAILED',
          },
          { status: 500 },
        ),
      ),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.click(screen.getByRole('button', { name: 'Сбросить мир' }));
    await user.click(screen.getByRole('button', { name: 'Да, сбросить' }));

    await screen.findByText(/Reset failed while running module '00_core'/);
    expect(screen.getByText(/RESET_FAILED/)).toBeInTheDocument();
    expect(onWorldChanged).not.toHaveBeenCalled();
  });

  it('shows the generic network message when tick/run fails outright', async () => {
    server.use(
      http.post('*/api/v1/admin/tick/run', () => HttpResponse.error()),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.click(screen.getByRole('button', { name: 'Запустить ход' }));

    await screen.findByText('Ошибка сети — попробуйте ещё раз.');
    expect(onWorldChanged).not.toHaveBeenCalled();
  });
});

describe('AdminBlock — full-screen JSON overlay', () => {
  const STATE = {
    modules: { '00_core': { counts: { players: 1, nations: 0 } } },
  };

  function allowState() {
    server.use(
      http.get('*/api/v1/admin/state', () => HttpResponse.json(STATE)),
    );
  }

  async function renderWithOutput() {
    allowState();
    const user = await renderAsAdmin();
    await user.click(screen.getByRole('button', { name: 'Состояние' }));
    await screen.findByTestId('admin-output');
    return user;
  }

  it('«Развернуть» opens the overlay with the same JSON; inline stays', async () => {
    const user = await renderWithOutput();

    await user.click(screen.getByRole('button', { name: 'Развернуть' }));

    await screen.findByTestId('admin-output-overlay');
    expect(screen.getByTestId('admin-output-overlay-pre'))
      .toHaveTextContent('"00_core"');
    // The inline output block is untouched under the overlay.
    expect(screen.getByTestId('admin-output'))
      .toHaveTextContent('"00_core"');
  });

  it('«Закрыть» and Esc both close the overlay', async () => {
    const user = await renderWithOutput();

    await user.click(screen.getByRole('button', { name: 'Развернуть' }));
    const overlay = await screen.findByTestId('admin-output-overlay');
    await user.click(
      within(overlay).getByRole('button', { name: 'Закрыть' }),
    );
    expect(
      screen.queryByTestId('admin-output-overlay'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Развернуть' }));
    await screen.findByTestId('admin-output-overlay');
    await user.keyboard('{Escape}');
    expect(
      screen.queryByTestId('admin-output-overlay'),
    ).not.toBeInTheDocument();
  });

  it('«Скопировать» inside the overlay writes the JSON; failure ignored', async () => {
    const user = await renderWithOutput();
    await user.click(screen.getByRole('button', { name: 'Развернуть' }));
    const overlay = await screen.findByTestId('admin-output-overlay');
    const copyButton = within(overlay).getByRole('button', {
      name: 'Скопировать',
    });

    // The write lands in the clipboard (stubbed by userEvent.setup()).
    await user.click(copyButton);
    await waitFor(() =>
      expect(navigator.clipboard.readText()).resolves.toBe(
        JSON.stringify(STATE, null, 2),
      ),
    );

    // A rejected write is swallowed — the overlay stays put.
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValueOnce(
      new Error('denied'),
    );
    await user.click(copyButton);
    expect(screen.getByTestId('admin-output-overlay')).toBeInTheDocument();
  });
});
