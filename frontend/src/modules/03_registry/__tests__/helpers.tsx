/**
 * Shared helpers for 03_registry tests: provider wrapper, Spec-shaped
 * fixtures and msw handlers for /api/v1/registry/*.
 */

import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../vitest.setup';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import type {
  RegistryRowsDTO,
  RegistryTablesDTO,
} from '../types';

// jsdom's AbortSignal fails undici's brand check inside `new Request`
// (same reason api-client races aborts); the router builds Requests on
// every navigation — strip foreign signals (same as 01_map helpers).
const UndiciRequest = Request;
vi.stubGlobal(
  'Request',
  class extends UndiciRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      const { signal: _dropped, ...rest } = init ?? {};
      super(input, init === undefined ? undefined : rest);
    }
  },
);

export const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 123456,
    created_at: '2026-09-01T12:00:00Z',
  },
};

export const TABLES: RegistryTablesDTO = {
  layout: { tabs_position: 'top' },
  tables: [
    {
      id: 'players',
      title: 'Игроки',
      icon: 'players',
      empty_text: 'Игроков пока нет',
      default_sort: { column: 'number', direction: 'asc' },
      columns: [
        {
          id: 'number', title: '№', type: 'index', width_px: 48,
          sortable: true, filters: [], filter_label: null,
          header_icon: null,
          searchable: false, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'player', title: 'Игрок', type: 'person', width_px: 190,
          sortable: true, filters: ['text'], filter_label: null,
          header_icon: null,
          searchable: true, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'joined', title: 'Дата регистрации', type: 'date', width_px: 136,
          sortable: true, filters: ['date_range'], filter_label: null,
          header_icon: null,
          searchable: false, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'level', title: 'Уровень', type: 'integer', width_px: 92,
          sortable: true, filters: ['number_range'], filter_label: null,
          header_icon: null,
          searchable: false, stub: true, scale_min: null, scale_max: null,
        },
        {
          id: 'judge_rating', title: 'Рейтинг', type: 'gauge',
          width_px: 112, sortable: true, filters: ['number_range'],
          filter_label: null, header_icon: null,
          searchable: false, stub: true, scale_min: -100, scale_max: 100,
        },
        {
          id: 'nation', title: 'Государство', type: 'nation', width_px: 292,
          sortable: true,
          filters: ['select_or_contains', 'presence'], filter_label: null,
          header_icon: null,
          searchable: true, stub: false, scale_min: null, scale_max: null,
        },
      ],
    },
    {
      id: 'nations',
      title: 'Государства',
      icon: 'nations',
      empty_text: 'Государств пока нет',
      default_sort: { column: 'number', direction: 'asc' },
      columns: [
        {
          id: 'number', title: '№', type: 'index', width_px: 48,
          sortable: true, filters: [], filter_label: null,
          header_icon: null,
          searchable: false, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'name', title: 'Название', type: 'text', width_px: 430,
          sortable: true, filters: ['text'], filter_label: null,
          header_icon: null,
          searchable: true, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'formed', title: 'Дата формирования', type: 'date',
          width_px: 176, sortable: true, filters: ['number_range'],
          filter_label: 'Ход',
          header_icon: null,
          searchable: false, stub: false, scale_min: null, scale_max: null,
        },
        {
          id: 'provinces', title: 'Провинции', type: 'integer',
          width_px: 112, sortable: true, filters: ['number_range'],
          filter_label: null, header_icon: null,
          searchable: false, stub: false, scale_min: null, scale_max: null,
        },
      ],
    },
  ],
};

export const PLAYERS_ROWS: RegistryRowsDTO = {
  table_id: 'players',
  total: 3,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    {
      key: 'p1',
      cells: {
        number: 1,
        player: { name: 'Борис Иванов', avatar_url: null, is_fallback: false },
        joined: { text: '01.09.2026', key: 20697 },
        level: 1,
        judge_rating: 5,
        nation: {
          id: 'n1',
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
        player: {
          name: 'Анна Смирнова',
          avatar_url: 'https://pp.vk.me/avatar.png',
          is_fallback: false,
        },
        joined: { text: '05.09.2026', key: 20701 },
        level: 2,
        judge_rating: 0,
        nation: null,
      },
    },
    {
      key: 'p3',
      cells: {
        number: 3,
        player: { name: 'Игрок №3', avatar_url: null, is_fallback: true },
        joined: { text: '10.09.2026', key: 20706 },
        level: 1,
        judge_rating: -20,
        nation: {
          id: 'n2',
          name: 'Рязань',
          color: '#2980B9',
          flag_url: null,
        },
      },
    },
  ],
};

export const NATIONS_ROWS: RegistryRowsDTO = {
  table_id: 'nations',
  total: 2,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    {
      key: 'n1',
      cells: {
        number: 1,
        name: 'Новгород',
        formed: { text: 'Январь 2041', key: 12 },
        provinces: 5,
      },
    },
    {
      key: 'n2',
      cells: {
        number: 2,
        name: 'Рязань',
        formed: { text: 'Май 2043', key: 40 },
        provinces: 3,
      },
    },
  ],
};

export function registerRegistryHandlers() {
  server.use(
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

export function renderWithSession(ui: ReactElement) {
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
