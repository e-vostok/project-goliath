/**
 * Shared helpers for 00_core component tests: the provider wrapper, a fake
 * session, default msw handlers and wizard-filling utilities.
 *
 * The default rules body deliberately uses NON-backend-config numbers so
 * that a limit hardcoded in a component (instead of read from
 * GET /nations/rules) fails these tests.
 */

import type { ReactElement } from 'react';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../../vitest.setup';
import type { NationRulesDTO } from '../../../../shared/types';
import { SessionProvider } from '../../hooks/useAuth';
import {
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../../../01_map/fixtures/miniMap';
import { CONNECTING_EDGE_TYPES } from '../../../01_map/lib/selection';
import { clearMapSessionCache } from '../../../01_map/lib/sessionCache';
import type {
  MapManifestDTO,
  StartingGroupCheckDTO,
} from '../../../01_map/types';

export const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 123456,
    created_at: '2026-09-01T12:00:00Z',
  },
};

/** NOT the real config numbers — a hardcoded client limit would fail tests. */
export const RULES: NationRulesDTO = {
  name_min_length: 4,
  name_max_length: 37,
  leader_name_min_length: 2,
  leader_name_max_length: 33,
  leader_title_min_length: 3,
  leader_title_max_length: 44,
  history_url_max_length: 321,
  history_url_allowed_hosts: ['vk.com', 'm.vk.com'],
  min_provinces: 2,
  max_provinces: 7,
};

export const FREE_PROVINCES = [
  { id: 1, nation_id: null },
  { id: 2, nation_id: null },
];

export const GAME_CLOCK = {
  current_turn: 12,
  game_date: '15 марта 1240',
  next_tick_at: '2026-10-02T03:00:00Z',
};

/**
 * Mutable 01_map fixture served by the default msw handlers — tests
 * tweak `state` (occupied provinces) or `checkAnswer` per case.
 */
export const mswMap: {
  manifest: MapManifestDTO;
  geometry: typeof MINI_GEOMETRY;
  state: typeof MINI_STATE;
  checkAnswer: StartingGroupCheckDTO | undefined;
  checkCalls: number;
  checkRequests: number[][];
} = {
  manifest: MINI_MANIFEST,
  geometry: MINI_GEOMETRY,
  state: MINI_STATE,
  checkAnswer: undefined,
  checkCalls: 0,
  checkRequests: [],
};

export function resetMswMap() {
  mswMap.manifest = MINI_MANIFEST;
  mswMap.geometry = MINI_GEOMETRY;
  mswMap.state = MINI_STATE;
  mswMap.checkAnswer = undefined;
  mswMap.checkCalls = 0;
  mswMap.checkRequests = [];
}

/** Real connectivity over a manifest's land/strait edges (like the api). */
export function manifestCheckAnswer(
  manifest: MapManifestDTO,
  ids: number[],
): StartingGroupCheckDTO {
  const adjacency = new Map<number, number[]>();
  for (const edge of manifest.edges) {
    if (!CONNECTING_EDGE_TYPES.has(edge.type)) {
      continue;
    }
    let list = adjacency.get(edge.a);
    if (!list) {
      list = [];
      adjacency.set(edge.a, list);
    }
    list.push(edge.b);
    list = adjacency.get(edge.b);
    if (!list) {
      list = [];
      adjacency.set(edge.b, list);
    }
    list.push(edge.a);
  }
  const wanted = new Set(ids);
  const seen = new Set<number>();
  let count = 0;
  for (const start of ids) {
    if (seen.has(start)) {
      continue;
    }
    count += 1;
    const queue = [start];
    seen.add(start);
    while (queue.length > 0) {
      for (const next of adjacency.get(queue.pop() as number) ?? []) {
        if (wanted.has(next) && !seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }
  return { connected: count === 1, component_count: count };
}

/**
 * Call in beforeEach — registers every GET the 00_core panels fire on
 * mount (unhandled requests are a test failure) plus the 01_map
 * endpoints the ProvincePicker needs when it opens from window 1.
 */
export function registerDefaultHandlers() {
  resetMswMap();
  clearMapSessionCache();
  server.use(
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.get('*/api/v1/provinces', () => HttpResponse.json(FREE_PROVINCES)),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(GAME_CLOCK)),
    http.get('*/api/v1/map/manifest', () =>
      HttpResponse.json(mswMap.manifest),
    ),
    http.get('*/api/v1/map/geometry/:version', () =>
      HttpResponse.json(mswMap.geometry),
    ),
    http.get('*/api/v1/map/state', () =>
      HttpResponse.json(mswMap.state),
    ),
    http.post('*/api/v1/map/starting-group/check', async ({ request }) => {
      mswMap.checkCalls += 1;
      const body = (await request.json()) as {
        province_ids?: number[];
      };
      const ids = body.province_ids ?? [];
      mswMap.checkRequests.push(ids);
      return HttpResponse.json(
        mswMap.checkAnswer ?? manifestCheckAnswer(mswMap.manifest, ids),
      );
    }),
  );
}

export function renderWithProviders(ui: ReactElement) {
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

/** Free LAND nodes in the current mini-map fixture. */
export function freeLandNodes() {
  const owned = new Set(mswMap.state.owners.map(([id]) => id));
  return mswMap.manifest.nodes.filter(
    (n) => n.kind === 'LAND' && !owned.has(n.id),
  );
}

/**
 * Picks provinces through the real ProvincePicker modal: opens it, waits
 * for the map, clicks each id's <path>, presses «Готово».
 * Map clicks use the delegated handler contract: mousedown on the path
 * + mouseup on window (a settled click, not a drag).
 */
export async function pickProvinces(user: UserEvent, ids: number[]) {
  await user.click(screen.getByTestId('open-province-picker'));
  // Wait until the picker's map rendered (manifest+geometry resolved).
  await waitFor(() =>
    expect(
      document.querySelectorAll(
        '[data-testid="map-view"] path[data-id]',
      ).length,
    ).toBeGreaterThan(0),
  );
  for (const id of ids) {
    const path = document.querySelector(
      `[data-testid="map-view"] path[data-id="${id}"]`,
    );
    expect(path).not.toBeNull();
    fireEvent.mouseDown(path as Element, {
      button: 0,
      clientX: 5,
      clientY: 5,
    });
    fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));
  }
  await user.click(screen.getByRole('button', { name: 'Готово' }));
}

/** Fills every required window-1 field with a valid value (overridable). */
export async function fillStep1(
  user: UserEvent,
  values: {
    name?: string;
    leaderName?: string;
    leaderTitle?: string;
    /** Province ids to select through the map picker. */
    provinceIds?: number[];
  } = {},
) {
  const {
    name = 'Testia',
    leaderName = 'Иван Грозный',
    leaderTitle = 'Верховный правитель',
    // 1003+1004: free and land-connected in MINI_MANIFEST.
    provinceIds = [1003, 1004],
  } = values;
  await user.type(screen.getByLabelText('Название государства'), name);
  await pickProvinces(user, provinceIds);
  await user.type(screen.getByLabelText('Имя лидера'), leaderName);
  await user.type(screen.getByLabelText('Должность лидера'), leaderTitle);
}

/** Switches to window 2 and fills the history link. */
export async function fillStep2(
  user: UserEvent,
  url = 'https://vk.com/@testia-istoriya',
) {
  await user.click(screen.getByTestId('step-next'));
  await user.type(
    screen.getByLabelText('Ссылка на историю государства'),
    url,
  );
}
