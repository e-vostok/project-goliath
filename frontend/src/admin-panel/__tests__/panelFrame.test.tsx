/**
 * Admin panel frame (0.11.0 unit 5a): hash navigation across the
 * seven sections, the «Сеанс: ещё N мин» countdown, session end and
 * «Выйти». msw stands at the HTTP boundary.
 */

import {
  act,
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

function renderPanel() {
  return render(
    <ThemeProvider listenVkScheme={false}>
      <AdminApp />
    </ThemeProvider>,
  );
}

function allowExchange(expiresInSeconds = 3600) {
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: expiresInSeconds,
      }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    // The default #/turn section loads its data on mount.
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession(); // the in-memory copy must not leak between tests
  window.history.replaceState(null, '', '/admin.html');
});

afterEach(() => {
  vi.useRealTimers();
});

it('clicking a menu item changes the hash route and the shown section', async () => {
  window.location.hash = `#t=${LINK_TOKEN}`;
  allowExchange();
  renderPanel();

  // Default route lands on «Ход и мир».
  const turnHeadings = await screen.findAllByText('Ход и мир');
  expect(turnHeadings.length).toBeGreaterThan(0);
  await waitFor(() => expect(window.location.hash).toBe('#/turn'));

  fireEvent.click(screen.getByRole('link', { name: /Государства/ }));

  // The hash route moved and the content card switched.
  await waitFor(() =>
    expect(window.location.hash).toBe('#/nations'),
  );
  await screen.findByRole('heading', { name: 'Государства' });
});

it('the countdown ticks every 30 s and the session ends with «Сеанс закончился»', async () => {
  window.location.hash = `#t=${LINK_TOKEN}`;
  allowExchange(120); // session: two minutes
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    // Fake Date too: the «ещё N мин» label reads Date.now().
    toFake: [
      'setTimeout',
      'clearTimeout',
      'setInterval',
      'clearInterval',
      'Date',
    ],
  });

  renderPanel();

  const left = await screen.findByTestId('panel-session-left');
  // The frame mounts inside findBy's polling — flush its effects
  // (the 30 s tick interval and the expiry timeout) before advancing.
  await act(async () => {});
  expect(left).toHaveTextContent('Сеанс: ещё 2 мин');

  // 30 s tick: 90 s left — still «2 мин» (ceil).
  act(() => vi.advanceTimersByTime(30_000));
  expect(left).toHaveTextContent('Сеанс: ещё 2 мин');

  // 60 s left → «ещё 1 мин».
  act(() => vi.advanceTimersByTime(30_000));
  expect(left).toHaveTextContent('Сеанс: ещё 1 мин');

  // Time runs out → the session card.
  act(() => vi.advanceTimersByTime(65_000));
  await screen.findByText('Сеанс закончился');
});

it('«Выйти» clears the stored session and shows the logout card', async () => {
  window.location.hash = `#t=${LINK_TOKEN}`;
  allowExchange();
  renderPanel();

  await screen.findByRole('navigation', { name: 'Разделы панели' });
  expect(window.sessionStorage.getItem(SESSION_KEY)).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));

  await screen.findByText('Вы вышли из панели');
  expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
});

it('the frame fills the window and the menu caption is the menu\'s last child', async () => {
  // A stored session opens straight into the short «Игроки» section.
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      token: 'panel-session-jwt-xyz',
      exp: Date.now() + 3_600_000,
    }),
  );
  window.location.hash = '#/players';
  server.use(
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/players', () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
  renderPanel();

  const nav = await screen.findByRole('navigation', {
    name: 'Разделы панели',
  });
  const frame = screen.getByTestId('panel-frame');
  expect(frame.style.minHeight).toBe('100vh');
  expect(nav.lastElementChild).toHaveTextContent(
    'Каждое действие пишется в журнал.',
  );
});

it('a later 401 from the API ends the session the same way', async () => {
  window.location.hash = `#t=${LINK_TOKEN}`;
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: 3600,
      }),
    ),
    http.get('*/api/v1/game-clock', () =>
      HttpResponse.json(
        { detail: 'Unauthorized', code: 'UNAUTHORIZED' },
        { status: 401 },
      ),
    ),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
  );
  renderPanel();

  await screen.findByText('Сеанс закончился');
  expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
});
