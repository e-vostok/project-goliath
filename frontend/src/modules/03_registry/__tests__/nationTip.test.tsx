/**
 * «Подсказка» first uses (version 0.9.0 unit 11): the nation tooltip
 * on `nation` cells and on the nations-table «name» cell (the public
 * card via GET /nations/{id}, a 60 s session cache) and the player
 * tooltip on `person` cells (row data only — NO request at all).
 * A cell with `id: null` gets no tip, and the tip never blocks the
 * click that opens the subscreen.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactElement } from 'react';

import { server } from '../../../../vitest.setup';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import { TOOLTIP_DELAY_MS } from '../../../shared/ui';
import type { NationPublicDTO } from '../../../shared/types';
import { clearNationTipCache } from '../lib/nationTipCache';
import { EMPTY_VIEW } from '../lib/tableView';
import { RegistryTable } from '../components/RegistryTable';
import { NationCell } from '../components/cells/NationCell';
import { PersonCell } from '../components/cells/PersonCell';
import type {
  RegistryCell,
  RegistryRowDTO,
  RegistryTableDTO,
} from '../types';
import { SESSION } from './helpers';

// jsdom has no PointerEvent — MouseEvent carries clientX/Y and
// relatedTarget, everything the pointer handlers under test read.
if (window.PointerEvent === undefined) {
  vi.stubGlobal('PointerEvent', window.MouseEvent);
}

const NATION_ID = 'n1';

const NATION: NationPublicDTO = {
  id: NATION_ID,
  created_at: '2026-09-01T12:00:00Z',
  name: 'Новгородская республика',
  short_name: 'НВГ',
  color_hex: '#C0392B',
  motto: null,
  description: null,
  flag_id: null,
  flag_url: null,
  province_ids: [1001, 1002, 1003],
  capital_province_id: 1001,
  capital_name: 'Новгород-град',
  leader_name: 'Борис Первый',
  leader_title: null,
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  history_url: null,
  level: 3,
  judge_rating: 12,
};

const NATION_CELL: RegistryCell = {
  id: NATION_ID,
  name: 'Новгород',
  color: '#C0392B',
  flag_url: null,
};

const PLAYER_CELLS: Record<string, RegistryCell> = {
  player: { name: 'Борис Иванов', avatar_url: null, is_fallback: false },
  joined: { text: '1 сентября 2026', key: 20697 },
  level: 2,
  judge_rating: 12,
  nation: NATION_CELL,
};

const NATIONS_TABLE: RegistryTableDTO = {
  id: 'nations',
  title: 'Государства',
  icon: 'nations',
  empty_text: 'Государств пока нет',
  default_sort: { column: 'number', direction: 'asc' },
  columns: [
    {
      id: 'number',
      title: '№',
      type: 'index',
      width_px: 48,
      sortable: true,
      filters: [],
      filter_label: null,
      header_icon: null,
      searchable: false,
      stub: false,
      scale_min: null,
      scale_max: null,
    },
    {
      id: 'name',
      title: 'Название',
      type: 'text',
      width_px: 430,
      sortable: true,
      filters: ['text'],
      filter_label: null,
      header_icon: null,
      searchable: true,
      stub: false,
      scale_min: null,
      scale_max: null,
    },
  ],
};

const NATIONS_ROWS: RegistryRowDTO[] = [
  { key: NATION_ID, cells: { number: 1, name: 'Новгород' } },
];

let nationCalls = 0;

function registerNation(status = 200) {
  server.use(
    http.get(`*/api/v1/nations/${NATION_ID}`, () => {
      nationCalls += 1;
      return status === 200
        ? HttpResponse.json(NATION)
        : HttpResponse.json(
            { detail: 'boom', code: 'INTERNAL' },
            { status },
          );
    }),
  );
}

function renderInRoot(ui: ReactElement) {
  return render(
    <SessionProvider session={SESSION}>
      <div data-testid="app-root" style={{ position: 'relative' }}>
        {ui}
      </div>
    </SessionProvider>,
  );
}

const tip = () => screen.queryByRole('tooltip');

function openTip(target: HTMLElement) {
  fireEvent.pointerOver(target, { clientX: 20, clientY: 20 });
  act(() => {
    vi.advanceTimersByTime(TOOLTIP_DELAY_MS);
  });
}

function leaveTip(target: HTMLElement) {
  fireEvent.pointerOut(target, { relatedTarget: document.body });
}

beforeEach(() => {
  nationCalls = 0;
  clearNationTipCache();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('NationCell — nation «Подсказка»', () => {
  it('shows leader, province count, capital and the «Нажмите…» line', async () => {
    vi.useFakeTimers();
    registerNation();
    renderInRoot(<NationCell value={NATION_CELL} onOpen={() => {}} />);

    openTip(screen.getByRole('button', { name: 'Новгород' }));
    vi.useRealTimers();

    const box = tip()!;
    expect(within(box).getByText('Загрузка…')).toBeInTheDocument();
    await within(box).findByText('Борис Первый');
    expect(within(box).getByText('Лидер')).toBeInTheDocument();
    expect(within(box).getByText('Провинций')).toBeInTheDocument();
    expect(within(box).getByText('3')).toBeInTheDocument();
    expect(within(box).getByText('Новгород-град')).toBeInTheDocument();
    // Unit 6a: the heading is the SHORT name — the loaded card's full
    // «Новгородская республика» never replaces it.
    expect(within(box).getByText('НВГ')).toBeInTheDocument();
    expect(
      within(box).queryByText('Новгородская республика'),
    ).not.toBeInTheDocument();
    expect(
      within(box).getByText('Нажмите на название, чтобы открыть государство'),
    ).toBeInTheDocument();
    expect(nationCalls).toBe(1);
  });

  it('serves a second hover within 60 s from the cache — one request', async () => {
    vi.useFakeTimers();
    registerNation();
    renderInRoot(<NationCell value={NATION_CELL} onOpen={() => {}} />);
    const cell = screen.getByRole('button', { name: 'Новгород' });

    openTip(cell);
    vi.useRealTimers();
    await within(tip()!).findByText('Борис Первый');
    expect(nationCalls).toBe(1);

    leaveTip(cell);
    vi.useFakeTimers();
    openTip(cell);
    vi.useRealTimers();
    await within(tip()!).findByText('Борис Первый');
    // The second open hit the 60 s in-memory cache — still one call.
    expect(nationCalls).toBe(1);
  });

  it('a failed request shows «Не удалось загрузить» and is retried on the next hover', async () => {
    vi.useFakeTimers();
    registerNation(500);
    renderInRoot(<NationCell value={NATION_CELL} onOpen={() => {}} />);
    const cell = screen.getByRole('button', { name: 'Новгород' });

    openTip(cell);
    vi.useRealTimers();
    await within(tip()!).findByText('Не удалось загрузить');
    expect(nationCalls).toBe(1);

    server.resetHandlers();
    registerNation();
    leaveTip(cell);
    vi.useFakeTimers();
    openTip(cell);
    vi.useRealTimers();
    // Failures are not cached — the next hover asks again and wins.
    await within(tip()!).findByText('Борис Первый');
    expect(nationCalls).toBe(2);
  });

  it('a cell with id: null gets no tooltip', () => {
    vi.useFakeTimers();
    renderInRoot(
      <NationCell
        value={{
          id: null,
          name: 'Безвестная вотчина',
          color: '#555555',
          flag_url: null,
        }}
      />,
    );

    fireEvent.pointerOver(screen.getByText('Безвестная вотчина'), {
      clientX: 20,
      clientY: 20,
    });
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(tip()).toBeNull();
  });

  it('the tip does not block the click — the nation still opens', async () => {
    vi.useFakeTimers();
    registerNation();
    const onOpen = vi.fn();
    renderInRoot(<NationCell value={NATION_CELL} onOpen={onOpen} />);
    const cell = screen.getByRole('button', { name: 'Новгород' });

    openTip(cell);
    expect(tip()).toBeInTheDocument();
    fireEvent.pointerDown(cell);
    expect(tip()).toBeNull();
    fireEvent.click(cell);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(NATION_ID);
  });
});

describe('RegistryTable — nations-table «name» cell tip', () => {
  it('the name cell carries the same tooltip, fetched by the row key', async () => {
    vi.useFakeTimers();
    registerNation();
    renderInRoot(
      <RegistryTable
        table={NATIONS_TABLE}
        rows={NATIONS_ROWS}
        view={EMPTY_VIEW}
        onSortClick={() => {}}
      />,
    );

    openTip(screen.getByRole('button', { name: 'Новгород' }));
    vi.useRealTimers();
    // The row key IS the nation id — the same «Подсказка» content.
    await within(tip()!).findByText('Борис Первый');
    expect(nationCalls).toBe(1);
  });
});

describe('PersonCell — player «Подсказка»', () => {
  it('shows the four rows from the row cells and makes no request', async () => {
    vi.useFakeTimers();
    renderInRoot(
      <PersonCell value={PLAYER_CELLS.player} cells={PLAYER_CELLS} />,
    );

    openTip(screen.getByText('Борис Иванов'));
    vi.useRealTimers();

    const box = tip()!;
    expect(within(box).getByText('Борис Иванов')).toBeInTheDocument();
    expect(within(box).getByText('Дата регистрации')).toBeInTheDocument();
    expect(within(box).getByText('1 сентября 2026')).toBeInTheDocument();
    expect(within(box).getByText('Уровень')).toBeInTheDocument();
    expect(within(box).getByText('2')).toBeInTheDocument();
    expect(within(box).getByText('Судейский рейтинг')).toBeInTheDocument();
    expect(within(box).getByText('12')).toBeInTheDocument();
    expect(within(box).getByText('Государство')).toBeInTheDocument();
    expect(within(box).getByText('Новгород')).toBeInTheDocument();
    // No «click to open» line — a player cannot be opened yet.
    expect(
      within(box).queryByText(/Нажмите/),
    ).not.toBeInTheDocument();
    // No request at all: the only registered handler is never hit.
    expect(nationCalls).toBe(0);
  });

  it('a player without a nation shows «нет государства»', async () => {
    vi.useFakeTimers();
    renderInRoot(
      <PersonCell
        value={PLAYER_CELLS.player}
        cells={{ ...PLAYER_CELLS, nation: null }}
      />,
    );

    openTip(screen.getByText('Борис Иванов'));
    vi.useRealTimers();
    expect(
      await within(tip()!).findByText('нет государства'),
    ).toBeInTheDocument();
  });
});
