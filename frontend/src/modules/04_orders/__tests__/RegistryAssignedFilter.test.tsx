/**
 * «Назначены мне» — the table filter extension 04_orders registers on
 * the Registry's «Приказы» tab (Spec 5.6, Spec 03_registry 5.5).
 *
 * Covered: a `{tab: 'orders', preset: {assignedToMe: true}}` entry
 * request leaves only the rows whose `o<N>` numbers are in the
 * `GET /orders/assigned` answer and counts as one filter; «Сбросить»
 * clears it and «Обновить» reloads the set; a failed load shows the
 * usual error text in the control and keeps every row; by hand the
 * control never fetches before the first «Да». The rows request gains
 * no parameters and no extra calls — the filter is evaluated in the
 * browser from data the caller already owns (no judge leak, INV-O5).
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
} from '@vkontakte/vk-mini-apps-router';
import { useState } from 'react';

import { server } from '../../../../vitest.setup';
import { PanelRegistry } from '../../03_registry/components/PanelRegistry';
import type { RegistryEntryRequest } from '../../03_registry/lib/entryRequest';
import { clearTableFilterExtensions } from '../../03_registry/lib/tableFilterExtensions';
import type {
  RegistryRowsDTO,
  RegistryTableDTO,
} from '../../03_registry/types';
import {
  ASSIGNED,
  ORDERS_TABLE,
  renderWithOrders,
} from './helpers';

vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

/** The nations table — the dropdown options the nation column needs. */
const NATIONS_TABLE: RegistryTableDTO = {
  id: 'nations',
  title: 'Государства',
  icon: 'nations',
  empty_text: 'Государств пока нет',
  default_sort: { column: 'number', direction: 'asc' },
  columns: [
    {
      id: 'number', title: '№', type: 'index', width_px: 48,
      sortable: true, filters: [], filter_label: null,
      header_icon: null, searchable: false, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'name', title: 'Название', type: 'text', width_px: 430,
      sortable: true, filters: ['text'], filter_label: null,
      header_icon: null, searchable: true, stub: false,
      scale_min: null, scale_max: null,
    },
  ],
};

const NATIONS_ROWS: RegistryRowsDTO = {
  table_id: 'nations',
  total: 2,
  truncated: false,
  generated_at: '2026-10-20T10:00:00Z',
  rows: [
    { key: 'n1', cells: { number: 1, name: 'Синдикат' } },
    { key: 'n2', cells: { number: 2, name: 'Автория' } },
  ],
};

const nationCell = (name: string) => ({
  id: null,
  name,
  color: '#336699',
  flag_url: null,
});

const ORDERS_ROWS: RegistryRowsDTO = {
  table_id: 'orders',
  total: 3,
  truncated: false,
  generated_at: '2026-10-20T10:00:00Z',
  rows: [
    {
      key: 'o7',
      cells: {
        number: 7,
        nation: nationCell('Автория'),
        title: { text: 'Приказ о перебазировании', action: 'order:7' },
      },
    },
    {
      key: 'o3',
      cells: {
        number: 3,
        nation: nationCell('Северия'),
        title: { text: 'О размещении гарнизона', action: 'order:3' },
      },
    },
    {
      key: 'o12',
      cells: {
        number: 12,
        nation: nationCell('Синдикат'),
        title: { text: 'О торговом договоре', action: 'order:12' },
      },
    },
  ],
};

/** The judge's queue: orders 7 and 12 are assigned to the caller. */
const ASSIGNED_7_12 = {
  items: [
    { ...ASSIGNED.items[0], number: 7 },
    { ...ASSIGNED.items[1], number: 12 },
  ],
};

let assignedCalls = 0;
let rowsCalls = 0;
let rowsUrls: string[] = [];

function registerHandlers() {
  assignedCalls = 0;
  rowsCalls = 0;
  rowsUrls = [];
  server.use(
    http.get('*/api/v1/registry/tables', () =>
      HttpResponse.json({
        layout: { tabs_position: 'top' },
        tables: [ORDERS_TABLE, NATIONS_TABLE],
      }),
    ),
    http.get('*/api/v1/registry/tables/orders', ({ request }) => {
      rowsCalls += 1;
      rowsUrls.push(request.url);
      return HttpResponse.json(ORDERS_ROWS);
    }),
    http.get('*/api/v1/registry/tables/nations', () =>
      HttpResponse.json(NATIONS_ROWS),
    ),
    http.get('*/api/v1/orders/assigned', () => {
      assignedCalls += 1;
      return HttpResponse.json(ASSIGNED_7_12);
    }),
  );
}

/** PanelRegistry needs the hash router; the harness mounts
 * OrdersUiProvider, which registers the extension. */
