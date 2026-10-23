/**
 * PanelRegistry tests (jsdom; network via msw).
 *
 * Covered: sort+filter survive a tab switch and the view resets when
 * the screen is left (Bible 2.7 — the `active` flag AppShell feeds);
 * the in-flow filter panel under the toolbar (badge count,
 * text and range inputs filtering the rows); a failed reload keeps
 * the old rows with «Повторить»; the table block is the scroll
 * container with a sticky header whose titles never break inside a
 * word; tabs_position: right renders the vertical tab column.
 */

import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
  useActiveVkuiLocation,
} from '@vkontakte/vk-mini-apps-router';

// RouterProvider pings VK Bridge on navigation; outside VK it would hit
// a real fetch — stub it (same pattern as 01_map tests).
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
  clearCellActions,
  registerCellAction,
} from '../lib/cellActions';
import type {
  RegistryRowsDTO,
  RegistryTableDTO,
} from '../types';
import {
  NATIONS_ROWS,
  registerRegistryHandlers,
  renderWithSession,
  TABLES,
} from './helpers';

/** Mirrors the AppShell wiring: the active flag follows the panel. */
function RoutedRegistry({
  entryRequest,
}: {
  entryRequest?: Parameters<typeof PanelRegistry>[0]['entryRequest'];
}) {
  const { panel } = useActiveVkuiLocation();
  return (
    <PanelRegistry
      entryRequest={entryRequest}
      active={panel === 'registry'}
    />
  );
}

function renderRegistry() {
  window.location.hash = '#/registry';
  const router = createHashRouter([
    { path: '/', panel: 'home', view: 'main' },
    { path: '/registry', panel: 'registry', view: 'main' },
  ]);
  const utils = renderWithSession(
    <RouterProvider router={router}>
      <RoutedRegistry />
    </RouterProvider>,
  );
  return { ...utils, router };
}

const rowKeys = () =>
  [...document.querySelectorAll('[data-row-key]')].map((el) =>
    el.getAttribute('data-row-key'),
  );

beforeEach(registerRegistryHandlers);

