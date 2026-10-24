/**
 * Admin panel entry (0.11.0 unit 5a): the `#t=` one-time link is
 * lifted out of the address bar and exchanged once for a short
 * session; the four terminal cards follow the answer. msw stands at
 * the HTTP boundary — the real api-client does the requests.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { ThemeProvider } from '../../shared/ui/theme';
import { AdminApp } from '../AdminApp';
import { clearSession } from '../session';

const LINK_TOKEN = 'one-time-link-abc123';
const SESSION_TOKEN = 'panel-session-jwt-xyz';
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

function allowExchange() {
  let body: unknown;
  server.use(
    http.post('*/api/v1/admin/session', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({
        access_token: SESSION_TOKEN,
        expires_in_seconds: 3600,
      });
    }),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
  );
  return () => body;
}

const MENU_TITLES = [
  'Ход и мир',
  'Игроки',
  'Государства',
  'Провинции',
  'Приказы',
  'Администраторы',
  'Журнал',
];

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession(); // the in-memory copy must not leak between tests
  window.history.replaceState(null, '', '/admin.html');
});

describe('panel entry — one-time link', () => {
  it('exchanges #t= once, strips the fragment, stores the session, shows the frame', async () => {
    window.location.hash = `#t=${LINK_TOKEN}`;
    const readBody = allowExchange();

    renderPanel();

    // The token is out of the address bar immediately (replaceState).
    expect(window.location.href).not.toContain(LINK_TOKEN);
    expect(window.location.hash === '' || window.location.hash === '#/turn')
      .toBe(true);

    // The frame: seven menu items in the mockup's order.
    const nav = await screen.findByRole('navigation', {
      name: 'Разделы панели',
    });
    const links = nav.querySelectorAll('a');
    expect(links).toHaveLength(7);
    expect([...links].map((a) => a.textContent)).toEqual(MENU_TITLES);

    // The session token was sent once and is remembered for the tab.
    await waitFor(() =>
      expect(readBody()).toEqual({ token: LINK_TOKEN }),
    );
    expect(window.sessionStorage.getItem(SESSION_KEY)).toContain(
      SESSION_TOKEN,
    );
    expect(
      screen.getByText('Пульт · панель администратора'),
    ).toBeInTheDocument();

    // Neither token is ever rendered.
    expect(document.body.innerHTML).not.toContain(LINK_TOKEN);
    expect(document.body.innerHTML).not.toContain(SESSION_TOKEN);
  });

  it('401 PANEL_LINK_INVALID → «Ссылка устарела»', async () => {
    window.location.hash = `#t=${LINK_TOKEN}`;
    server.use(
      http.post('*/api/v1/admin/session', () =>
        HttpResponse.json(
          {
            detail: 'The panel link is invalid or expired',
            code: 'PANEL_LINK_INVALID',
          },
          { status: 401 },
        ),
      ),
    );

    renderPanel();

    await screen.findByText('Ссылка устарела');
    expect(document.body.innerHTML).not.toContain(LINK_TOKEN);
  });

  it('403 → «Нет доступа»', async () => {
    window.location.hash = `#t=${LINK_TOKEN}`;
    server.use(
      http.post('*/api/v1/admin/session', () =>
        HttpResponse.json(
          { detail: 'Admin privileges required', code: 'ADMIN_REQUIRED' },
          { status: 403 },
        ),
      ),
    );

    renderPanel();

    await screen.findByText('Нет доступа');
  });

  it('network failure → the offline card, and the spent link is not retried', async () => {
    window.location.hash = `#t=${LINK_TOKEN}`;
    let calls = 0;
    server.use(
      http.post('*/api/v1/admin/session', () => {
        calls += 1;
        return HttpResponse.error();
      }),
    );

    renderPanel();

    await screen.findByText(
      /Не удалось связаться с сервером\. Вернитесь в игру/,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(calls).toBe(1);
  });
});

describe('panel entry — no fragment', () => {
  it('no stored session → «Ссылка устарела» without any request', async () => {
    let sessionCalls = 0;
    server.use(
      http.post('*/api/v1/admin/session', () => {
        sessionCalls += 1;
        return HttpResponse.error();
      }),
    );

    renderPanel();

    await screen.findByText('Ссылка устарела');
    expect(sessionCalls).toBe(0);
  });

  it('a still-valid stored session enters the frame after GET /admin/me', async () => {
    window.sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify({
        token: SESSION_TOKEN,
        exp: Date.now() + 30 * 60_000,
      }),
    );
    server.use(
      http.get('*/api/v1/admin/me', () =>
        HttpResponse.json({ is_admin: true }),
      ),
      http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    );

    renderPanel();

    await screen.findByRole('navigation', { name: 'Разделы панели' });
    expect(
      screen.getByText('Пульт · панель администратора'),
    ).toBeInTheDocument();
  });

  it('a stored session the server rejects ends on «Ссылка устарела»', async () => {
    window.sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify({
        token: SESSION_TOKEN,
        exp: Date.now() + 30 * 60_000,
      }),
    );
    server.use(
      http.get('*/api/v1/admin/me', () =>
        HttpResponse.json(
          { detail: 'Unauthorized', code: 'UNAUTHORIZED' },
          { status: 401 },
        ),
      ),
    );

    renderPanel();

    await screen.findByText('Ссылка устарела');
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });
});
