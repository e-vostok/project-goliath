/**
 * NationSubscreen — the «Государство» subscreen of the Registry
 * (UI Spec 9.3, version 0.9.0 unit 14c): the public nation card from
 * GET /nations/{id}, the path chain, and the three states
 * (loading / error with «Повторить» / «Государство не найдено»).
 */

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import type { NationPublicDTO } from '../../../../shared/types';
import { NationSubscreen } from '../NationSubscreen';
import {
  registerDefaultHandlers,
  renderWithProviders,
} from './helpers';

const NATION_ID = 'a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d';

const NATION: NationPublicDTO = {
  id: NATION_ID,
  created_at: '2026-09-01T12:00:00Z',
  name: 'Новгород',
  short_name: 'НВГ',
  color_hex: '#C0392B',
  motto: 'Слово и дело',
  description: 'Вольный город на севере.',
  flag_id: null,
  flag_url: null,
  // 1002 «Бета» is listed before the capital 1001 «Альфа» on purpose —
  // the territory block must move the capital first.
  province_ids: [1002, 1001],
  capital_province_id: 1001,
  capital_name: 'Новгород-град',
  leader_name: 'Борис Первый',
  leader_title: 'Князь',
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  history_url: 'https://vk.com/@novgorod-history',
  level: 3,
  judge_rating: 12,
};

function registerNation(body: NationPublicDTO = NATION) {
  server.use(
    http.get(`*/api/v1/nations/${NATION_ID}`, () =>
      HttpResponse.json(body),
    ),
  );
}

function renderSubscreen(props: {
  fromTab?: string | null;
  onBack?: () => void;
  onShowOnMap?: (capitalId: number | null) => void;
}) {
  return renderWithProviders(
    <NationSubscreen
      nationId={NATION_ID}
      fromTab={props.fromTab ?? null}
      onBack={props.onBack ?? (() => {})}
      onShowOnMap={props.onShowOnMap ?? (() => {})}
    />,
  );
}

describe('NationSubscreen — content (direct link, no router state)', () => {
  it('loads the public card: header, THREE tiles, leader, territory, description', async () => {
    registerDefaultHandlers();
    registerNation();
    renderSubscreen({});

    // The card arrives (getNation) — the header shows the label, name
    // and motto; the chain becomes «Реестр / Государство · Новгород».
    await screen.findByText('Новгород');
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Государство · Новгород',
    );
    // The short name is the small label line above the name — no
    // «Кратко:» words since 0.9.2 (0.10.0 unit 4a).
    expect(screen.getByText('НВГ')).toBeInTheDocument();
    expect(screen.getByText('Слово и дело')).toBeInTheDocument();

    // Exactly three tiles — no «Приказы» tile, no «Изменить» button;
    // the header action is «Показать на карте».
    const stats = screen.getByTestId('nation-subscreen-stats');
    expect(stats.children).toHaveLength(3);
    expect(stats).toHaveTextContent('Провинции');
    expect(stats).toHaveTextContent('Уровень');
    expect(stats).toHaveTextContent('Судейский рейтинг');
    expect(screen.queryByText('Неразрешённые приказы')).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Изменить' }),
    ).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Показать на карте' }),
    ).toBeInTheDocument();

    // «Глава государства» and «Описание» with the history link.
    expect(screen.getByText('Глава государства')).toBeInTheDocument();
    expect(screen.getByText('Борис Первый')).toBeInTheDocument();
    expect(screen.getByText('Вольный город на севере.')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'История государства ↗' }),
    ).toHaveAttribute('href', 'https://vk.com/@novgorod-history');

    // Province NAMES, never numbers; the capital comes first.
    const territory = screen.getByTestId('nation-territory-block');
    await waitFor(() =>
      expect(territory).toHaveTextContent('Альфа'),
    );
    expect(territory).toHaveTextContent('Бета');
    expect(territory).not.toHaveTextContent('1001');
    expect(territory).not.toHaveTextContent('1002');
    expect(territory.textContent?.indexOf('Альфа')).toBeLessThan(
      territory.textContent?.indexOf('Бета') ?? -1,
    );
    // The capital chip carries its «★ …» form.
    expect(territory).toHaveTextContent('★');
  });

  it('shows no owner-only fields — no «Приказы», gender, succession or anthem', async () => {
    registerDefaultHandlers();
    registerNation();
    renderSubscreen({});
    await screen.findByText('Новгород');

    expect(screen.queryByText('Приказы')).toBeNull();
    expect(screen.queryByText(/Мужской|Женский/)).toBeNull();
    expect(screen.queryByText(/гимн/i)).toBeNull();
    expect(screen.queryByText(/наследован|выборы/i)).toBeNull();
  });

  it('opens the map through «Показать на карте» with the capital id', async () => {
    const user = userEvent.setup();
    const onShowOnMap = vi.fn();
    registerDefaultHandlers();
    registerNation();
    renderSubscreen({ onShowOnMap });

    await user.click(
      await screen.findByRole('button', { name: 'Показать на карте' }),
    );
    expect(onShowOnMap).toHaveBeenCalledWith(1001);
  });

  it('«← Реестр» in the band calls onBack', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    registerDefaultHandlers();
    registerNation();
    renderSubscreen({ onBack });

    await screen.findByText('Новгород');
    await user.click(screen.getByTestId('subscreen-back'));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('NationSubscreen — chain from a table row', () => {
  it('reads «Реестр / <вкладка> / <название>» when fromTab is set', async () => {
    registerDefaultHandlers();
    registerNation();
    renderSubscreen({ fromTab: 'Игроки' });

    // «Новгород» sits in the chain AND the header — wait on the card.
    await screen.findByTestId('nation-subscreen');
    expect(screen.getByTestId('subscreen-trail')).toHaveAttribute(
      'aria-label',
      'Реестр / Игроки / Новгород',
    );
  });
});

describe('NationSubscreen — failure states', () => {
  it('404 → «Государство не найдено» plus a «← Реестр» button', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    registerDefaultHandlers();
    server.use(
      http.get(`*/api/v1/nations/${NATION_ID}`, () =>
        HttpResponse.json(
          { detail: 'Nation not found', code: 'NATION_NOT_FOUND' },
          { status: 404 },
        ),
      ),
    );
    renderSubscreen({ onBack });

    expect(
      await screen.findByText('Государство не найдено'),
    ).toBeInTheDocument();
    // The band button and the state's own «← Реестр» both lead back.
    const backs = screen.getAllByRole('button', { name: '← Реестр' });
    expect(backs.length).toBeGreaterThanOrEqual(2);
    await user.click(backs[backs.length - 1]);
    expect(onBack).toHaveBeenCalled();
  });

  it('a server error shows the shared ErrorState and «Повторить» reloads', async () => {
    const user = userEvent.setup();
    registerDefaultHandlers();
    let calls = 0;
    server.use(
      http.get(`*/api/v1/nations/${NATION_ID}`, () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            { detail: 'boom', code: 'INTERNAL' },
            { status: 500 },
          );
        }
        return HttpResponse.json(NATION);
      }),
    );
    renderSubscreen({});

    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Новгород')).toBeInTheDocument();
    expect(calls).toBe(2);
  });
});
