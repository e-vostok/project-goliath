/**
 * «Администраторы» and «Журнал» sections (0.11.0 unit 7).
 *
 * Администраторы: the table renders both right-sources with the right
 * action cell («Снять права…» for revocable rows, the grey «Снять
 * нельзя» for env admins and the caller's own row); «Выдать права…»
 * stays disabled until a player is chosen from the suggestions; each
 * server refusal (LAST_ADMIN, ROOT_ADMIN_PROTECTED, CANNOT_REVOKE_SELF)
 * keeps the popup open with its own Russian line.
 *
 * Журнал: the table renders the backend labels, the filters send
 * their query values to /admin/audit-log and «Показать ещё» walks the
 * next_before_id cursor.
 *
 * msw stands at the HTTP boundary — the real api-client does the
 * requests.
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { ThemeProvider } from '../../shared/ui/theme';
import { AdminApp } from '../AdminApp';
import { clearSession } from '../session';

const LINK_TOKEN = 'one-time-link-abc123';

const CLOCK_DTO = {
  current_turn: 1,
  game_date: '2040-01-01',
  game_date_text: 'январь 2040',
  next_tick_at: '25.10.2026 00:00:00',
};

const ADMINS = [
  {
    vk_user_id: 100000001,
    display_name: 'Алексей Морозов',
    source: 'env' as const,
    granted_by_vk_user_id: null,
    granted_by_name: null,
    granted_at: null,
    is_self: true,
  },
  {
    vk_user_id: 100000003,
    display_name: 'Дмитрий Соколов',
    source: 'grant' as const,
    granted_by_vk_user_id: 100000001,
    granted_by_name: 'Алексей Морозов',
    granted_at: '2026-10-24 15:40:12',
    is_self: false,
  },
];

const SUGGESTIONS = {
  items: [
    {
      vk_user_id: 100000009,
      display_name: 'Ольга Ветрова',
      nation_short_name: 'Лига',
      created_at: '2026-10-20 00:00:03',
      is_admin: false,
    },
  ],
  total: 1,
};

const AUDIT_PAGE_1 = {
  items: [
    {
      id: 12,
      created_at: '2026-10-24 15:44:12',
      actor_vk_user_id: 100000001,
      actor_name: 'Алексей Морозов',
      action: 'admin.grant',
      action_label: 'Выдача прав',
      target_type: 'player',
      target_id: '100000003',
      summary: 'Выданы права администратора игроку Дмитрий Соколов.',
    },
    {
      id: 11,
      created_at: '2026-10-24 15:21:03',
      actor_vk_user_id: 100000001,
      actor_name: 'Алексей Морозов',
      action: 'world.reset',
      action_label: 'Сброс мира',
      target_type: null,
      target_id: null,
      summary: 'Выполнен сброс состояния мира.',
    },
  ],
  next_before_id: 11,
};

const AUDIT_PAGE_2 = {
  items: [
    {
      id: 10,
      created_at: '2026-10-24 15:12:40',
      actor_vk_user_id: 999000111,
      actor_name: null,
      action: 'tick.run',
      action_label: 'Запуск хода',
      target_type: 'tick',
      target_id: null,
      summary: 'Запущен ход вручную: мир на ходе 1.',
    },
  ],
  next_before_id: null,
};

const AUDIT_FILTERS = {
  actors: [
    { vk_user_id: 100000001, display_name: 'Алексей Морозов' },
    { vk_user_id: 999000111, display_name: null },
  ],
  actions: [
    { action: 'admin.grant', action_label: 'Выдача прав' },
    { action: 'world.reset', action_label: 'Сброс мира' },
    { action: 'tick.run', action_label: 'Запуск хода' },
  ],
};

interface AdminsCounters {
  admins: number;
  players: number;
  grant: number;
  revoke: number;
}

function allowAdminsSection({
  grantAnswer,
  revokeAnswer,
}: {
  grantAnswer?: { status: number; body: { detail: string; code: string } };
  revokeAnswer?: { status: number; body: { detail: string; code: string } };
} = {}): AdminsCounters {
  const counters: AdminsCounters = {
    admins: 0,
    players: 0,
    grant: 0,
    revoke: 0,
  };
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: 3600,
      }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    // The default «Ход и мир» section may mount on the way through.
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/admins', () => {
      counters.admins += 1;
      return HttpResponse.json(ADMINS);
    }),
    http.get('*/api/v1/admin/players', () => {
      counters.players += 1;
      return HttpResponse.json(SUGGESTIONS);
    }),
    http.post('*/api/v1/admin/admins', () => {
      counters.grant += 1;
      if (grantAnswer !== undefined) {
        return HttpResponse.json(grantAnswer.body, {
          status: grantAnswer.status,
        });
      }
      return HttpResponse.json({ granted: 100000009 });
    }),
    http.post('*/api/v1/admin/admins/*/revoke', () => {
      counters.revoke += 1;
      if (revokeAnswer !== undefined) {
        return HttpResponse.json(revokeAnswer.body, {
          status: revokeAnswer.status,
        });
      }
      return HttpResponse.json({ revoked: 100000003 });
    }),
  );
  return counters;
}

