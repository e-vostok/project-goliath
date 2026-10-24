/**
 * Entry request with a preset (Spec 5.5 «Вход с предустановкой»).
 *
 * Covered: a `preset.nation` opens the «Приказы» tab with the nation
 * dropdown already set — the same value the player could pick by
 * hand — the counter shows it and the column gets its dot; a preset
 * never overrides a value the player picked earlier in the visit;
 * a preset nation with no rows shows «Ничего не найдено» and
 * «Сбросить»; a request stored while the panel is away is taken when
 * it becomes active (the in-app path of the «Штаб» badges).
 */

import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
  useActiveVkuiLocation,
} from '@vkontakte/vk-mini-apps-router';

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
import { PanelRegistry } from '../components/PanelRegistry';
import {
  setRegistryEntryRequest,
  takeRegistryEntryRequest,
  type RegistryEntryRequest,
} from '../lib/entryRequest';
import { clearTableFilterExtensions } from '../lib/tableFilterExtensions';
import type { RegistryRowsDTO, RegistryTableDTO } from '../types';
import {
  registerRegistryHandlers,
  renderWithSession,
  TABLES,
} from './helpers';

/** The «Приказы» table with a `select_or_contains` nation column —
 * the shape configs/03_registry.yaml describes. */
const ORDERS_TABLE: RegistryTableDTO = {
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
        nation: nationCell('Синдикат'),
        title: { text: 'Приказ о перебазировании', action: 'order:7' },
      },
    },
    {
      key: 'o3',
      cells: {
        number: 3,
        nation: nationCell('Автория'),
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

/** The nations table answer — the dropdown options must include the
 * order nations (Синдикат, Автория) plus one without orders (Рязань). */
const NATIONS_ROWS: RegistryRowsDTO = {
  table_id: 'nations',
  total: 4,
  truncated: false,
  generated_at: '2026-10-20T10:00:00Z',
  rows: [
    { key: 'n1', cells: { number: 1, name: 'Новгород', formed: { text: 'Январь 2041', key: 12 } } },
    { key: 'n2', cells: { number: 2, name: 'Рязань', formed: { text: 'Май 2043', key: 40 } } },
    { key: 'n3', cells: { number: 3, name: 'Синдикат', formed: { text: 'Июнь 2045', key: 60 } } },
    { key: 'n4', cells: { number: 4, name: 'Автория', formed: { text: 'Июль 2046', key: 70 } } },
  ],
};

function registerOrdersHandlers() {
  server.use(
    http.get('*/api/v1/registry/tables', () =>
      HttpResponse.json({
        ...TABLES,
        tables: [...TABLES.tables, ORDERS_TABLE],
      }),
    ),
    http.get('*/api/v1/registry/tables/orders', () =>
      HttpResponse.json(ORDERS_ROWS),
    ),
    http.get('*/api/v1/registry/tables/nations', () =>
      HttpResponse.json(NATIONS_ROWS),
    ),
  );
}

function RoutedRegistry({
  entryRequest = null,
}: {
  entryRequest?: RegistryEntryRequest | null;
}) {
  const { panel } = useActiveVkuiLocation();
  return (
    <PanelRegistry
      entryRequest={entryRequest}
      active={panel === 'registry'}
    />
  );
}

function renderRegistry(entryRequest: RegistryEntryRequest | null = null) {
  window.location.hash = '#/registry';
  const router = createHashRouter([
    { path: '/', panel: 'home', view: 'main' },
    { path: '/registry', panel: 'registry', view: 'main' },
  ]);
  const utils = renderWithSession(
    <RouterProvider router={router}>
      <RoutedRegistry entryRequest={entryRequest} />
    </RouterProvider>,
  );
  return { ...utils, router };
}

const rowKeys = () =>
  [...document.querySelectorAll('[data-row-key]')].map((el) =>
    el.getAttribute('data-row-key'),
  );

beforeEach(() => {
  registerRegistryHandlers();
  registerOrdersHandlers();
  clearTableFilterExtensions();
  takeRegistryEntryRequest(); // never leak a stored request
});

describe('entry request — preset { nation }', () => {
  it('opens the «Приказы» tab with the nation dropdown set, rows reduced and the counter at 1', async () => {
    renderRegistry({
      tab: 'orders',
      preset: { nation: 'Синдикат' },
    });

    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
    expect(
      screen.getByRole('tab', { name: 'Приказы' }),
    ).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByTestId('filters-count')).toHaveTextContent('1');

    const user = userEvent.setup();
    await user.click(screen.getByTestId('filters-toggle'));
    const item = await screen.findByTestId('filter-item-nation');
    expect(
      within(item).getByLabelText('Государство: Список'),
    ).toHaveValue('Синдикат');
    // the usual marker: the filtered column carries its dot
    expect(screen.getByTestId('filter-dot-nation')).toBeInTheDocument();
  });

  it('a preset nation with no orders shows «Ничего не найдено» and «Сбросить» restores the rows', async () => {
    const user = userEvent.setup();
    // Рязань is in the dropdown options (nations table) but has no orders.
    renderRegistry({ tab: 'orders', preset: { nation: 'Рязань' } });

    const nothingFound = await screen.findByText('Ничего не найдено');
    await user.click(
      within(nothingFound.parentElement as HTMLElement).getByRole(
        'button',
        { name: 'Сбросить' },
      ),
    );
    await waitFor(() =>
      expect(rowKeys()).toEqual(['o7', 'o3', 'o12']),
    );
    expect(screen.queryByTestId('filters-count')).not.toBeInTheDocument();
  });

  it('never overrides a nation the player picked earlier in the visit', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');

    await user.click(screen.getByRole('tab', { name: 'Приказы' }));
    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o3', 'o12']));

    await user.click(screen.getByTestId('filters-toggle'));
    const select = within(
      await screen.findByTestId('filter-item-nation'),
    ).getByLabelText('Государство: Список');
    await user.selectOptions(select, 'Автория');
    await waitFor(() => expect(rowKeys()).toEqual(['o3']));

    // A badge click while the panel is open — in-app handoff, no hash.
    act(() => {
      setRegistryEntryRequest({
        tab: 'orders',
        preset: { nation: 'Синдикат' },
      });
    });

    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Приказы' }),
      ).toHaveAttribute('aria-selected', 'true'),
    );
    // The player's own «Автория» choice stays.
    await waitFor(() => expect(rowKeys()).toEqual(['o3']));
    expect(select).toHaveValue('Автория');
  });

  it('a request stored while the panel is away applies when it becomes active', async () => {
    window.location.hash = '#/';
    const router = createHashRouter([
      { path: '/', panel: 'home', view: 'main' },
      { path: '/registry', panel: 'registry', view: 'main' },
    ]);
    renderWithSession(
      <RouterProvider router={router}>
        <RoutedRegistry />
      </RouterProvider>,
    );
    // The inactive panel does not read the store yet.
    act(() => {
      setRegistryEntryRequest({
        tab: 'orders',
        preset: { nation: 'Синдикат' },
      });
    });
    act(() => {
      void router.navigate('/registry');
    });

    await waitFor(() => expect(rowKeys()).toEqual(['o7', 'o12']));
    expect(await screen.findByTestId('filters-count')).toHaveTextContent('1');
  });
});
