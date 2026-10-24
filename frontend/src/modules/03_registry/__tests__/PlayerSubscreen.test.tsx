/**
 * PlayerSubscreen — the «Игрок» subscreen of the Registry (UI Spec
 * 9.7, version 0.10.0 unit 8b): the public player card from
 * GET /registry/players/{number}, the path chain, the three states
 * (loading / error with «Повторить» / «Игрок не найден»), the
 * no-nation case and the p<N> click gate of person cells.
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { EMPTY_VIEW } from '../lib/tableView';
import { RegistryTable } from '../components/RegistryTable';
import { PlayerSubscreen } from '../components/PlayerSubscreen';
import type {
  RegistryPlayerDTO,
  RegistryRowDTO,
  RegistryTableDTO,
} from '../types';
import { renderWithSession } from './helpers';

const NATION_ID = 'a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d';

const PLAYER: RegistryPlayerDTO = {
  number: 1,
  person: {
    name: 'Борис Иванов',
    avatar_url: 'https://pp.vk.me/avatar.png',
    is_fallback: false,
  },
  joined: { text: '01.09.2026', key: 20697 },
  level: 2,
  judge_rating: 12,
  nation: {
    id: NATION_ID,
    name: 'НВГ',
    color: '#C0392B',
    flag_url: '/assets/nations/flags/flag_1.png',
  },
};

let lastPlayerUrl = '';

function registerPlayer(body: RegistryPlayerDTO = PLAYER, number = 1) {
  server.use(
    http.get(`*/api/v1/registry/players/${number}`, ({ request }) => {
      lastPlayerUrl = request.url;
      return HttpResponse.json(body);
    }),
  );
}

function renderSubscreen(props: {
  number?: number;
  fromTab?: string | null;
  onBack?: () => void;
  onOpenNation?: (nationId: string) => void;
}) {
  return renderWithSession(
    <PlayerSubscreen
      number={props.number ?? 1}
      fromTab={props.fromTab ?? null}
      onBack={props.onBack ?? (() => {})}
      onOpenNation={props.onOpenNation ?? (() => {})}
    />,
  );
}

beforeEach(() => {
  lastPlayerUrl = '';
});

describe('PlayerSubscreen — content', () => {
  it('loads the public card: avatar, caption, three tiles, nation card', async () => {
    registerPlayer();
    renderSubscreen({});

    await screen.findByTestId('player-subscreen');
    // The chain: «Реестр / Игроки / <имя>» — «Игроки» on a bare link.
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Игроки / Борис Иванов',
    );

    const header = screen.getByTestId('player-subscreen-header');
    // PNG 12: the VK avatar is a real image at 96 px under the
    // «ИГРОК» caption.
    const avatar = header.querySelector('img');
    expect(avatar).not.toBeNull();
    expect(avatar).toHaveAttribute('src', 'https://pp.vk.me/avatar.png');
    expect(avatar).toHaveAttribute('width', '96');
    expect(within(header).getByText('Игрок')).toBeInTheDocument();
    expect(within(header).getByText('Борис Иванов')).toBeInTheDocument();

    // PNG 12: three tiles — «РЕГИСТРАЦИЯ», «УРОВЕНЬ», «РЕЙТИНГ» (the
    // rating a bare signal number, no gauge bar).
    const stats = screen.getByTestId('player-subscreen-stats');
    expect(within(stats).getByText('Регистрация')).toBeInTheDocument();
    expect(within(stats).getByText('01.09.2026')).toBeInTheDocument();
    expect(within(stats).getByText('Уровень')).toBeInTheDocument();
    expect(within(stats).getByText('2')).toBeInTheDocument();
    expect(within(stats).getByText('Рейтинг')).toBeInTheDocument();
    expect(within(stats).getByText('12')).toBeInTheDocument();
    expect(
      within(stats).queryByTestId('gauge-fill'),
    ).not.toBeInTheDocument();

    // The nation card — the short name is a button to the subscreen.
    const nation = screen.getByTestId('player-subscreen-nation');
    expect(within(nation).getByText('Государство')).toBeInTheDocument();
    expect(
      within(nation).getByRole('button', { name: 'НВГ' }),
    ).toBeInTheDocument();

    // INV-R2: nothing that even looks like the hidden identifiers.
    expect(document.body.innerHTML).not.toContain('player_id');
    expect(document.body.innerHTML).not.toContain('vk_user_id');
    expect(lastPlayerUrl).toContain('/api/v1/registry/players/1');
    expect(lastPlayerUrl).not.toContain('player_id');
    expect(lastPlayerUrl).not.toContain('vk_user_id');
  });

  it('reads «Реестр / <вкладка> / <имя>» when fromTab is set', async () => {
    registerPlayer();
    renderSubscreen({ fromTab: 'Игроки' });

    await screen.findByTestId('player-subscreen');
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Игроки / Борис Иванов',
    );
  });

  it('a fallback profile shows the neutral circle and the fallback name', async () => {
    registerPlayer({
      ...PLAYER,
      person: { name: 'Игрок №3', avatar_url: null, is_fallback: true },
    });
    renderSubscreen({});

    const header = await screen.findByTestId('player-subscreen-header');
    expect(within(header).getByText('Игрок №3')).toBeInTheDocument();
    // No VK photo in the header — the neutral circle stands in.
    expect(header.querySelector('img')).toBeNull();
  });

  it('a player without a nation shows «Государства нет» — no flag, no link', async () => {
    registerPlayer({ ...PLAYER, nation: null });
    renderSubscreen({});

    const nation = await screen.findByTestId('player-subscreen-nation');
    expect(
      within(nation).getByText('Государства нет'),
    ).toBeInTheDocument();
    expect(within(nation).queryByRole('button')).toBeNull();
    expect(within(nation).queryByRole('img')).toBeNull();
  });

  it('a nation cell with id: null stays plain text', async () => {
    registerPlayer({
      ...PLAYER,
      nation: {
        id: null,
        name: 'Безвестная вотчина',
        color: '#555555',
        flag_url: null,
      },
    });
    renderSubscreen({});

    const nation = await screen.findByTestId('player-subscreen-nation');
    expect(
      within(nation).getByText('Безвестная вотчина'),
    ).toBeInTheDocument();
    expect(within(nation).queryByRole('button')).toBeNull();
  });

  it('the nation line opens the nation subscreen by its id', async () => {
    const user = userEvent.setup();
    const onOpenNation = vi.fn();
    registerPlayer();
    renderSubscreen({ onOpenNation });

    await user.click(
      await screen.findByRole('button', { name: 'НВГ' }),
    );
    expect(onOpenNation).toHaveBeenCalledWith(NATION_ID);
  });

  it('«← Реестр» in the band calls onBack', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    registerPlayer();
    renderSubscreen({ onBack });

    await screen.findByTestId('player-subscreen');
    await user.click(screen.getByTestId('subscreen-back'));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('PlayerSubscreen — failure states', () => {
  it('404 → «Игрок не найден» plus a «← Реестр» button', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    server.use(
      http.get('*/api/v1/registry/players/99', () =>
        HttpResponse.json(
          { detail: 'Player not found', code: 'REGISTRY_PLAYER_NOT_FOUND' },
          { status: 404 },
        ),
      ),
    );
    renderSubscreen({ number: 99, onBack });

    expect(
      await screen.findByText('Игрок не найден'),
    ).toBeInTheDocument();
    const backs = screen.getAllByRole('button', { name: '← Реестр' });
    expect(backs.length).toBeGreaterThanOrEqual(2);
    await user.click(backs[backs.length - 1]);
    expect(onBack).toHaveBeenCalled();
  });

  it('a server error shows the shared ErrorState and «Повторить» reloads', async () => {
    const user = userEvent.setup();
    let calls = 0;
    server.use(
      http.get('*/api/v1/registry/players/1', () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            { detail: 'boom', code: 'INTERNAL' },
            { status: 500 },
          );
        }
        return HttpResponse.json(PLAYER);
      }),
    );
    renderSubscreen({});

    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('player-subscreen')).toBeInTheDocument();
    expect(calls).toBe(2);
  });
});

describe('RegistryTable — person cell opens the player only for p<N> keys', () => {
  const PLAYERS_TABLE: RegistryTableDTO = {
    id: 'players',
    title: 'Игроки',
    icon: 'players',
    empty_text: 'Игроков пока нет',
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
        id: 'player',
        title: 'Игрок',
        type: 'person',
        width_px: 190,
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

  const person = (name: string) => ({
    name,
    avatar_url: null,
    is_fallback: false,
  });

  const ROWS: RegistryRowDTO[] = [
    { key: 'p5', cells: { number: 5, player: person('Борис Иванов') } },
    // An orders-table-shaped key — the cell must NOT guess a number.
    { key: 'o7', cells: { number: 7, player: person('Анна Смирнова') } },
    // A `p` key with a non-number tail — not clickable either.
    { key: 'p7a', cells: { number: 8, player: person('Игрок №8') } },
  ];

  it('a p<N> row key makes the person cell a button passing N; other keys stay plain text', async () => {
    const user = userEvent.setup();
    const onOpenPlayer = vi.fn();
    renderWithSession(
      <RegistryTable
        table={PLAYERS_TABLE}
        rows={ROWS}
        view={EMPTY_VIEW}
        onSortClick={() => {}}
        onOpenPlayer={onOpenPlayer}
      />,
    );

    const button = screen.getByRole('button', { name: 'Борис Иванов' });
    // 'o7' and 'p7a' rows render their names as plain text — no button.
    expect(
      screen.queryByRole('button', { name: 'Анна Смирнова' }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Игрок №8' }),
    ).toBeNull();
    expect(screen.getByText('Анна Смирнова')).toBeInTheDocument();
    expect(screen.getByText('Игрок №8')).toBeInTheDocument();

    await user.click(button);
    expect(onOpenPlayer).toHaveBeenCalledWith(5);
  });
});