function allowLogSection() {
  const queries: string[] = [];
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: 3600,
      }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/audit-log/filters', () =>
      HttpResponse.json(AUDIT_FILTERS),
    ),
    http.get('*/api/v1/admin/audit-log', ({ request }) => {
      const url = new URL(request.url);
      queries.push(url.search);
      if (url.searchParams.get('before_id') === '11') {
        return HttpResponse.json(AUDIT_PAGE_2);
      }
      return HttpResponse.json(AUDIT_PAGE_1);
    }),
  );
  return queries;
}

function renderPanel() {
  return render(
    <ThemeProvider listenVkScheme={false}>
      <AdminApp />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

describe('«Администраторы» section', () => {
  async function enterSection() {
    window.location.hash = `#t=${LINK_TOKEN}`;
    const view = renderPanel();
    window.location.hash = '#/admins';
    await screen.findByTestId('admins-table');
    return view.unmount;
  }

  it('renders both right-sources with the right action cell per row', async () => {
    allowAdminsSection();
    await enterSection();

    const table = screen.getByTestId('admins-table');
    expect(table).toHaveTextContent('Алексей Морозов');
    expect(table).toHaveTextContent('VK 100000001');
    expect(table).toHaveTextContent('Из настроек сервера');
    expect(table).toHaveTextContent('Дмитрий Соколов');
    expect(table).toHaveTextContent('Выдано через панель');
    expect(table).toHaveTextContent('24.10.2026 15:40');
    // The env row is also the caller's own row — no revoke button.
    expect(screen.queryByTestId('revoke-100000001')).not.toBeInTheDocument();
    expect(screen.getByTestId('revoke-100000003')).toBeInTheDocument();
    expect(
      screen.getAllByText('Снять нельзя').length,
    ).toBeGreaterThanOrEqual(1);
  });

  it('«Выдать права…» stays disabled until a suggestion is picked', async () => {
    const counters = allowAdminsSection();
    await enterSection();

    const open = screen.getByTestId('open-grant');
    expect(open).toBeDisabled();

    fireEvent.change(screen.getByTestId('admins-grant-search'), {
      target: { value: 'Ольга' },
    });
    const suggestion = await screen.findByTestId('suggest-100000009');
    expect(counters.players).toBeGreaterThanOrEqual(1);

    fireEvent.mouseDown(suggestion);
    expect(open).toBeEnabled();

    fireEvent.click(open);
    const popup = await screen.findByTestId('grant-popup');
    expect(popup).toHaveTextContent(
      'Выдать права администратора игроку «Ольга Ветрова»?',
    );
    expect(popup).toHaveTextContent(
      'Администратор может всё в этой панели',
    );

    fireEvent.click(screen.getByTestId('confirm-grant'));
    await waitFor(() => expect(counters.grant).toBe(1));
    await waitFor(() =>
      expect(screen.queryByTestId('grant-popup')).not.toBeInTheDocument(),
    );
    await screen.findByText(
      'Игроку «Ольга Ветрова» выданы права администратора.',
    );
  });

  it('a revoke refusal shows its own line inside the open popup', async () => {
    for (const [code, text] of [
      ['LAST_ADMIN', 'Нельзя снять последнего администратора'],
      [
        'ROOT_ADMIN_PROTECTED',
        'Этого администратора можно убрать только в настройках сервера',
      ],
      ['CANNOT_REVOKE_SELF', 'Нельзя снять права у самого себя'],
    ] as const) {
      allowAdminsSection({
        revokeAnswer: { status: 409, body: { detail: code, code } },
      });
      const unmount = await enterSection();

      fireEvent.click(screen.getByTestId('revoke-100000003'));
      const popup = await screen.findByTestId('revoke-popup');
      expect(popup).toHaveTextContent(
        'Снять права администратора у игрока «Дмитрий Соколов»?',
      );

      fireEvent.click(screen.getByTestId('confirm-revoke'));
      const error = await screen.findByTestId('admins-popup-error');
      expect(error).toHaveTextContent(text);
      expect(screen.getByTestId('revoke-popup')).toBeInTheDocument();

      // Unmount before the next code — a fresh panel for each refusal.
      unmount();
    }
  });
});

describe('«Журнал» section', () => {
  async function enterSection() {
    window.location.hash = `#t=${LINK_TOKEN}`;
    renderPanel();
    window.location.hash = '#/log';
    await screen.findByTestId('log-table');
  }

  it('renders the backend labels and the «Над чем» words', async () => {
    allowLogSection();
    await enterSection();

    const table = screen.getByTestId('log-table');
    expect(table).toHaveTextContent('24.10 15:44');
    expect(table).toHaveTextContent('Алексей Морозов');
    expect(table).toHaveTextContent('Выдача прав');
    expect(table).toHaveTextContent('Игрок 100000003');
    expect(table).toHaveTextContent('Сброс мира');
    // No target → the dash, not an empty cell.
    expect(table).toHaveTextContent('—');
    expect(screen.getByTestId('log-shown')).toHaveTextContent(
      'Показано 2 · записи не удаляются и не правятся',
    );
  });

  it('the filters send their query values to /admin/audit-log', async () => {
    const queries = allowLogSection();
    await enterSection();
    expect(queries.length).toBe(1);

    fireEvent.change(screen.getByTestId('log-filter-actor'), {
      target: { value: '100000001' },
    });
    await waitFor(() =>
      expect(
        queries.some((q) => q.includes('actor_vk_user_id=100000001')),
      ).toBe(true),
    );

    fireEvent.change(screen.getByTestId('log-filter-action'), {
      target: { value: 'admin.grant' },
    });
    await waitFor(() =>
      expect(
        queries.some(
          (q) =>
            q.includes('actor_vk_user_id=100000001') &&
            q.includes('action=admin.grant'),
        ),
      ).toBe(true),
    );

    fireEvent.change(screen.getByTestId('log-filter-from'), {
      target: { value: '2026-10-20' },
    });
    await waitFor(() =>
      expect(
        queries.some((q) => q.includes('date_from=2026-10-20')),
      ).toBe(true),
    );

    fireEvent.change(screen.getByTestId('log-filter-to'), {
      target: { value: '2026-10-24' },
    });
    await waitFor(() =>
      expect(
        queries.some((q) => q.includes('date_to=2026-10-24')),
      ).toBe(true),
    );

    // «Сбросить» sends a bare query again.
    fireEvent.click(screen.getByTestId('log-reset'));
    await waitFor(() =>
      expect(
        queries.some(
          (q) =>
            !q.includes('actor_vk_user_id') &&
            !q.includes('action=') &&
            !q.includes('date_from') &&
            !q.includes('date_to'),
        ),
      ).toBe(true),
    );
  });

  it('«Показать ещё» walks the next_before_id cursor', async () => {
    const queries = allowLogSection();
    await enterSection();

    fireEvent.click(screen.getByTestId('log-show-more'));
    await waitFor(() =>
      expect(queries.some((q) => q.includes('before_id=11'))).toBe(true),
    );

    // The second page appends; with next_before_id null the button hides.
    await waitFor(() =>
      expect(screen.getByTestId('log-shown')).toHaveTextContent(
        'Показано 3',
      ),
    );
    expect(screen.getByTestId('log-table')).toHaveTextContent(
      'VK 999000111',
    );
    expect(screen.queryByTestId('log-show-more')).not.toBeInTheDocument();
  });
});