describe('PanelRegistry — view state', () => {
  it('keeps a sort and a filter set on «Игроки» after switching to «Государства» and back', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');

    // Sort by player name (asc) + text filter «смир» on the player column.
    await user.click(screen.getByTestId('sort-btn-player'));
    await waitFor(() => expect(rowKeys()).toEqual(['p2', 'p1', 'p3']));
    await user.click(screen.getByTestId('filters-toggle'));
    await user.type(
      within(await screen.findByTestId('filter-item-player')).getByPlaceholderText(
        'содержит…',
      ),
      'смир',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p2']));
    expect(screen.getByTestId('registry-counter')).toHaveTextContent(
      'Показано 1 из 3',
    );

    // Switch to «Государства» and back — rows refetch, view is kept.
    await user.click(screen.getByRole('tab', { name: 'Государства' }));
    await waitFor(() => expect(rowKeys()).toEqual(['n1', 'n2']));

    await user.click(screen.getByRole('tab', { name: 'Игроки' }));
    await waitFor(() => expect(rowKeys()).toEqual(['p2']));
    expect(screen.getByTestId('registry-counter')).toHaveTextContent(
      'Показано 1 из 3',
    );
  });

  it('leaving the screen resets sort, filters and search to the default view', async () => {
    const user = userEvent.setup();
    const { router } = renderRegistry();
    await screen.findByText('Борис Иванов');

    await user.click(screen.getByTestId('sort-btn-player'));
    await user.type(
      screen.getByPlaceholderText('Поиск…'),
      'иван',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p1']));

    // What the top bar's «Штаб» tab does: route away — the mounted
    // panel's `active` flag drops and the view state resets (Bible 2.7).
    act(() => {
      void router.navigate('/');
    });
    await waitFor(() => expect(window.location.hash).toBe('#/'));

    await waitFor(() => expect(rowKeys()).toEqual(['p1', 'p2', 'p3']));
    expect(
      screen.getByPlaceholderText('Поиск…'),
    ).toHaveValue('');
    expect(screen.getByTestId('registry-counter')).toHaveTextContent(
      'Показано 3 из 3',
    );
  });
});

describe('PanelRegistry — filter panel', () => {
  it('opens under the toolbar in normal flow and the badge counts active filters', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');

    await user.click(screen.getByTestId('filters-toggle'));
    const panel = await screen.findByTestId('registry-filter-panel');
    const toolbar = screen.getByTestId('registry-toolbar');
    // in-flow: sits right after the toolbar — no portal, no positioning
    expect(toolbar.nextElementSibling).toBe(panel);
    expect(panel.closest('[data-testid="panel-registry"]')).not.toBeNull();
    expect(['', 'static']).toContain(panel.style.position);

    await user.type(
      within(screen.getByTestId('filter-item-player')).getByPlaceholderText(
        'содержит…',
      ),
      'смир',
    );
    expect(
      await screen.findByTestId('filters-count'),
    ).toHaveTextContent('1');
  });

  it('filters rows by a text filter and a range filter entered in the panel', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');
    await user.click(screen.getByTestId('filters-toggle'));

    await user.type(
      within(screen.getByTestId('filter-item-player')).getByPlaceholderText(
        'содержит…',
      ),
      'смир',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p2']));

    await user.clear(
      within(screen.getByTestId('filter-item-player')).getByPlaceholderText(
        'содержит…',
      ),
    );
    await user.type(
      within(screen.getByTestId('filter-item-level')).getByLabelText(
        'Уровень: от',
      ),
      '2',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p2']));
  });

  it('marks a filtered column with a header dot and never breaks a title inside a word', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');

    const titleSpan = document.querySelector(
      'thead th button span',
    ) as HTMLElement;
    expect(titleSpan).not.toBeNull();
    expect(titleSpan.style.wordBreak).toBe('keep-all');
    expect(titleSpan.style.hyphens).toBe('none');
    expect(screen.queryByTestId('filter-dot-player')).toBeNull();

    await user.click(screen.getByTestId('filters-toggle'));
    await user.type(
      within(screen.getByTestId('filter-item-player')).getByPlaceholderText(
        'содержит…',
      ),
      'смир',
    );
    expect(
      await screen.findByTestId('filter-dot-player'),
    ).toBeInTheDocument();
  });

  it('nation column offers a dropdown of every known nation plus «содержит…» — either filters rows', async () => {
    // A nation the players table does not mention — the dropdown must
    // still list it (the source is the «nations» table, not the rows).
    server.use(
      http.get('*/api/v1/registry/tables/nations', () =>
        HttpResponse.json({
          ...NATIONS_ROWS,
          total: 3,
          rows: [
            ...NATIONS_ROWS.rows,
            {
              key: 'n3',
              cells: {
                number: 3,
                name: 'Северия',
                formed: { text: 'Август 2044', key: 55 },
              },
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');
    await user.click(screen.getByTestId('filters-toggle'));

    const item = await screen.findByTestId('filter-item-nation');
    const select = within(item).getByLabelText('Государство: Список');
    await waitFor(() =>
      expect(
        within(select)
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual(['Все', 'Новгород', 'Рязань', 'Северия']),
    );

    // Dropdown: exact nation match — only p3 (Рязань).
    await user.selectOptions(select, 'Рязань');
    await waitFor(() => expect(rowKeys()).toEqual(['p3']));

    // Back to «Все», then the free-text half still filters.
    await user.selectOptions(select, '');
    await waitFor(() => expect(rowKeys()).toEqual(['p1', 'p2', 'p3']));
    await user.type(
      within(item).getByPlaceholderText('содержит…'),
      'нов',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p1']));
  });
});

describe('PanelRegistry — load states', () => {
  it('a failed tables load shows the dictionary text, never the English detail', async () => {
    server.use(
      http.get('*/api/v1/registry/tables', () =>
        HttpResponse.json(
          { detail: 'Provider exploded upstream', code: 'REGISTRY_PROVIDER_FAILED' },
          { status: 500 },
        ),
      ),
    );
    renderRegistry();

    await screen.findByText('Не удалось загрузить таблицы реестра');
    expect(
      screen.getByText('Не удалось собрать таблицу. Попробуйте ещё раз позже.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Provider exploded/),
    ).not.toBeInTheDocument();
  });

  it('a failed reload keeps the old rows and shows «Повторить»', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');
    expect(rowKeys()).toHaveLength(3);

    server.use(
      http.get('*/api/v1/registry/tables/players', () =>
        HttpResponse.json(
          { detail: 'boom', code: 'REGISTRY_PROVIDER_FAILED' },
          { status: 500 },
        ),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Обновить' }));

    await screen.findByText('Не удалось загрузить таблицу');
    expect(
      screen.getByRole('button', { name: 'Повторить' }),
    ).toBeInTheDocument();
    // previously shown rows stay
    expect(rowKeys()).toEqual(['p1', 'p2', 'p3']);
  });

  it('scrolls inside the table block with a sticky header', async () => {
    renderRegistry();
    await screen.findByText('Борис Иванов');

    const block = screen.getByTestId('registry-table-block');
    expect(block.style.overflowY).toBe('auto');
    expect(block.style.flex).toContain('1');
    expect(block.style.minHeight).toBe('0');
    // The screen is as tall as its content — the table caps at 720 px
    // and scrolls inside (UI Spec 9.2).
    expect(block.style.maxHeight).toBe('720px');

    const headCell = document.querySelector(
      '[data-testid="registry-table"] thead th',
    ) as HTMLElement;
    expect(headCell).not.toBeNull();
    expect(headCell.style.position).toBe('sticky');
    expect(headCell.style.top).toBe('0px');
  });
});

describe('PanelRegistry — 910 px window rule (Spec 5.5)', () => {
  it('renders a fixed-layout table whose colgroup shares follow width_px, and the block never scrolls sideways', async () => {
    renderRegistry();
    await screen.findByText('Борис Иванов');

    const block = screen.getByTestId('registry-table-block');
    expect(block.style.overflowX).toBe('hidden');
    expect(block.style.overflowY).toBe('auto');

    const table = screen.getByTestId('registry-table');
    expect(table.style.tableLayout).toBe('fixed');
    expect(table.style.width).toBe('100%');

    const cols = [
      ...table.querySelectorAll<HTMLElement>('colgroup col'),
    ];
    const players = TABLES.tables[0].columns;
    const totalPx = players.reduce((s, c) => s + c.width_px, 0);
    const shares = cols.map((c) => parseFloat(c.style.width));
    expect(cols).toHaveLength(players.length);
    shares.forEach((share, i) => {
      expect(share).toBeCloseTo((players[i].width_px / totalPx) * 100, 6);
    });
    expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 6);
  });
});

describe('PanelRegistry — screen frame (UI Spec 9.2)', () => {
  it('shows the «РЕЕСТР» screen title with the three tab labels in the same row', async () => {
    server.use(
      http.get('*/api/v1/registry/tables', () =>
        HttpResponse.json({
          ...TABLES,
          tables: [
            ...TABLES.tables,
            {
              id: 'orders',
              title: 'Приказы',
              icon: 'orders',
              empty_text: 'Приказов пока нет',
              default_sort: { column: 'number', direction: 'desc' },
              columns: [],
            },
          ],
        }),
      ),
    );
    renderRegistry();
    await screen.findByText('Борис Иванов');

    // The shared screen title carries the signed tabs right after
    // «РЕЕСТР» — no separate tab row underneath (mockup «Registry»).
    const title = document.querySelector(
      '[data-testid="panel-registry"] h1',
    ) as HTMLElement;
    expect(title).not.toBeNull();
    expect(title).toHaveTextContent('Реестр');
    // PNG 09 — the segmented tabs sit in the same row as the title.
    const strip = title.parentElement!.querySelector(
      '[data-testid="registry-tabstrip"]',
    ) as HTMLElement;
    expect(strip).not.toBeNull();
    expect(
      within(strip).getAllByRole('tab').map((t) => t.textContent),
    ).toEqual(['Игроки', 'Государства', 'Приказы']);
  });

  it('the players table shows the «Дата регистрации» column title', async () => {
    renderRegistry();
    await screen.findByText('Борис Иванов');
    const head = document.querySelector(
      '[data-testid="registry-table"] thead',
    ) as HTMLElement;
    expect(
      within(head).getByText('Дата регистрации'),
    ).toBeInTheDocument();
  });
});

describe('PanelRegistry — tabs_position', () => {
  it('tabs_position: right renders the vertical tab column', async () => {
    server.use(
      http.get('*/api/v1/registry/tables', () =>
        HttpResponse.json({
          ...TABLES,
          layout: { tabs_position: 'right' },
        }),
      ),
    );
    renderRegistry();
    await screen.findByText('Борис Иванов');

    const strip = screen.getByTestId('registry-tabstrip');
    expect(strip).toHaveAttribute('data-orientation', 'vertical');
    expect(within(strip).getAllByRole('tab')).toHaveLength(2);
  });
});

describe('PanelRegistry — entry request (Spec 04_orders 5.5)', () => {
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
        id: 'title', title: 'Название', type: 'action_text',
        width_px: 236, sortable: true, filters: ['text'],
        filter_label: null, header_icon: null, searchable: true,
        stub: false, scale_min: null, scale_max: null,
      },
    ],
  };
  const ORDERS_ROWS: RegistryRowsDTO = {
    table_id: 'orders',
    total: 1,
    truncated: false,
    generated_at: '2026-10-15T10:00:00Z',
    rows: [
      {
        key: 'o7',
        cells: {
          number: 7,
          title: { text: 'Мобилизация', action: 'order:7' },
        },
      },
    ],
  };

  afterEach(clearCellActions);

  it('selects the requested tab and runs the action once its rows load', async () => {
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
    );
    const spy = vi.fn();
    registerCellAction('order', spy);

    window.location.hash = '#/registry';
    const router = createHashRouter([
      { path: '/', panel: 'home', view: 'main' },
      { path: '/registry', panel: 'registry', view: 'main' },
    ]);
    renderWithSession(
      <RouterProvider router={router}>
        <RoutedRegistry
          entryRequest={{ tab: 'orders', action: 'order:7' }}
        />
      </RouterProvider>,
    );

    // The «Приказы» tab becomes active…
    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Приказы' }),
      ).toHaveAttribute('aria-selected', 'true'),
    );
    // …and once its rows arrived the action ran like a cell click.
    await waitFor(() => expect(spy).toHaveBeenCalledWith('7'));
    await screen.findByText('Мобилизация');
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
