/**
 * AppShell — registry route + top bar integration (jsdom; network via
 * msw).
 *
 * A player WITHOUT a nation opens /registry and stays (the panel is
 * exempt from the nation redirect, like PANEL_MAP); the permanent top
 * bar shows the active screen's tab selected and navigates between
 * routes (unit 4a — the floating entry buttons are gone).
 */

import { screen, waitFor } from '@testing-library/react';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
} from '@vkontakte/vk-mini-apps-router';
// Deep imports (no exports map — same pattern as the shell's
// `dist/hooks/hooks` useLocation import): the router keeps the context
// throttle values and the navigation transaction queue in module-level
// singletons that survive between tests.
import { ContextThrottleService } from '@vkontakte/vk-mini-apps-router/dist/services/ContextThrottleService';
import { TransactionExecutor } from '@vkontakte/vk-mini-apps-router/dist/services/TransactionExecutor';
import {
  AdaptivityProvider,
  AppRoot,
  ViewWidth,
} from '@vkontakte/vkui';

// RouterProvider pings VK Bridge on navigation; outside VK it would hit
// a real fetch — stub it.
vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

import { server } from '../../../../vitest.setup';
import { ThemeProvider } from '../../../shared/ui';
import type { NationPublicDTO } from '../../../shared/types';
import type { RegistryRowsDTO } from '../types';
import { RULES } from '../../00_core/components/__tests__/helpers';
import {
  AppShell,
  normalizeEntryHash,
  PANEL_CREATE,
  PANEL_HOME,
  PANEL_MAP,
  PANEL_REGISTRY,
} from '../../../app/AppShell';
import { takeRegistryEntryRequest } from '../lib/entryRequest';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../../01_map/fixtures/miniMap';
import {
  NATIONS_ROWS,
  PLAYERS_ROWS,
  SESSION,
  TABLES,
} from './helpers';

const AUTH_RESPONSE = {
  access_token: SESSION.token,
  token_type: 'bearer',
  expires_in: 3600,
  player: SESSION.player,
};

function registerAppHandlers() {
  server.use(
    http.post('*/api/v1/auth/vk', () => HttpResponse.json(AUTH_RESPONSE)),
    // Player without a nation: 404 is the normal "no nation" signal.
    http.get('*/api/v1/nations/me', () =>
      HttpResponse.json(
        { detail: 'Nation not found', code: 'NATION_NOT_FOUND' },
        { status: 404 },
      ),
    ),
    http.get('*/api/v1/bot/status', () =>
      HttpResponse.json({
        enabled: false,
        consent: 'UNKNOWN',
        stale: false,
        throttled: false,
        registration_requires_consent: false,
        chat_url: null,
        consent_poll_interval_seconds: null,
        consent_poll_timeout_seconds: null,
      }),
    ),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: false }),
    ),
    // The VKUI View mounts EVERY panel eagerly — PanelCreateNation is
    // always up (nation===null) and its symbols tab reads rules.flags;
    // the full RULES fixture keeps it alive.
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.get('*/api/v1/provinces', () => HttpResponse.json([])),
    http.get('*/api/v1/game-clock', () =>
      HttpResponse.json({
        current_turn: 12,
        game_date: '2041-01-01',
        game_date_text: 'Январь 2041',
        next_tick_at: '2026-10-15T03:00:00Z',
      }),
    ),
    http.get('*/api/v1/map/manifest', () =>
      HttpResponse.json(MINI_MANIFEST),
    ),
    http.get('*/api/v1/map/geometry/:version', () =>
      HttpResponse.json(MINI_GEOMETRY),
    ),
    http.get('*/api/v1/map/borders/:version', () =>
      HttpResponse.json(MINI_BORDERS),
    ),
    http.get('*/api/v1/map/state', () => HttpResponse.json(MINI_STATE)),
    http.get('*/api/v1/registry/tables', () =>
      HttpResponse.json(TABLES),
    ),
    http.get('*/api/v1/registry/tables/players', () =>
      HttpResponse.json(PLAYERS_ROWS),
    ),
    http.get('*/api/v1/registry/tables/nations', () =>
      HttpResponse.json(NATIONS_ROWS),
    ),
  );
}

describe('normalizeEntryHash — registry links (#registry, #registry/order-N)', () => {
  afterEach(() => {
    takeRegistryEntryRequest(); // never leak a stored request between tests
  });

  it('rewrites the bare #registry hash to the registry route (community menu link)', () => {
    window.location.hash = '#registry';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/registry');
    expect(takeRegistryEntryRequest()).toBeNull();
  });

  it('rewrites a 1-9 digit order hash to the registry route with a stored request; anything else is ignored', () => {
    window.location.hash = '#registry/order-12';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/registry');
    expect(takeRegistryEntryRequest()).toEqual({
      tab: 'orders',
      action: 'order:12',
    });

    // More than nine digits — ignored, the hash stays untouched.
    window.location.hash = '#registry/order-1234567890';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#registry/order-1234567890');
    expect(takeRegistryEntryRequest()).toBeNull();

    // Non-digits — ignored.
    window.location.hash = '#registry/order-abc';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#registry/order-abc');
    expect(takeRegistryEntryRequest()).toBeNull();
  });
});

