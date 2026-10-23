/**
 * Shared helpers for 00_core component tests: the provider wrapper, a fake
 * session, default msw handlers and wizard-filling utilities.
 *
 * The default rules body deliberately uses NON-backend-config numbers so
 * that a limit hardcoded in a component (instead of read from
 * GET /nations/rules) fails these tests.
 */

import { useRef, type ReactElement, type ReactNode } from 'react';
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
import type { OrderRulesDTO } from '../../../04_orders/types';
import { writeFormDraft } from '../../../../shared/formDraft';
import {
  REGISTRATION_DRAFT_KEY,
  type ChipOption,
  type RegistrationForm,
  type RegistrationTab,
} from '../registrationForm';
import { SessionProvider } from '../../hooks/useAuth';
import { OrdersUiProvider } from '../../../04_orders/OrdersUiProvider';
import { NoticeHost, PopupHost } from '../../../../shared/ui';
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
  short_name_min_length: 3,
  short_name_max_length: 15,
  motto_max_length: 55,
  description_max_length: 111,
  leader_name_min_length: 2,
  leader_name_max_length: 33,
  leader_title_min_length: 3,
  leader_title_max_length: 44,
  leader_bio_max_length: 444,
  capital_name_min_length: 2,
  capital_name_max_length: 22,
  history_url_max_length: 321,
  history_url_allowed_hosts: ['vk.com', 'm.vk.com'],
  anthem_url_max_length: 222,
  anthem_url_allowed_hosts: ['vk.com', 'm.vk.com'],
  min_provinces: 3,
  max_provinces: 3,
  palette: ['#102030', '#a0b0c0'],
  flags: [{ id: 'flag_stub', url: '/assets/nations/flags/flag_stub.png' }],
  portraits: [
    { id: 'portrait_stub', url: '/assets/nations/portraits/portrait_stub.png' },
  ],
  genders: ['male', 'female'],
  succession_types: ['elections', 'appointment', 'criteria', 'inheritance'],
};

export const FREE_PROVINCES = [
  { id: 1, nation_id: null },
  { id: 2, nation_id: null },
];

export const GAME_CLOCK = {
  current_turn: 12,
  game_date: '2041-01-01',
  game_date_text: 'Январь 2041',
  next_tick_at: '2026-10-02T03:00:00Z',
};

/**
 * Order limits for the «Мои приказы» badge and the composer's counter —
 * deliberately NOT the real config numbers: a hardcoded limit fails
 * tests.
 */
export const ORDER_RULES: OrderRulesDTO = {
  title_min_length: 4,
  title_max_length: 77,
  summary_min_length: 9,
  summary_max_length: 444,
  url_max_length: 188,
  max_unresolved_orders: 7,
  unresolved_orders: 2,
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
 * mount (unhandled requests are a test failure), the POST the tab-1
 * color-check hint fires after its debounce, plus the 01_map endpoints
 * the ProvincePicker needs when it opens from window 1.
 */
export function registerDefaultHandlers() {
  resetMswMap();
  clearMapSessionCache();
  server.use(
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.post('*/api/v1/nations/color-check', () =>
      HttpResponse.json({ status: 'OK' }),
    ),
    http.get('*/api/v1/provinces', () => HttpResponse.json(FREE_PROVINCES)),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(GAME_CLOCK)),
    http.get('*/api/v1/orders/rules', () => HttpResponse.json(ORDER_RULES)),
    http.get('*/api/v1/orders/assigned', () =>
      HttpResponse.json({ items: [] }),
    ),
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

/**
 * The same wiring AppShell has: a relative root container plus the
 * PopupHost the shared windows (order windows, the province picker)
 * portal into.
 */
function PopupHarness({ children }: { children?: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <PopupHost container={containerRef}>
        {/* PanelNationHome hosts the orders block — the provider
            must exist; these tests never open its windows. NoticeHost
            feeds the shared «done» bar. */}
        <NoticeHost container={containerRef}>
          <OrdersUiProvider>{children}</OrdersUiProvider>
        </NoticeHost>
      </PopupHost>
    </div>
  );
}

export function renderWithProviders(ui: ReactElement) {
  return render(
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <SessionProvider session={SESSION}>
            <PopupHarness>{ui}</PopupHarness>
          </SessionProvider>
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

/** Three chips — exactly RULES.max_provinces, so a seeded form submits. */
const SEEDED_PROVINCES: ChipOption[] = [1005, 1006, 1007].map((id) => ({
  value: id,
  label: `Провинция ${id}`,
}));

/**
 * A RegistrationForm with every required field filled (the optional
 * texts stay empty, flag and portrait get the stub catalog ids — both
 * are mandatory on create since 0.9.0, no capital mark — the server
 * defaults the capital to the first province). The UI cannot reach some
 * fields until Issues 13–15, so tests that need an enabled submit seed
 * this through the v2 draft.
 */
export function completeRegistrationForm(
  overrides: Partial<RegistrationForm> = {},
): RegistrationForm {
  return {
    name: 'Testia',
    shortName: 'Тестия',
    color: '#e64545',
    motto: '',
    description: '',
    flagId: 'flag_stub',
    leaderName: 'Иван Грозный',
    gender: 'male',
    leaderTitle: 'Верховный правитель',
    leaderBio: '',
    portraitId: 'portrait_stub',
    successionType: 'elections',
    historyUrl: 'https://vk.com/@testia-istoriya',
    provinces: SEEDED_PROVINCES.map((chip) => ({ ...chip })),
    capitalProvinceId: null,
    capitalName: 'Столицево',
    capitalNameEdited: false,
    ...overrides,
  };
}

/** Seeds the v2 session draft BEFORE the panel renders (read on mount). */
export function seedRegistrationDraft(
  overrides: Partial<RegistrationForm> = {},
): void {
  writeFormDraft(REGISTRATION_DRAFT_KEY, completeRegistrationForm(overrides));
}

/** Jumps to a registration tab through its clickable title. */
export async function goToTab(user: UserEvent, tab: RegistrationTab) {
  await user.click(screen.getByTestId(`step-title-${tab}`));
}

/**
 * Picks provinces through the real ProvincePicker modal on tab 4: opens
 * it, waits for the map, clicks each id's <path>, presses «Готово».
 * Map clicks use the delegated handler contract: mousedown on the path
 * + mouseup on window (a settled click, not a drag).
 */
export async function pickProvinces(user: UserEvent, ids: number[]) {
  await goToTab(user, 4);
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

/** Fills the one tab-3 field — the history link. */
export async function fillTab3(
  user: UserEvent,
  url = 'https://vk.com/@testia-istoriya',
) {
  await goToTab(user, 3);
  await user.type(
    screen.getByLabelText('Ссылка на статью с историей государства'),
    url,
  );
}
