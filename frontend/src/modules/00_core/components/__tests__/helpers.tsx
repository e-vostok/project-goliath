/**
 * Shared helpers for 00_core component tests: the provider wrapper, a fake
 * session, default msw handlers and wizard-filling utilities.
 *
 * The default rules body deliberately uses NON-backend-config numbers so
 * that a limit hardcoded in a component (instead of read from
 * GET /nations/rules) fails these tests.
 */

import type { ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
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
 * Call in beforeEach — registers every GET the 00_core panels fire on
 * mount (unhandled requests are a test failure).
 */
export function registerDefaultHandlers() {
  server.use(
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.get('*/api/v1/provinces', () => HttpResponse.json(FREE_PROVINCES)),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(GAME_CLOCK)),
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

/** Fills every required window-1 field with a valid value (overridable). */
export async function fillStep1(
  user: UserEvent,
  values: {
    name?: string;
    leaderName?: string;
    leaderTitle?: string;
    provinceId?: string;
  } = {},
) {
  const {
    name = 'Testia',
    leaderName = 'Иван Грозный',
    leaderTitle = 'Верховный правитель',
    provinceId = '1',
  } = values;
  await user.type(screen.getByLabelText('Название государства'), name);
  await user.type(
    screen.getByPlaceholderText('Введите ID провинции и нажмите Enter'),
    `${provinceId}{Enter}`,
  );
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