describe('normalizeEntryHash — nation subscreen links (#registry/nation-<id>)', () => {
  it('rewrites a bare #registry/nation-<id> hash to the subscreen route', () => {
    window.location.hash = '#registry/nation-a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d';
    normalizeEntryHash();
    expect(window.location.hash).toBe(
      '#/registry/nation-a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d',
    );
  });

  it('rewrites a malformed nation id to the plain Registry — no error', () => {
    // 'zz' is outside the hex+dash alphabet.
    window.location.hash = '#registry/nation-zz-not-an-id';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/registry');
    // Too short.
    window.location.hash = '#registry/nation-ab12';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/registry');
    // Not a nation suffix at all — left untouched (same as bad orders).
    window.location.hash = '#registry/other-thing';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#registry/other-thing');
  });
});

/**
 * Module-level router state leaks between tests: the throttle service
 * feeds a NEW RouterProvider's hooks the PREVIOUS test's route (and a
 * pending throttle timer can broadcast it back mid-test), and an
 * unfinished navigation transaction makes the first context update get
 * dropped. Clear both — and disable throttling via `throttled={false}`
 * below — so every test sees the real route synchronously.
 */
function resetRouterSingletons() {
  const service = ContextThrottleService.getInstance() as unknown as {
    contextThrottleMap: Map<string, { updateTimerId: number }>;
  };
  for (const data of service.contextThrottleMap.values()) {
    clearTimeout(data.updateTimerId);
  }
  service.contextThrottleMap.clear();
  ContextThrottleService.updateThrottledServiceSettings({
    interval: 0,
    throttled: false,
  });
  TransactionExecutor.resetTransactions();
}

let liveRouter: ReturnType<typeof createHashRouter> | null = null;

/**
 * msw gives the LAST `server.use` precedence, so per-test overrides must
 * be registered after the defaults — before `render` fires the fetches.
 */
function renderApp(overrides?: () => void) {
  // The previous test's router still listens to hashchange — dispose it
  // or it keeps reacting to this test's `location.hash` writes.
  liveRouter?.dispose();
  resetRouterSingletons();
  registerAppHandlers();
  overrides?.();
  const router = createHashRouter([
    { path: '/', panel: PANEL_HOME, view: 'main' },
    { path: '/nation/new', panel: PANEL_CREATE, view: 'main' },
    { path: '/map', panel: PANEL_MAP, view: 'main' },
    { path: '/registry', panel: PANEL_REGISTRY, view: 'main' },
    { path: '/registry/:sub', panel: PANEL_REGISTRY, view: 'main' },
  ]);
  liveRouter = router;
  render(
    <ThemeProvider>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <RouterProvider router={router} throttled={false}>
            <AppShell />
          </RouterProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ThemeProvider>,
  );
  return router;
}

const tab = (name: string) => screen.getByRole('tab', { name });

describe('AppShell — auth gate (board «Loading», unit 12b)', () => {
  it('shows the loading screen while POST /auth/vk resolves', () => {
    window.location.hash = '#/';
    renderApp();
    // First paint — the answer has not arrived yet.
    expect(screen.getByTestId('loading-screen')).toBeInTheDocument();
    expect(screen.getByText('PAX ATOMICA')).toBeInTheDocument();
    expect(screen.getByText('Загрузка…')).toBeInTheDocument();
  });

  it('shows the auth error screen with «Повторить» when /auth/vk fails', async () => {
    window.location.hash = '#/';
    renderApp(() => {
      server.use(
        http.post('*/api/v1/auth/vk', () =>
          HttpResponse.json(
            { detail: 'bad signature' },
            { status: 403 },
          ),
        ),
      );
    });

    await screen.findByTestId('auth-error-screen');
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText(/Не удалось войти\./)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Повторить' }),
    ).toBeInTheDocument();
  });
});

describe('AppShell — /registry route', () => {
  it('a player without a nation opens /registry and is not redirected; «Реестр» is the active top bar tab', async () => {
    window.location.hash = '#/registry';
    renderApp();

    // Registry rows resolved → auth + nation probe + table fetches done.
    await screen.findByText('Борис Иванов', undefined, { timeout: 5000 });

    // Give the redirect effect a chance to (not) fire.
    await waitFor(() =>
      expect(screen.getByTestId('panel-registry')).toBeInTheDocument(),
    );
    expect(window.location.hash).toBe('#/registry');
    expect(tab('Реестр')).toHaveAttribute('aria-selected', 'true');
  });
});

