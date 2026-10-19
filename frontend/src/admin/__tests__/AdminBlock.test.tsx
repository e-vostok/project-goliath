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

// The height probe calls VK Bridge; outside VK it would hit a real
// postMessage — stub it (same pattern as 03_registry tests).
vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

import bridge from '@vkontakte/vk-bridge';

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
  next_tick_at_local: '2026-09-30T03:00:00+03:00',
  tick_log: {
    id: 7,
    turn_number: 1,
    started_at: '2026-09-29T12:00:00+00:00',
    finished_at: '2026-09-29T12:00:01+00:00',
    started_at_local: '2026-09-29T15:00:00+03:00',
    finished_at_local: '2026-09-29T15:00:01+03:00',
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

  it('«Скопировать» and «Развернуть» precede the JSON <pre> in DOM order', async () => {
    await renderWithOutput();

    const pre = screen.getByTestId('admin-output');
    for (const name of ['Скопировать', 'Развернуть']) {
      const button = screen.getByRole('button', { name });
      expect(
        button.compareDocumentPosition(pre) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

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

describe('AdminBlock — удаление игрока', () => {
  const PREVIEW = {
    vk_user_id: 123456789,
    nation_name: 'Цель',
    provinces_released: 2,
    orders_author: 1,
    orders_judge_undecided: 1,
    orders_judge_decided: 1,
    outbox_rows: 3,
    consent_rows: 1,
    vk_profile_rows: 1,
  };

  function allowDeleteApi() {
    server.use(
      http.get('*/api/v1/admin/players/*/delete-preview', () =>
        HttpResponse.json(PREVIEW),
      ),
      http.post('*/api/v1/admin/players/*/delete', () =>
        HttpResponse.json(PREVIEW),
      ),
    );
  }

  it('renders the section only for admins, with a disabled destructive button', async () => {
    const user = await renderAsAdmin();

    expect(
      screen.getByText('Удаление игрока'),
    ).toBeInTheDocument();
    const deleteButton = screen.getByRole('button', {
      name: 'Удалить безвозвратно',
    });
    expect(deleteButton).toBeDisabled();

    // Stays disabled while the two ids differ.
    await user.type(screen.getByLabelText('VK ID игрока'), '123456789');
    await user.type(
      screen.getByLabelText('Повторите VK ID для подтверждения'),
      '987654321',
    );
    expect(deleteButton).toBeDisabled();

    // Enabled only when both fields carry the same id.
    await user.clear(
      screen.getByLabelText('Повторите VK ID для подтверждения'),
    );
    await user.type(
      screen.getByLabelText('Повторите VK ID для подтверждения'),
      '123456789',
    );
    expect(deleteButton).toBeEnabled();
  });

  it('«Показать, что будет удалено» renders a plain-Russian preview', async () => {
    allowDeleteApi();
    const user = await renderAsAdmin();

    await user.type(screen.getByLabelText('VK ID игрока'), '123456789');
    await user.click(
      screen.getByRole('button', { name: 'Показать, что будет удалено' }),
    );

    const preview = await screen.findByTestId('player-delete-preview');
    expect(preview).toHaveTextContent(
      'Государство «Цель» будет удалено, 2 провинций станут свободными',
    );
    expect(preview).toHaveTextContent('2 приказов будет удалено');
    expect(preview).toHaveTextContent(
      '1 вернутся в очередь на нового судью',
    );
  });

  it('sends the retyped id, then shows the deletion counts', async () => {
    let deleteBody: unknown;
    server.use(
      http.get('*/api/v1/admin/players/*/delete-preview', () =>
        HttpResponse.json(PREVIEW),
      ),
      http.post('*/api/v1/admin/players/*/delete', async ({ request }) => {
        deleteBody = await request.json();
        return HttpResponse.json(PREVIEW);
      }),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.type(screen.getByLabelText('VK ID игрока'), '123456789');
    await user.type(
      screen.getByLabelText('Повторите VK ID для подтверждения'),
      '123456789',
    );
    await user.click(
      screen.getByRole('button', { name: 'Удалить безвозвратно' }),
    );

    await waitFor(() => expect(deleteBody).toBeDefined());
    expect(deleteBody).toEqual({ confirm_vk_user_id: '123456789' });

    const result = await screen.findByTestId('player-delete-result');
    expect(result).toHaveTextContent('2 провинций станут свободными');
    await waitFor(() => expect(onWorldChanged).toHaveBeenCalledTimes(1));
  });

  it('shows a Russian error for PLAYER_NOT_FOUND and never deletes', async () => {
    let deleteCalls = 0;
    server.use(
      http.get('*/api/v1/admin/players/*/delete-preview', () =>
        HttpResponse.json(
          {
            detail: 'Player vk_user_id=1 does not exist',
            code: 'PLAYER_NOT_FOUND',
          },
          { status: 404 },
        ),
      ),
      http.post('*/api/v1/admin/players/*/delete', () => {
        deleteCalls += 1;
        return HttpResponse.json(PREVIEW);
      }),
    );
    const onWorldChanged = vi.fn();
    const user = await renderAsAdmin(onWorldChanged);

    await user.type(screen.getByLabelText('VK ID игрока'), '1');
    await user.click(
      screen.getByRole('button', { name: 'Показать, что будет удалено' }),
    );

    await screen.findByText('Игрок с таким VK ID не найден.');
    expect(
      screen.queryByTestId('player-delete-preview'),
    ).not.toBeInTheDocument();
    expect(deleteCalls).toBe(0);
    expect(onWorldChanged).not.toHaveBeenCalled();
  });
});

function mockWindowSize(width: number, height: number) {
  for (const [key, value] of [
    ['innerWidth', width],
    ['innerHeight', height],
  ] as const) {
    Object.defineProperty(window, key, {
      configurable: true,
      value,
    });
  }
  return () => {
    mockWindowSize(1024, 768);
  };
}

describe('AdminBlock — окно приложения', () => {
  it('renders the window size as «ширина × высота» for admins', async () => {
    const restore = mockWindowSize(1234, 567);
    try {
      await renderAsAdmin();

      const probe = screen.getByTestId('window-probe');
      expect(probe).toHaveTextContent('1234 × 567');
      expect(probe).toHaveTextContent('Горизонтальная прокрутка: нет');
      expect(
        screen.getByRole('button', { name: 'Обновить' }),
      ).toBeInTheDocument();
    } finally {
      restore();
    }
  });
});

describe('AdminBlock — высота окна', () => {
  const sendMock = vi.mocked(bridge.send);

  beforeEach(() => {
    sendMock.mockClear();
    sendMock.mockResolvedValue({ width: 910, height: 1200 });
  });

  it('«1200» asks VK to resize to 1200 and shows the VK answer', async () => {
    const restore = mockWindowSize(910, 3000);
    try {
      const user = await renderAsAdmin();

      await user.click(screen.getByRole('button', { name: '1200' }));

      expect(sendMock).toHaveBeenCalledWith('VKWebAppResizeWindow', {
        width: 910,
        height: 1200,
      });
      await screen.findByText('Ответ VK: 910 × 1200');
      // 300 ms later the probe re-reads the real window size.
      await screen.findByText('Через 300 мс: 910 × 3000');
    } finally {
      restore();
    }
  });

  it('a rejected resize shows the VK error text and the block stays alive', async () => {
    sendMock.mockRejectedValue({
      error_type: 'client_error',
      error_data: { error_code: 1, error_reason: 'not supported' },
    });
    const user = await renderAsAdmin();

    await user.click(screen.getByRole('button', { name: '4050' }));

    await screen.findByText('Ошибка VK: client_error');
    expect(screen.getByText(/not supported/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '1200' }),
    ).toBeEnabled();
  });

  it('«Автоподстройка высоты» is OFF by default and creates no observer until switched on', async () => {
    const constructed = vi.fn();
    const observed = vi.fn();
    const disconnected = vi.fn();
    class FakeResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        constructed(callback);
      }
      observe = observed;
      unobserve = vi.fn();
      disconnect = disconnected;
    }
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
    try {
      const user = await renderAsAdmin();

      const toggle = screen.getByRole('switch', {
        name: 'Автоподстройка высоты',
      });
      expect(toggle).not.toBeChecked();
      expect(constructed).not.toHaveBeenCalled();
      expect(sendMock).not.toHaveBeenCalled();

      await user.click(toggle);

      expect(constructed).toHaveBeenCalledTimes(1);
      expect(observed).toHaveBeenCalledTimes(1);
      expect(screen.getByText('Вызовов: 0')).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
