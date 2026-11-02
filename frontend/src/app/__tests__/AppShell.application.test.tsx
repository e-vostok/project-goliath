/**
 * AppShell — the application («анкета») routing of 0.13.0 unit 7a
 * (Spec applications §2, §10, APP-5; jsdom; network via msw).
 *
 * Three states of the home slot:
 *   nation exists            → «Штаб» (the application is ignored);
 *   no nation, PENDING       → the «Анкета» window + top-bar tab —
 *                              the player CAN still open the map and
 *                              the Registry;
 *   no nation, DRAFT / none  → the registration window.
 * The `#application` bot link normalizes like `#map`; without a
 * pending application the route falls back to the default panel.
 */

import { fireEvent, screen, waitFor } from '@testing-library/react';
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

import { server } from '../../../vitest.setup';
import { ThemeProvider } from '../../shared/ui';
import type { ApplicationDTO, NationDTO } from '../../shared/types';
import {
  APPLICATION_PENDING,
  GAME_CLOCK,
  RULES,
  SESSION,
} from '../../modules/00_core/components/__tests__/helpers';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../../modules/01_map/fixtures/miniMap';

// jsdom's AbortSignal is not undici's — @remix-run/router's
// createClientSideRequest does `new Request(url, {signal})` inside
// every `navigator.push` and throws (the signal only feeds loader
// fetches, none exist here). Subclassing keeps the real Request —
// msw intercepted it before this stub installs.
class JsdomSafeRequest extends Request {
  constructor(input: string | URL | Request, init?: RequestInit) {
    const { signal, ...rest } = init ?? {};
    super(input, rest);
    if (signal !== undefined) {
      Object.defineProperty(this, 'signal', {
        value: signal,
        configurable: true,
      });
    }
  }
}
beforeAll(() => {
  vi.stubGlobal('Request', JsdomSafeRequest);
});

import {
  AppShell,
  normalizeEntryHash,
  PANEL_APPLICATION,
  PANEL_CREATE,
  PANEL_HOME,
  PANEL_MAP,
  PANEL_REGISTRY,
} from '../AppShell';

const AUTH_RESPONSE = {
  access_token: SESSION.token,
  token_type: 'bearer',
  expires_in: 3600,
  player: SESSION.player,
};

const NATION: NationDTO = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Testia',
  short_name: 'ТЕС',
  color_hex: '#e64545',
  owner_player_id: SESSION.player.id,
  created_at: '2026-09-27T00:00:00Z',
  motto: null,
  description: null,
  flag_url: null,
  flag_thumb_url: null,
  province_ids: [1005, 1006, 1007],
  capital_province_id: 1005,
  capital_name: 'Столицево',
  leader_name: 'Иван Грозный',
  gender: 'male',
  leader_title: 'Верховный правитель',
  leader_bio: null,
  portrait_url: null,
  portrait_thumb_url: null,
  succession_type: 'elections',
  history_url: null,
  anthem_url: null,
  level: 1,
  judge_rating: 0,
};

const application404 = () =>
  http.get('*/api/v1/applications/me', () =>
    HttpResponse.json(
      { detail: 'Application not found', code: 'APPLICATION_NOT_FOUND' },
      { status: 404 },
    ),
  );

const nation404 = () =>
  http.get('*/api/v1/nations/me', () =>
    HttpResponse.json(
      { detail: 'Nation not found', code: 'NATION_NOT_FOUND' },
      { status: 404 },
    ),
  );

function registerAppHandlers() {
  server.use(
    http.post('*/api/v1/auth/vk', () => HttpResponse.json(AUTH_RESPONSE)),
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
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.get('*/api/v1/provinces', () => HttpResponse.json([])),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(GAME_CLOCK)),
    http.get('*/api/v1/orders/rules', () =>
      HttpResponse.json({
        title_min_length: 4,
        title_max_length: 77,
        summary_min_length: 9,
        summary_max_length: 444,
        url_max_length: 188,
        max_unresolved_orders: 7,
        unresolved_orders: 2,
      }),
    ),
    http.get('*/api/v1/orders/assigned', () =>
      HttpResponse.json({ items: [] }),
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
    http.get('*/api/v1/map/province-names', () =>
      HttpResponse.json({
        map_version: MINI_MANIFEST.geometry_version,
        names: {},
      }),
    ),
    http.get('*/api/v1/registry/tables', () =>
      HttpResponse.json({ layout: {}, tables: [] }),
    ),
  );
}

