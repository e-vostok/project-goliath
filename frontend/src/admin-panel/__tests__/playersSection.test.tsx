/**
 * «Игроки» section (0.11.0 unit 6b): the table renders from
 * GET /admin/players, admins get the grey «Администратора удалить
 * нельзя» instead of the button, the S popup lists only the non-zero
 * consequences of the delete-preview, «Удалить игрока» stays disabled
 * until the VK id is retyped exactly, a success reloads the list and
 * the CANNOT_DELETE_* refusals show their line inside the popup.
 * The last test pins the Mini App cleanup: the old «Админ» block is
 * gone from AppShell and from the tree.
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
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

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

const PLAYERS = {
  items: [
    {
      vk_user_id: 100000001,
      display_name: 'Елена Владимирова',
      nation_short_name: 'Федерация',
      created_at: '2026-10-20 00:00:03',
      is_admin: true,
    },
    {
      vk_user_id: 100000002,
      display_name: 'Мария Волкова',
      nation_short_name: 'Лига',
      created_at: '2026-10-21 00:00:03',
      is_admin: false,
    },
    {
      vk_user_id: 100000004,
      display_name: 'Пётр Малинин',
      nation_short_name: null,
      created_at: '2026-10-23 00:00:03',
      is_admin: false,
    },
  ],
  total: 3,
};

const PREVIEW = {
  vk_user_id: 100000002,
  nation_name: 'Лига',
  provinces_released: 4,
  orders_author: 1,
  orders_judge_undecided: 0,
  orders_judge_decided: 0,
  outbox_rows: 2,
  consent_rows: 1,
  vk_profile_rows: 1,
};

const DELETE_RESULT = { ...PREVIEW };

interface Counters {
  players: number;
  preview: number;
  del: number;
}

function allowSection({
  playersAnswer = PLAYERS,
  deleteAnswer,
}: {
  playersAnswer?: typeof PLAYERS;
  deleteAnswer?: {
    status: number;
    body: { detail: string; code: string };
  };
} = {}): Counters {
  const counters: Counters = { players: 0, preview: 0, del: 0 };
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
    // The default «Ход и мир» section may mount on the way through —
    // answer its calls so a stray render never fails the test.
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/players', () => {
      counters.players += 1;
      return HttpResponse.json(playersAnswer);
    }),
    http.get('*/api/v1/admin/players/*/delete-preview', () => {
      counters.preview += 1;
      return HttpResponse.json(PREVIEW);
    }),
    http.post('*/api/v1/admin/players/*/delete', () => {
      counters.del += 1;
      if (deleteAnswer !== undefined) {
        return HttpResponse.json(deleteAnswer.body, {
          status: deleteAnswer.status,
        });
      }
      return HttpResponse.json(DELETE_RESULT);
    }),
  );
  return counters;
}

function renderPanel() {
  return render(
    <ThemeProvider listenVkScheme={false}>
      <AdminApp />
    </ThemeProvider>,
  );
}

/** Enter through the one-time link, then route to «Игроки». */
async function enterSection() {
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();
  window.location.hash = '#/players';
  await screen.findByTestId('players-table');
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('renders the table from GET /admin/players', async () => {
  allowSection();
  await enterSection();

  const table = screen.getByTestId('players-table');
  expect(table).toHaveTextContent('Елена Владимирова');
  expect(table).toHaveTextContent('VK 100000001');
  expect(table).toHaveTextContent('Федерация');
  expect(table).toHaveTextContent('Государства нет');
  expect(table).toHaveTextContent('20.10.2026');
  expect(table).toHaveTextContent('Администратор');
  expect(screen.getByTestId('players-shown')).toHaveTextContent(
    'Показано 3 из 3',
  );
});

it('admins get «Администратора удалить нельзя» instead of the button', async () => {
  allowSection();
  await enterSection();

  expect(
    screen.queryByTestId('delete-100000001'),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText('Администратора удалить нельзя'),
  ).toBeInTheDocument();
  // Ordinary players keep their «Удалить…».
  expect(screen.getByTestId('delete-100000002')).toBeInTheDocument();
});

it('the popup lists only the non-zero consequences', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('delete-100000002'));
  const popup = await screen.findByTestId('player-delete-popup');
  const list = await screen.findByTestId('player-delete-consequences');

  expect(popup).toHaveTextContent('Удалить игрока «Мария Волкова»?');
  expect(popup).toHaveTextContent(
    'Это нельзя отменить. Вместе с игроком исчезнет:',
  );
  expect(list).toHaveTextContent(
    'государство «Лига», 4 провинций станут свободными',
  );
  expect(list).toHaveTextContent('приказов автора: 1');
  expect(list).toHaveTextContent('сообщений в очереди бота: 2');
  expect(list).toHaveTextContent('согласие на сообщения');
  expect(list).toHaveTextContent('кэш профиля ВК');
  // Zero counts produce no bullet at all.
  expect(list).not.toHaveTextContent('без вердикта');
  expect(list).not.toHaveTextContent('с вердиктом');
});