describe('AppShell — top bar', () => {
  it('the active tab follows the panel and each tab navigates to its route', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/';
    renderApp();

    // No nation: the shell's redirect sends «Штаб» to registration,
    // the tab stays «Штаб».
    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    await waitFor(() =>
      expect(tab('Штаб')).toHaveAttribute('aria-selected', 'true'),
    );

    await user.click(tab('Реестр'));
    await waitFor(() => expect(window.location.hash).toBe('#/registry'));
    await waitFor(() =>
      expect(tab('Реестр')).toHaveAttribute('aria-selected', 'true'),
    );

    await user.click(tab('Карта'));
    await waitFor(() => expect(window.location.hash).toBe('#/map'));
    await waitFor(() =>
      expect(tab('Карта')).toHaveAttribute('aria-selected', 'true'),
    );

    await user.click(tab('Штаб'));
    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    await waitFor(() =>
      expect(tab('Штаб')).toHaveAttribute('aria-selected', 'true'),
    );
  });
});

/* -------------------------------------------------- nation subscreen */

/** A route-valid nation id (the shared fixtures use non-hex 'n1'). */
const NATION_ID = 'a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d';

const NATION_PUBLIC: NationPublicDTO = {
  id: NATION_ID,
  created_at: '2026-09-01T12:00:00Z',
  name: 'Новгород',
  short_name: 'НВГ',
  color_hex: '#C0392B',
  motto: 'Слово и дело',
  description: 'Вольный город на севере.',
  flag_id: null,
  flag_url: null,
  province_ids: [1002, 1001],
  capital_province_id: 1001,
  capital_name: 'Новгород-град',
  leader_name: 'Борис Первый',
  leader_title: 'Князь',
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  history_url: 'https://vk.com/@novgorod-history',
  level: 3,
  judge_rating: 12,
};

/**
 * Players rows where the nation cells carry the hex-alphabet id the
 * `#/registry/nation-<id>` address accepts; the second row holds the
 * orders-table shape — an `id: null` snapshot that stays plain text.
 */
const PLAYERS_NATION_ROWS: RegistryRowsDTO = {
  table_id: 'players',
  total: 2,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    {
      key: 'p1',
      cells: {
        number: 1,
        player: { name: 'Борис Иванов', avatar_url: null, is_fallback: false },
        joined: { text: '1 сентября 2026', key: 20697 },
        level: 1,
        nation: {
          id: NATION_ID,
          name: 'Новгород',
          color: '#C0392B',
          flag_url: null,
        },
      },
    },
    {
      key: 'p2',
      cells: {
        number: 2,
        player: { name: 'Анна Смирнова', avatar_url: null, is_fallback: false },
        joined: { text: '5 сентября 2026', key: 20701 },
        level: 2,
        nation: {
          id: null,
          name: 'Безвестная вотчина',
          color: '#555555',
          flag_url: null,
        },
      },
    },
  ],
};

/** Nations rows keyed by real nation ids (row.key IS the nation id). */
const NATIONS_KEY_ROWS: RegistryRowsDTO = {
  table_id: 'nations',
  total: 2,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    {
      key: NATION_ID,
      cells: {
        number: 1,
        name: 'Новгород',
        formed: { text: 'Январь 2041', key: 12 },
      },
    },
    {
      key: 'e5f6a7b8-1c2d-3e4f-5a6b-7c8d9e0f1a2b',
      cells: {
        number: 2,
        name: 'Рязань',
        formed: { text: 'Май 2043', key: 40 },
      },
    },
  ],
};

function registerNationSubscreen() {
  server.use(
    http.get(`*/api/v1/nations/${NATION_ID}`, () =>
      HttpResponse.json(NATION_PUBLIC),
    ),
  );
}