/**
 * Module-level router state leaks between tests — the same cleanup the
 * Registry shell tests run.
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

function renderApp(overrides?: () => void) {
  liveRouter?.dispose();
  resetRouterSingletons();
  registerAppHandlers();
  overrides?.();
  const router = createHashRouter([
    { path: '/', panel: PANEL_HOME, view: 'main' },
    { path: '/nation/new', panel: PANEL_CREATE, view: 'main' },
    { path: '/application', panel: PANEL_APPLICATION, view: 'main' },
    { path: '/application/:sub', panel: PANEL_APPLICATION, view: 'main' },
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

describe('normalizeEntryHash — the #application bot link', () => {
  it('rewrites the bare #application hash to the application route', () => {
    window.location.hash = '#application';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/application');
  });

  it.each([
    ['#application/a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d', '#/application/a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d'],
    ['#application/not-a-uuid', '#/'],
    ['#application/', '#/'],
    ['#application/a1b2', '#/'],
  ])('rewrites %s to %s', (from, to) => {
    window.location.hash = from;
    normalizeEntryHash();
    expect(window.location.hash).toBe(to);
  });
});

describe('AppShell — the application window replaces «Штаб»', () => {
  it('a nationless player with a PENDING application lands on «Анкета», whatever the start route', async () => {
    window.location.hash = '#/';
    let appHits = 0;
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () => {
          appHits += 1;
          return HttpResponse.json(APPLICATION_PENDING);
        }),
      );
    });

    await waitFor(() => expect(appHits).toBeGreaterThan(0));
    await waitFor(() =>
      expect(window.location.hash).toBe('#/application'),
    );
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();
    expect(await screen.findByText('На рассмотрении')).toBeInTheDocument();
    // The «Штаб» tab is replaced by «Анкета» — map and registry stay.
    expect(tab('Анкета')).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('tab', { name: 'Штаб' })).toBeNull();
    expect(tab('Реестр')).toBeInTheDocument();
    expect(tab('Карта')).toBeInTheDocument();
  });

  it('with a PENDING application /nation/new bounces back to the application', async () => {
    window.location.hash = '#/nation/new';
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () =>
          HttpResponse.json(APPLICATION_PENDING),
        ),
      );
    });

    await waitFor(() =>
      expect(window.location.hash).toBe('#/application'),
    );
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();
  });

  it('a nationless player with a DRAFT application sees registration — «Анкета» is not a tab', async () => {
    window.location.hash = '#/application';
    const draft: ApplicationDTO = {
      ...APPLICATION_PENDING,
      status: 'DRAFT',
      draft_reason: 'cancelled',
      review_deadline_at: null,
      submissions: 1,
    };
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () =>
          HttpResponse.json(draft),
        ),
      );
    });

    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    expect(
      await screen.findByTestId('panel-create-nation'),
    ).toBeInTheDocument();
    // The «отменена вами» plate sits above the tabs (mockup 19d).
    expect(
      await screen.findByTestId('application-cancelled-plate'),
    ).toBeInTheDocument();
    expect(screen.getByText('Вы отменили анкету')).toBeInTheDocument();
    // The server draft filled the form — not the empty start.
    expect(screen.getByLabelText('Полное название')).toHaveValue('Testia');
    expect(screen.queryByRole('tab', { name: 'Анкета' })).toBeNull();
  });

  it('a nationless player without an application sees the plain registration on /application', async () => {
    window.location.hash = '#/application';
    renderApp(() => {
      server.use(nation404());
      server.use(application404());
    });

    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    expect(
      await screen.findByTestId('panel-create-nation'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Анкета' })).toBeNull();
  });

  it('a player with a nation on /application falls back to «Штаб»', async () => {
    window.location.hash = '#/application';
    renderApp(() => {
      server.use(
        http.get('*/api/v1/nations/me', () => HttpResponse.json(NATION)),
      );
      server.use(application404());
    });

    await waitFor(() => expect(window.location.hash).toBe('#/'));
    // The own nation card — the «Штаб» tab is back and active.
    expect(await screen.findByText('Testia')).toBeInTheDocument();
    expect(tab('Штаб')).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('tab', { name: 'Анкета' })).toBeNull();
  });
});

