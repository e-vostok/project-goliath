/**
 * Shared helpers for 04_orders tests: a stateful harness that mirrors
 * the AppShell wiring (a root container + PopupHost + OrdersUiProvider,
 * which renders the five windows itself), a fake session, Spec-shaped
 * fixtures and msw handlers for /api/v1/orders/*.
 */

import { useRef, type ReactElement, type ReactNode } from 'react';
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
import { NoticeHost, PopupHost } from '../../../shared/ui';
import { OrdersUiProvider } from '../OrdersUiProvider';
import type {
  AssignedOrdersDTO,
  OrderDetailDTO,
  OrderRulesDTO,
} from '../types';
import type { RegistryRowsDTO, RegistryTableDTO } from '../../03_registry/types';

// jsdom's AbortSignal fails undici's brand check inside `new Request`
// (same reason api-client races aborts) — strip foreign signals (same
// as the 01_map / 03_registry helpers).
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

export const RULES: OrderRulesDTO = {
  title_min_length: 3,
  title_max_length: 100,
  summary_min_length: 10,
  summary_max_length: 500,
  url_max_length: 200,
  max_unresolved_orders: 5,
  unresolved_orders: 0,
};

export const ORDER: OrderDetailDTO = {
  number: 7,
  nation: { name: 'Автория', color: '#336699' },
  title: 'Приказ о перебазировании',
  summary: 'Перевести вторую армию к северной границе.',
  article_url: 'https://vk.com/@order-seven',
  distributed: false,
  verdict: null,
  overdue: false,
  can_write_verdict: false,
};

/** The judge's queue: one fresh order and one past its deadline. */
export const ASSIGNED: AssignedOrdersDTO = {
  items: [
    {
      number: 7,
      nation: { name: 'Автория', color: '#336699' },
      title: 'Приказ о перебазировании',
      summary: 'Перевести вторую армию к северной границе.',
      article_url: 'https://vk.com/@order-seven',
      deadline_text: '18.10.2026 21:21',
      overdue: false,
    },
    {
      number: 3,
      nation: { name: 'Северия', color: '#993366' },
      title: 'Очень длинное название приказа, которое не влезает в строку',
      summary: 'Сводить гарнизоны.',
      article_url: 'https://vk.com/@order-three',
      deadline_text: '14.10.2026 09:00',
      overdue: true,
    },
  ],
};

/** The Registry's orders table as Spec Appendix D describes it. */
export const ORDERS_TABLE: RegistryTableDTO = {
  id: 'orders',
  title: 'Приказы',
  icon: 'orders',
  empty_text: 'Приказов пока нет',
  default_sort: { column: 'number', direction: 'desc' },
  columns: [
    {
      id: 'number', title: '№', type: 'index', width_px: 56,
      sortable: true, filters: [], filter_label: null,
      header_icon: null, searchable: false, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'nation', title: 'Государство', type: 'nation', width_px: 168,
      sortable: true, filters: ['select_or_contains'], filter_label: null,
      header_icon: null, searchable: true, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'title', title: 'Название', type: 'action_text', width_px: 236,
      sortable: true, filters: ['text'], filter_label: null,
      header_icon: null, searchable: true, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'submitted', title: 'Подача', type: 'datetime', width_px: 136,
      sortable: true, filters: ['date_range'], filter_label: null,
      header_icon: 'stage_submitted', searchable: false, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'distributed', title: 'Распределение', type: 'datetime',
      width_px: 136, sortable: true, filters: ['date_range', 'presence'],
      filter_label: null, header_icon: 'stage_distributed',
      searchable: false, stub: false, scale_min: null, scale_max: null,
    },
    {
      id: 'verdict', title: 'Вердикт', type: 'datetime', width_px: 136,
      sortable: true, filters: ['date_range', 'presence'],
      filter_label: null, header_icon: 'stage_verdict',
      searchable: false, stub: false, scale_min: null, scale_max: null,
    },
  ],
};

export const ORDERS_ROWS: RegistryRowsDTO = {
  table_id: 'orders',
  total: 1,
  truncated: false,
  generated_at: '2026-10-16T10:00:00Z',
  rows: [
    {
      key: 'o7',
      cells: {
        number: 7,
        nation: { name: 'Автория', color: '#336699', flag_url: null },
        title: {
          text: 'Приказ о перебазировании',
          action: 'order:7',
        },
        submitted: {
          date: '16.10.2026',
          time: '12:00',
          key: 1760616000,
          day: 20751,
          mark: null,
        },
        distributed: {
          date: null,
          time: null,
          key: null,
          day: null,
          mark: null,
        },
        verdict: {
          date: null,
          time: null,
          key: null,
          day: null,
          mark: null,
        },
      },
    },
  ],
};

export function registerRulesHandler(rules: OrderRulesDTO = RULES) {
  server.use(
    http.get('*/api/v1/orders/rules', () => HttpResponse.json(rules)),
  );
}

export function registerOrderDetailHandler(
  order: OrderDetailDTO = ORDER,
) {
  server.use(
    http.get(`*/api/v1/orders/${order.number}`, () =>
      HttpResponse.json(order),
    ),
  );
}

export function registerAssignedHandler(
  assigned: AssignedOrdersDTO = ASSIGNED,
) {
  server.use(
    http.get('*/api/v1/orders/assigned', () =>
      HttpResponse.json(assigned),
    ),
  );
}

/**
 * The same wiring AppShell has: a relative root container, PopupHost
 * and the provider that renders the five windows as shared Popups.
 */
function OrdersHarness({ children }: { children?: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <PopupHost container={containerRef}>
        <NoticeHost container={containerRef}>
          <OrdersUiProvider>{children}</OrdersUiProvider>
        </NoticeHost>
      </PopupHost>
    </div>
  );
}

export function renderWithOrders(ui: ReactElement) {
  return render(
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <SessionProvider session={SESSION}>
            <OrdersHarness>{ui}</OrdersHarness>
          </SessionProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>,
  );
}