describe('AppShell — nation subscreen', () => {
  it('a direct link «#/registry/nation-<id>» shows the subscreen; «Реестр» stays the active tab and «← Реестр» returns to #/registry', async () => {
    const user = userEvent.setup();
    window.location.hash = `#/registry/nation-${NATION_ID}`;
    renderApp(registerNationSubscreen);

    await screen.findByTestId('nation-subscreen');
    // «Реестр / Государство · Новгород» — a bare link carries no tab.
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Государство · НВГ',
    );
    expect(tab('Реестр')).toHaveAttribute('aria-selected', 'true');

    await user.click(screen.getByTestId('subscreen-back'));
    await waitFor(() => expect(window.location.hash).toBe('#/registry'));
    // A direct-link return lands on the plain Registry (first tab).
    expect(await screen.findByText('Борис Иванов')).toBeInTheDocument();
  });

  it('an invalid id shows the plain Registry, no error', async () => {
    window.location.hash = '#/registry/nation-not-valid!';
    renderApp();
    expect(await screen.findByText('Борис Иванов')).toBeInTheDocument();
    expect(screen.queryByTestId('subscreen')).toBeNull();
  });

  it('a too-short id shows the plain Registry as well', async () => {
    window.location.hash = '#/registry/nation-x';
    renderApp();
    expect(await screen.findByText('Борис Иванов')).toBeInTheDocument();
    expect(screen.queryByTestId('subscreen')).toBeNull();
  });

  it('a nation cell click in «Игроки» opens the subscreen with chain «Реестр / Игроки / Новгород»; an id:null cell is not a button', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/registry';
    renderApp(() => {
      registerNationSubscreen();
      server.use(
        http.get('*/api/v1/registry/tables/players', () =>
          HttpResponse.json(PLAYERS_NATION_ROWS),
        ),
      );
    });

    // The nation cell is a real button; the id:null snapshot is not.
    const nationButton = await screen.findByRole('button', {
      name: 'Новгород',
    });
    expect(
      screen.queryByRole('button', { name: 'Безвестная вотчина' }),
    ).toBeNull();
    expect(screen.getByText('Безвестная вотчина')).toBeInTheDocument();

    await user.click(nationButton);
    await waitFor(() =>
      expect(window.location.hash).toBe(`#/registry/nation-${NATION_ID}`),
    );
    await screen.findByTestId('nation-subscreen');
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Игроки / НВГ',
    );
  });

  it('the «Государства» name cell opens the nation by the row key', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/registry';
    renderApp(() => {
      registerNationSubscreen();
      server.use(
        http.get('*/api/v1/registry/tables/nations', () =>
          HttpResponse.json(NATIONS_KEY_ROWS),
        ),
      );
    });

    await screen.findByText('Борис Иванов');
    await user.click(
      await screen.findByRole('tab', { name: 'Государства' }),
    );

    const nameButton = await screen.findByRole('button', {
      name: 'Новгород',
    });
    // The name cell's row carries the nation id as its key.
    const row = nameButton.closest('tr');
    expect(row).toHaveAttribute('data-row-key', NATION_ID);

    await user.click(nameButton);
    await waitFor(() =>
      expect(window.location.hash).toBe(`#/registry/nation-${NATION_ID}`),
    );
    await screen.findByTestId('nation-subscreen');
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Государства / НВГ',
    );
  });

  it('«Назад» returns to the same Registry instance — tab, search text and rows are kept', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/registry';
    renderApp(() => {
      registerNationSubscreen();
      server.use(
        http.get('*/api/v1/registry/tables/nations', () =>
          HttpResponse.json(NATIONS_KEY_ROWS),
        ),
      );
    });

    await screen.findByText('Борис Иванов');
    await user.click(
      await screen.findByRole('tab', { name: 'Государства' }),
    );
    const search = await screen.findByLabelText('Поиск…');
    await user.type(search, 'Нов');
    // The search filtered the table down to Новгород only.
    await waitFor(() =>
      expect(screen.queryByText('Рязань')).not.toBeInTheDocument(),
    );

    await user.click(
      await screen.findByRole('button', { name: 'Новгород' }),
    );
    await screen.findByTestId('nation-subscreen');
    // The Registry content is hidden but mounted — still in the DOM.
    expect(screen.getByTestId('panel-registry')).toBeInTheDocument();

    await user.click(screen.getByTestId('subscreen-back'));
    await waitFor(() => expect(window.location.hash).toBe('#/registry'));

    // Same DOM input (no remount), same tab, same text, same rows.
    expect(screen.getByLabelText('Поиск…')).toBe(search);
    expect(search).toHaveValue('Нов');
    expect(tab('Государства')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: 'Новгород' })).toBeInTheDocument();
    expect(screen.queryByText('Рязань')).not.toBeInTheDocument();
  });

  it('«Показать на карте» opens #/map and selects the capital province', async () => {
    const user = userEvent.setup();
    window.location.hash = `#/registry/nation-${NATION_ID}`;
    renderApp(registerNationSubscreen);

    await user.click(
      await screen.findByRole('button', { name: 'Показать на карте' }),
    );
    await waitFor(() => expect(window.location.hash).toBe('#/map'));
    // The capital (1001 «Альфа») is selected and the map centres on it.
    await waitFor(() =>
      expect(
        document.querySelector('path[data-selected="1001"]'),
      ).not.toBeNull(),
    );
  });
});