describe('AppShell — the admin review link #application/<id> (unit 7b)', () => {
  const ADMIN_ID = 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d';
  const adminDto = {
    ...APPLICATION_PENDING,
    id: ADMIN_ID,
    owner_vk_user_id: 987654,
    owner_name: 'Иван Петров',
    assigned_to_me: true,
    submitted_at: '2026-10-31T11:20:00Z',
    decided_at: null,
    auto_accepted: null,
    accepted_nation_id: null,
  };

  it('an administrator WITH a nation opens the review window — the state redirect does not bounce it', async () => {
    window.location.hash = `#/application/${ADMIN_ID}`;
    renderApp(() => {
      server.use(
        http.get('*/api/v1/nations/me', () => HttpResponse.json(NATION)),
      );
      server.use(application404());
      server.use(
        http.get(`*/api/v1/admin/applications/${ADMIN_ID}`, () =>
          HttpResponse.json(adminDto),
        ),
      );
    });

    expect(await screen.findByTestId('application-admin')).toBeInTheDocument();
    // The hash stays on the review address — no redirect to «Штаб».
    expect(window.location.hash).toBe(`#/application/${ADMIN_ID}`);
    const facts = await screen.findByTestId('application-admin-facts');
    expect(facts).toHaveTextContent('Иван Петров');
    expect(
      screen.getByTestId('application-admin-actions'),
    ).toBeInTheDocument();
  });

  it('a non-administrator gets the plain default panel — the 403 shows no error', async () => {
    window.location.hash = `#/application/${ADMIN_ID}`;
    renderApp(() => {
      server.use(
        http.get('*/api/v1/nations/me', () => HttpResponse.json(NATION)),
      );
      server.use(application404());
      server.use(
        http.get(`*/api/v1/admin/applications/${ADMIN_ID}`, () =>
          HttpResponse.json(
            { detail: 'not an admin', code: 'ADMIN_REQUIRED' },
            { status: 403 },
          ),
        ),
      );
    });

    // Back on the default panel («Штаб» for a nation owner).
    await waitFor(() => expect(window.location.hash).toBe('#/'));
    expect(await screen.findByText('Testia')).toBeInTheDocument();
    expect(
      screen.queryByTestId('application-admin'),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('AppShell — audit of PR 267', () => {
  it('acceptance flips to «Штаб» without ever rendering the empty registration', async () => {
    // PENDING, next poll answers 404 and /nations/me now answers a
    // nation — the shell must hold the loading cell until the refetch
    // resolves: the empty PanelCreateNation never mounts, not even
    // for a frame.
    let appLive = true;
    let nationLive = false;
    window.location.hash = '#/';
    const seen: string[] = [];
    const observer = new MutationObserver(() => {
      for (const el of document.querySelectorAll('[data-testid]')) {
        const id = el.getAttribute('data-testid');
        if (id !== null && !seen.includes(id)) {
          seen.push(id);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    renderApp(() => {
      server.use(
        http.get('*/api/v1/applications/me', () =>
          appLive
            ? HttpResponse.json(APPLICATION_PENDING)
            : HttpResponse.json(
                { detail: 'gone', code: 'APPLICATION_NOT_FOUND' },
                { status: 404 },
              ),
        ),
        http.get('*/api/v1/nations/me', () =>
          nationLive
            ? HttpResponse.json(NATION)
            : HttpResponse.json(
                { detail: 'none', code: 'NATION_NOT_FOUND' },
                { status: 404 },
              ),
        ),
      );
    });
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();

    appLive = false;
    nationLive = true;
    fireEvent.focus(window);

    await waitFor(() => expect(window.location.hash).toBe('#/'));
    expect(await screen.findByText('Testia')).toBeInTheDocument();
    expect(seen).not.toContain('panel-create-nation');
    observer.disconnect();
  });

  it('a poll answering a returned DRAFT lands on registration with the plate', async () => {
    let appLive = true;
    const returned = {
      ...APPLICATION_PENDING,
      status: 'DRAFT' as const,
      draft_reason: 'returned' as const,
      return_comment: 'Ссылка битая.',
      review_deadline_at: null,
    };
    window.location.hash = '#/';
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () =>
          appLive
            ? HttpResponse.json(APPLICATION_PENDING)
            : HttpResponse.json(returned),
        ),
      );
    });
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();

    appLive = false;
    fireEvent.focus(window);

    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    const plate = await screen.findByTestId('application-returned-plate');
    expect(plate).toHaveTextContent('Анкета возвращена администратором');
    expect(plate).toHaveTextContent('«Ссылка битая.»');
  });

  it('a poll 404 while the nation is still absent lands on registration', async () => {
    let appLive = true;
    window.location.hash = '#/';
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () =>
          appLive
            ? HttpResponse.json(APPLICATION_PENDING)
            : HttpResponse.json(
                { detail: 'gone', code: 'APPLICATION_NOT_FOUND' },
                { status: 404 },
              ),
        ),
      );
    });
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();

    appLive = false;
    fireEvent.focus(window);

    await waitFor(() =>
      expect(window.location.hash).toBe('#/nation/new'),
    );
    expect(
      await screen.findByTestId('panel-create-nation'),
    ).toBeInTheDocument();
    // A vanished application with no return reason — plain form.
    expect(
      screen.queryByTestId('application-returned-plate'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('application-cancelled-plate'),
    ).not.toBeInTheDocument();
  });

  it('a failed application load shows the error + retry — never the empty registration', async () => {
    let appFails = true;
    window.location.hash = '#/';
    renderApp(() => {
      server.use(nation404());
      server.use(
        http.get('*/api/v1/applications/me', () =>
          appFails
            ? HttpResponse.json(
                { detail: 'boom', code: 'INTERNAL' },
                { status: 500 },
              )
            : HttpResponse.json(APPLICATION_PENDING),
        ),
      );
    });

    expect(
      await screen.findByText('Не удалось загрузить анкету'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('panel-create-nation'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('Полное название'),
    ).not.toBeInTheDocument();

    // «Повторить» retries the same GET — the PENDING answer moves the
    // shell to «Анкета».
    appFails = false;
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('panel-application')).toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.hash).toBe('#/application'),
    );
  });
});
