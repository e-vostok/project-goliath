/**
 * «Ход и мир» section (0.11.0 unit 6a): the overview tiles render
 * from GET /admin/overview, the tick popup confirms through
 * POST /admin/tick/run and refreshes, the world reset stays disabled
 * until the server allows it AND «СБРОС» is retyped, the tick journal
 * shows ✓/✕. msw stands at the HTTP boundary — the real api-client
 * does the requests.
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
const SESSION_KEY = 'pax.admin.panel.session';

const CLOCK_DTO = {
  current_turn: 1,
  game_date: '2040-01-01',
  game_date_text: 'январь 2040',
  next_tick_at: '25.10.2026 00:00:00',
};

const TILES = [
  { key: 'turn', label: 'Ход', value: '1 · январь 2040', sort: 10 },
  { key: 'players', label: 'Игроки', value: '4', sort: 40 },
  {
    key: 'orders-no-verdict',
    label: 'Приказы без вердикта',
    value: '3',
    sort: 70,
  },
];

const LOG_ROWS = [
  {
    id: 3,
    turn_number: 2,
    turn_label: '2 · март 2040',
    started_at: '2026-10-25 00:00:00',
    finished_at: '2026-10-25 00:00:02',
    status: 'COMPLETED',
    error_message: null,
  },
  {
    id: 2,
    turn_number: 2,
    turn_label: '2 · март 2040',
    started_at: '2026-10-24 00:00:00',
    finished_at: '2026-10-24 00:00:01',
    status: 'FAILED',
    error_message: 'сбой расчёта, откат',
  },
];

function renderPanel() {
  return render(
    <ThemeProvider listenVkScheme={false}>
      <AdminApp />
    </ThemeProvider>,
  );
}

interface Counters {
  tick: number;
  reset: number;
  overview: number;
  log: number;
}

function allowSection(
  { resetAllowed = false }: { resetAllowed?: boolean } = {},
): Counters {
  const counters: Counters = { tick: 0, reset: 0, overview: 0, log: 0 };
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: 3600,
      }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: resetAllowed }),
    ),
    http.get('*/api/v1/admin/overview', () => {
      counters.overview += 1;
      return HttpResponse.json(TILES);
    }),
    http.get('*/api/v1/admin/tick-log', () => {
      counters.log += 1;
      return HttpResponse.json(LOG_ROWS);
    }),
    http.post('*/api/v1/admin/tick/run', () => {
      counters.tick += 1;
      return HttpResponse.json({
        ok: true,
        current_turn: 2,
        next_tick_at: '2026-10-26 00:00:00',
        tick_log: LOG_ROWS[0],
      });
    }),
    http.post('*/api/v1/admin/state/reset', () => {
      counters.reset += 1;
      return HttpResponse.json({ reset: ['00_core'] });
    }),
  );
  return counters;
}

async function enterSection() {
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();
  // The section's first paint: the tiles are in.
  return screen.findByTestId('tile-turn');
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('renders the world-state tiles from GET /admin/overview', async () => {
  allowSection();
  await enterSection();

  expect(screen.getByTestId('tile-turn')).toHaveTextContent(
    '1 · январь 2040',
  );
  const players = screen.getByTestId('tile-players');
  expect(players).toHaveTextContent('Игроки');
  expect(players).toHaveTextContent('4');
  expect(
    screen.getByTestId('tile-orders-no-verdict'),
  ).toHaveTextContent('3');
  // The «Обновлено …» caption and the «Обновить» button are there.
  expect(screen.getByText(/Обновлено/)).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Обновить' }),
  ).toBeInTheDocument();
});

it('the tick popup confirm calls /tick/run once and refreshes tiles + log', async () => {
  const counters = allowSection();
  await enterSection();
  expect(counters.overview).toBe(1);
  expect(counters.log).toBe(1);

  fireEvent.click(screen.getByTestId('run-tick'));
  await screen.findByTestId('tick-popup');

  fireEvent.click(screen.getByTestId('confirm-tick'));

  await waitFor(() => expect(counters.tick).toBe(1));
  await waitFor(() =>
    expect(screen.queryByTestId('tick-popup')).not.toBeInTheDocument(),
  );
  // Success → shared Notice + a fresh overview and journal pull.
  await screen.findByText(/Ход 2 выполнен успешно/);
  await waitFor(() => expect(counters.overview).toBe(2));
  expect(counters.log).toBe(2);
});

it('cancel inside the tick popup calls nothing', async () => {
  const counters = allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('run-tick'));
  await screen.findByTestId('tick-popup');
  fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));

  await waitFor(() =>
    expect(screen.queryByTestId('tick-popup')).not.toBeInTheDocument(),
  );
  expect(counters.tick).toBe(0);
  // No refresh either — cancel is a pure close.
  expect(counters.overview).toBe(1);
});

it('a failed tick shows the server error text in the card', async () => {
  const counters = allowSection();
  await enterSection();
  server.use(
    http.post('*/api/v1/admin/tick/run', () => {
      counters.tick += 1;
      return HttpResponse.json({
        ok: false,
        current_turn: 1,
        next_tick_at: '2026-10-26 00:00:00',
        tick_log: LOG_ROWS[1],
      });
    }),
  );

  fireEvent.click(screen.getByTestId('run-tick'));
  await screen.findByTestId('tick-popup');
  fireEvent.click(screen.getByTestId('confirm-tick'));

  await waitFor(() =>
    expect(screen.getByTestId('tick-error')).toHaveTextContent(
      'сбой расчёта, откат',
    ),
  );
});

it('reset stays disabled with the hint while reset_allowed is false', async () => {
  allowSection({ resetAllowed: false });
  await enterSection();

  expect(screen.getByTestId('open-reset')).toBeDisabled();
  expect(screen.getByTestId('reset-hint')).toHaveTextContent(
    'Сейчас выключено на этом сервере — кнопка недоступна.',
  );
});

it('with reset allowed the confirm stays disabled until «СБРОС» exactly', async () => {
  const counters = allowSection({ resetAllowed: true });
  await enterSection();

  fireEvent.click(screen.getByTestId('open-reset'));
  await screen.findByTestId('reset-popup');
  const confirm = screen.getByTestId('confirm-reset');
  expect(confirm).toBeDisabled();

  const input = screen.getByLabelText(
    'Наберите «СБРОС» для подтверждения',
  );
  // Wrong case never unlocks it.
  fireEvent.change(input, { target: { value: 'сброс' } });
  expect(confirm).toBeDisabled();

  fireEvent.change(input, { target: { value: 'СБРОС' } });
  expect(confirm).toBeEnabled();

  fireEvent.click(confirm);
  await waitFor(() => expect(counters.reset).toBe(1));
  await waitFor(() =>
    expect(screen.queryByTestId('reset-popup')).not.toBeInTheDocument(),
  );
  await waitFor(() => expect(counters.overview).toBe(2));
});

it('the tick journal shows ✓ and ✕ rows with the error text', async () => {
  allowSection();
  await enterSection();

  const table = screen.getByTestId('tick-log-table');
  expect(table).toHaveTextContent('✓ Успешно');
  expect(table).toHaveTextContent('✕ Ошибка');
  expect(table).toHaveTextContent('сбой расчёта, откат');
  expect(table).toHaveTextContent('2 · март 2040');
});

it('a 401 from the section ends the session through the frame', async () => {
  allowSection();
  server.use(
    http.get('*/api/v1/admin/overview', () =>
      HttpResponse.json(
        { detail: 'Unauthorized', code: 'UNAUTHORIZED' },
        { status: 401 },
      ),
    ),
  );
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();

  await screen.findByText('Сеанс закончился');
  expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
});