function RegistryWithRouter({
  entryRequest = null,
}: {
  entryRequest?: RegistryEntryRequest | null;
}) {
  const [router] = useState(() =>
    createHashRouter([{ path: '/', panel: 'registry', view: 'main' }]),
  );
  return (
    <RouterProvider router={router}>
      <PanelRegistry entryRequest={entryRequest} />
    </RouterProvider>
  );
}

const rowKeys = () =>
  [...document.querySelectorAll('[data-row-key]')].map((el) =>
    el.getAttribute('data-row-key'),
  );

const extGroup = () => screen.getByTestId('filter-ext-assigned_to_me');

beforeEach(registerHandlers);
afterEach(clearTableFilterExtensions);

describe('«Назначены мне» — preset { assignedToMe }', () => {
  it('keeps only the judge-queue rows, counts as one filter and adds nothing to the rows request', async () => {
    renderWithOrders(
      <RegistryWithRouter
        entryRequest={{ tab: 'orders', preset: { assignedToMe: true } }}
      />,
    );

    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
    expect(assignedCalls).toBe(1);
    expect(await screen.findByTestId('filters-count')).toHaveTextContent('1');

    // INV-R10 / no judge leak: the rows request is exactly what every
    // player gets — one call, no new query parameters.
    expect(rowsCalls).toBe(1);
    expect(
      rowsUrls.map((u) => new URL(u).search),
    ).toEqual(['']);
  });

  it('«Сбросить» clears the filter and «Обновить» reloads the set', async () => {
    const user = userEvent.setup();
    renderWithOrders(
      <RegistryWithRouter
        entryRequest={{ tab: 'orders', preset: { assignedToMe: true } }}
      />,
    );

    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));

    await user.click(screen.getByTestId('filters-toggle'));
    const item = extGroup();
    expect(
      within(item).getByRole('radio', { name: 'Да' }),
    ).toBeChecked();

    await user.click(screen.getByRole('button', { name: 'Сбросить' }));
    await waitFor(() =>
      expect(rowKeys()).toEqual(['o7', 'o3', 'o12']),
    );
    expect(
      within(extGroup()).getByRole('radio', { name: 'Все' }),
    ).toBeChecked();
    expect(screen.queryByTestId('filters-count')).not.toBeInTheDocument();

    // «Да» again — the set is already loaded, no refetch; «Обновить»
    // reloads it together with the rows.
    await user.click(
      within(extGroup()).getByRole('radio', { name: 'Да' }),
    );
    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
    expect(assignedCalls).toBe(1);

    await user.click(screen.getByRole('button', { name: 'Обновить' }));
    await waitFor(() => expect(assignedCalls).toBe(2));
    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
  });

  it('a failing /orders/assigned shows the usual error text in the control and keeps all rows', async () => {
    server.use(
      http.get('*/api/v1/orders/assigned', () => {
        assignedCalls += 1;
        return HttpResponse.json(
          { detail: 'boom', code: 'ORDERS_ASSIGNED_FAILED' },
          { status: 500 },
        );
      }),
    );
    renderWithOrders(
      <RegistryWithRouter
        entryRequest={{ tab: 'orders', preset: { assignedToMe: true } }}
      />,
    );

    await screen.findByText('Приказ о перебазировании');
    await waitFor(() => expect(assignedCalls).toBe(1));

    const user = userEvent.setup();
    await user.click(screen.getByTestId('filters-toggle'));
    const item = await extGroup();
    await within(item).findByTestId('filter-ext-error-assigned_to_me');
    expect(
      within(item).getByTestId('filter-ext-error-assigned_to_me'),
    ).toHaveTextContent('Ошибка сервера — попробуйте ещё раз позже.');
    // The failed filter is off — every row stays on screen.
    expect(rowKeys()).toEqual(['o7', 'o3', 'o12']);
    expect(
      within(item).getByRole('radio', { name: 'Все' }),
    ).toBeChecked();
    expect(screen.queryByTestId('filters-count')).not.toBeInTheDocument();
  });
});

describe('«Назначены мне» — the control by hand', () => {
  it('never calls /orders/assigned before the first «Да» and toggles «Все» ↔ «Да»', async () => {
    const user = userEvent.setup();
    renderWithOrders(<RegistryWithRouter />);

    await screen.findByText('Приказ о перебазировании');
    await waitFor(() =>
      expect(rowKeys()).toEqual(['o7', 'o3', 'o12']),
    );
    expect(assignedCalls).toBe(0);

    await user.click(screen.getByTestId('filters-toggle'));
    const item = await extGroup();
    expect(
      within(item).getByRole('radio', { name: 'Все' }),
    ).toBeChecked();
    expect(assignedCalls).toBe(0);

    await user.click(within(item).getByRole('radio', { name: 'Да' }));
    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
    expect(assignedCalls).toBe(1);

    await user.click(within(item).getByRole('radio', { name: 'Все' }));
    await waitFor(() =>
      expect(rowKeys()).toEqual(['o7', 'o3', 'o12']),
    );
    expect(assignedCalls).toBe(1);
  });
});