it('«Удалить игрока» stays disabled until the exact VK id is typed', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('delete-100000002'));
  await screen.findByTestId('player-delete-popup');
  await screen.findByTestId('player-delete-consequences');

  const confirm = screen.getByTestId('confirm-player-delete');
  expect(confirm).toBeDisabled();

  const input = screen.getByLabelText(
    'Для подтверждения введите VK ID: 100000002',
  );
  // A prefix — still not the exact id.
  fireEvent.change(input, { target: { value: '10000000' } });
  expect(confirm).toBeDisabled();
  // A different id — still not it.
  fireEvent.change(input, { target: { value: '100000003' } });
  expect(confirm).toBeDisabled();

  fireEvent.change(input, { target: { value: '100000002' } });
  expect(confirm).toBeEnabled();
});

it('a successful delete closes the popup, notices and reloads', async () => {
  const counters = allowSection();
  await enterSection();
  expect(counters.players).toBe(1);

  fireEvent.click(screen.getByTestId('delete-100000002'));
  await screen.findByTestId('player-delete-popup');
  fireEvent.change(
    screen.getByLabelText('Для подтверждения введите VK ID: 100000002'),
    { target: { value: '100000002' } },
  );
  fireEvent.click(screen.getByTestId('confirm-player-delete'));

  await waitFor(() => expect(counters.del).toBe(1));
  await waitFor(() =>
    expect(
      screen.queryByTestId('player-delete-popup'),
    ).not.toBeInTheDocument(),
  );
  await screen.findByText('Игрок «Мария Волкова» удалён.');
  await waitFor(() => expect(counters.players).toBe(2));
});

it('CANNOT_DELETE_SELF shows its line inside the open popup', async () => {
  allowSection({
    deleteAnswer: {
      status: 409,
      body: { detail: 'self', code: 'CANNOT_DELETE_SELF' },
    },
  });
  await enterSection();

  fireEvent.click(screen.getByTestId('delete-100000002'));
  await screen.findByTestId('player-delete-popup');
  fireEvent.change(
    screen.getByLabelText('Для подтверждения введите VK ID: 100000002'),
    { target: { value: '100000002' } },
  );
  fireEvent.click(screen.getByTestId('confirm-player-delete'));

  const error = await screen.findByTestId('player-delete-error');
  expect(error).toHaveTextContent('Удалить самого себя нельзя.');
  expect(screen.getByTestId('player-delete-popup')).toBeInTheDocument();
});

it('CANNOT_DELETE_ADMIN shows its line inside the open popup', async () => {
  allowSection({
    deleteAnswer: {
      status: 409,
      body: { detail: 'admin', code: 'CANNOT_DELETE_ADMIN' },
    },
  });
  await enterSection();

  fireEvent.click(screen.getByTestId('delete-100000002'));
  await screen.findByTestId('player-delete-popup');
  fireEvent.change(
    screen.getByLabelText('Для подтверждения введите VK ID: 100000002'),
    { target: { value: '100000002' } },
  );
  fireEvent.click(screen.getByTestId('confirm-player-delete'));

  const error = await screen.findByTestId('player-delete-error');
  expect(error).toHaveTextContent('Удалить администратора нельзя.');
  expect(screen.getByTestId('player-delete-popup')).toBeInTheDocument();
});

it('the search box sends the query to /admin/players', async () => {
  const counters = allowSection();
  let seenSearch: string | null = null;
  server.use(
    http.get('*/api/v1/admin/players', ({ request }) => {
      counters.players += 1;
      seenSearch = new URL(request.url).searchParams.get('search');
      return HttpResponse.json(PLAYERS);
    }),
  );
  await enterSection();

  fireEvent.change(screen.getByTestId('players-search'), {
    target: { value: 'Волкова' },
  });
  await waitFor(() => expect(counters.players).toBe(2));
  await waitFor(() => expect(seenSearch).toBe('Волкова'));
});

it('the Mini App no longer carries the old «Админ» block', () => {
  const src = join(__dirname, '..', '..');
  expect(
    existsSync(join(src, 'admin', 'AdminBlock.tsx')),
  ).toBe(false);
  const shell = readFileSync(join(src, 'app', 'AppShell.tsx'), 'utf8');
  expect(shell).not.toContain('AdminBlock');
});
