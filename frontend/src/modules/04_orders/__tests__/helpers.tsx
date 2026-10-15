/**
 * Shared helpers for 04_orders tests: a stateful harness that mirrors
 * the AppShell wiring (OrdersUiProvider + the single ModalRoot with
 * the three windows), a fake session, Spec-shaped fixtures and msw
 * handlers for /api/v1/orders/*.
 */

import { useState, type ReactElement, type ReactNode } from 'react';
import { render } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  ModalRoot,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../vitest.setup';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import {
  MODAL_ORDER_COMPOSER,
  MODAL_ORDER_CONFIRM,
  MODAL_ORDER_DETAIL,
  OrdersUiProvider,
} from '../OrdersUiProvider';
import { OrderComposer } from '../OrderComposer';
import { ConfirmSubmitModal } from '../ConfirmSubmitModal';
import { OrderDetailModal } from '../OrderDetailModal';
import type { OrderDetailDTO, OrderRulesDTO } from '../types';
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
      sortable: true, filters: ['text'], filter_label: null,
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

/**
 * The same wiring AppShell has: OrdersUiProvider drives the single
 * ModalRoot that hosts the three order windows.
 */
function OrdersHarness({ children }: { children?: ReactNode }) {
  const [activeModal, setActiveModal] = useState<string | null>(null);
  return (
    <OrdersUiProvider activeModal={activeModal} onActiveModal={setActiveModal}>
      {children}
      <ModalRoot
        activeModal={activeModal}
        onClose={() => setActiveModal(null)}
      >
        <OrderComposer id={MODAL_ORDER_COMPOSER} />
        <ConfirmSubmitModal id={MODAL_ORDER_CONFIRM} />
        <OrderDetailModal id={MODAL_ORDER_DETAIL} />
      </ModalRoot>
    </OrdersUiProvider>
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
