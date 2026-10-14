/**
 * PanelRegistry tests (jsdom; network via msw).
 *
 * Covered: sort+filter survive a tab switch and the view resets on
 * «Назад»; the in-flow filter panel under the toolbar (badge count,
 * text and range inputs filtering the rows); a failed reload keeps
 * the old rows with «Повторить»; the table block is the scroll
 * container with a sticky header whose titles never break inside a
 * word; tabs_position: right renders the vertical tab column.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import {
  createHashRouter,
  RouterProvider,
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
  registerRegistryHandlers,
  renderWithSession,
  TABLES,
} from './helpers';

function renderRegistry() {
  window.location.hash = '#/registry';
  const router = createHashRouter([
    { path: '/', panel: 'home', view: 'main' },
    { path: '/registry', panel: 'registry', view: 'main' },
  ]);
  return renderWithSession(
    <RouterProvider router={router}>
      <PanelRegistry />
    </RouterProvider>,
  );
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

  it('«Назад» resets sort, filters and search to the default view', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByText('Борис Иванов');

    await user.click(screen.getByTestId('sort-btn-player'));
    await user.type(
      screen.getByPlaceholderText('Поиск…'),
      'иван',
    );
    await waitFor(() => expect(rowKeys()).toEqual(['p1']));

    await user.click(screen.getByRole('button', { name: 'Назад' }));
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
});

describe('PanelRegistry — load states', () => {
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
