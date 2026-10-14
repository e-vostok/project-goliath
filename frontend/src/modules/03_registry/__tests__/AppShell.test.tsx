/**
 * AppShell — registry route integration (jsdom; network via msw).
 *
 * A player WITHOUT a nation opens /registry and stays (the panel is
 * exempt from the nation redirect, like PANEL_MAP); the «Реестр»
 * entry button is hidden on the Registry panel itself.
 */

import { screen, waitFor } from '@testing-library/react';
import { render } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
} from '@vkontakte/vk-mini-apps-router';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
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
import {
  AppShell,
  PANEL_CREATE,
  PANEL_HOME,
  PANEL_MAP,
  PANEL_REGISTRY,
} from '../../../app/AppShell';
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
    http.get('*/api/v1/nations/rules', () =>
      HttpResponse.json({
        name_min_length: 4,
        name_max_length: 37,
        leader_name_min_length: 2,
        leader_name_max_length: 33,
        leader_title_min_length: 3,
        leader_title_max_length: 44,
        history_url_max_length: 321,
        history_url_allowed_hosts: ['vk.com'],
        min_provinces: 2,
        max_provinces: 7,
      }),
    ),
    http.get('*/api/v1/provinces', () => HttpResponse.json([])),
    http.get('*/api/v1/game-clock', () =>
      HttpResponse.json({
        current_turn: 12,
        game_date: '15 марта 1240',
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

describe('AppShell — /registry route', () => {
  it('a player without a nation opens /registry and is not redirected; the «Реестр» button is hidden on the registry panel', async () => {
    registerAppHandlers();
    window.location.hash = '#/registry';
    const router = createHashRouter([
      { path: '/', panel: PANEL_HOME, view: 'main' },
      { path: '/nation/new', panel: PANEL_CREATE, view: 'main' },
      { path: '/map', panel: PANEL_MAP, view: 'main' },
      { path: '/registry', panel: PANEL_REGISTRY, view: 'main' },
    ]);
    render(
      <ConfigProvider platform={Platform.VKCOM}>
        <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
          <AppRoot>
            <RouterProvider router={router}>
              <AppShell />
            </RouterProvider>
          </AppRoot>
        </AdaptivityProvider>
      </ConfigProvider>,
    );

    // Registry rows resolved → auth + nation probe + table fetches done.
    await screen.findByText('Борис Иванов', undefined, { timeout: 5000 });

    // Give the redirect effect a chance to (not) fire.
    await waitFor(() =>
      expect(screen.getByTestId('panel-registry')).toBeInTheDocument(),
    );
    expect(window.location.hash).toBe('#/registry');

    // «Реестр» hidden on its own panel; «Карта» stays available.
    expect(
      screen.queryByRole('button', { name: 'Реестр' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Карта' }),
    ).toBeInTheDocument();
  });
});
