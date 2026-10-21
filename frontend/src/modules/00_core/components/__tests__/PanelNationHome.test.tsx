/**
 * PanelNationHome — the nation card and the edit form (Spec 1.3 Part 5,
 * UI Spec 9.1 «Штаб», mockup «Main», version 0.9.0 unit 8b).
 *
 * Card covers: header (flag/stub, «Кратко: краткое» when it differs
 * from the full name, display
 * name, motto, colour), the four stat tiles («N из M» from
 * /orders/rules, level/rating — the nation's own fields since 0.9.0),
 * leader block (no captions, title hidden when empty),
 * territory chips BY NAME with the capital first («★ Столица
 * (Провинция)»), the description/history block rules, the removed
 * service rows (gender, notifications, succession, anthem, delete),
 * the 910 px rule and the province-name loading placeholders.
 *
 * Edit covers (unit 8c): the same tab strip and blocks as the
 * registration window, the PATCH that must carry only changed fields
 * (an emptied optional field goes as '', a legacy NULL flag/portrait
 * stands on the first catalog tile so the first save already carries
 * its id), partial saves for legacy nations, inline error mapping, the
 * read-only «Территории» tab, the bot-consent row's home at the bottom
 * of the edit view, no `anthem_url` anywhere, and the draft memory.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import type { NationDTO } from '../../../../shared/types';
import { BotStatusProvider } from '../../../02_bot/hooks/useBotStatus';
import { PanelNationHome } from '../PanelNationHome';
import {
  goToTab,
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  SESSION,
  mswMap,
} from './helpers';

const NATION: NationDTO = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  owner_player_id: SESSION.player.id,
  created_at: '2026-09-27T00:00:00Z',
  name: 'Testia',
  short_name: 'Тестия',
  color_hex: '#e64545',
  motto: null,
  description: null,
  flag_id: null,
  flag_url: null,
  // Mini-map ids — the chips must show manifest names, never numbers.
  province_ids: [1002, 1001],
  capital_province_id: 1001,
  capital_name: 'Столицево',
  leader_name: 'Иван Грозный',
  gender: 'male',
  leader_title: 'Верховный правитель',
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  succession_type: 'elections',
  history_url: 'https://vk.com/@testia-istoriya',
  anthem_url: null,
  // The owner's stats ride the nation itself — NOT the old registry
  // players row (level 3 / rating 12 there).
  level: 5,
  judge_rating: 21,
};

/** All post-0.8.0 fields null, no capital — the legacy card. */
const LEGACY_NATION: NationDTO = {
  ...NATION,
  short_name: null,
  capital_province_id: null,
  capital_name: null,
  leader_name: null,
  gender: null,
  leader_title: null,
  succession_type: null,
  history_url: null,
};

/**
 * NATION with the catalog ids filled: the edit form then has no
 * legacy-pick fallback to add, so a PATCH can carry ONLY the field the
 * player actually changed (the clean «changed fields only» cases).
 */
const FULL_NATION: NationDTO = {
  ...NATION,
  flag_id: 'flag_stub',
  portrait_id: 'portrait_stub',
};

function renderHome(nation: NationDTO = NATION) {
  const onChanged = vi.fn();
  const view = renderWithProviders(
    <PanelNationHome nation={nation} onChanged={onChanged} />,
  );
  return { onChanged, ...view };
}

async function openEdit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Изменить' }));
  return screen.getByRole('button', { name: 'Сохранить' });
}

/** Captures PATCH /nations/me bodies; the responder returns `reply`. */
function capturePatch(reply: NationDTO) {
  const bodies: unknown[] = [];
  server.use(
    http.patch('*/api/v1/nations/me', async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json(reply);
    }),
  );
  return bodies;
}

beforeEach(registerDefaultHandlers);

describe('PanelNationHome — the card', () => {
  it('renders the full card: header, tiles, leader, territory names, description', async () => {
    const nation: NationDTO = {
      ...NATION,
      motto: 'Север помнит всё',
      description: 'Профиль государства',
      flag_url: '/assets/nations/flags/flag_stub.png',
      portrait_url: '/assets/nations/portraits/portrait_stub.png',
      leader_bio: 'Правил долго и грозно',
    };
    renderHome(nation);

    // Header — flag image, «Кратко: краткое», display name,
    // motto, colour swatch + HEX.
    expect(screen.getByAltText('Флаг Testia')).toBeInTheDocument();
    const header = screen.getByTestId('nation-card-header');
    expect(within(header).getByText('Кратко: Тестия'))
      .toBeInTheDocument();
    expect(within(header).getByText('Testia')).toBeInTheDocument();
    expect(within(header).getByText('Север помнит всё'))
      .toBeInTheDocument();
    expect(within(header).getByText('#e64545')).toBeInTheDocument();
    expect(
      within(header).getByRole('button', { name: 'Изменить' }),
    ).toBeInTheDocument();

    // The four tiles — level/rating are the nation's own fields.
    const tiles = await screen.findByTestId('nation-stats-row');
    const tileOf = (label: string) =>
      within(tiles).getByText(label).parentElement as HTMLElement;
    expect(tileOf('Провинции').textContent).toContain('2');
    await waitFor(() =>
      expect(tileOf('Уровень').textContent).toContain('5'),
    );
    await waitFor(() =>
      expect(tileOf('Судейский рейтинг').textContent).toContain('21'),
    );
    await waitFor(() =>
      expect(tileOf('Неразрешённые приказы').textContent).toContain(
        '2 из 7',
      ),
    );

    // Leader — portrait image, name, uppercase title, bio; no captions.
    const leader = screen.getByTestId('nation-leader-block');
    expect(
      within(leader).getByAltText('Портрет лидера Testia'),
    ).toBeInTheDocument();
    expect(within(leader).getByText('Иван Грозный'))
      .toBeInTheDocument();
    expect(within(leader).getByText('Верховный правитель'))
      .toBeInTheDocument();
    expect(within(leader).getByText('Правил долго и грозно'))
      .toBeInTheDocument();

    // Territory — province NAMES in chips, the capital first with «★».
    const territory = screen.getByTestId('nation-territory-block');
    const capitalChip = await within(territory).findByText(
      '★ Столицево (Альфа)',
    );
    expect(capitalChip).toBeInTheDocument();
    expect(within(territory).getByText('Бета')).toBeInTheDocument();
    // Province numbers are shown nowhere.
    expect(within(territory).queryByText(/1001|1002/))
      .not.toBeInTheDocument();

    // Description block + the history link at its end.
    const description = screen.getByTestId('nation-description-block');
    expect(within(description).getByText('Профиль государства'))
      .toBeInTheDocument();
    const history = within(description).getByRole('link', {
      name: 'История государства ↗',
    });
    expect(history).toHaveAttribute('href', nation.history_url);
    expect(history).toHaveAttribute('target', '_blank');
    expect(history).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('shows no label line when the short name is missing or equals the full name', async () => {
    renderHome({ ...NATION, short_name: NATION.name });
    const header = screen.getByTestId('nation-card-header');
    // The duplicated «Testia = Тестия» line is meaningless — never shown.
    expect(within(header).queryByText(/Кратко:/)).not.toBeInTheDocument();
    expect(within(header).getByText('Testia')).toBeInTheDocument();
  });

  it('the capital chip goes first and keeps the «★ Столица (Провинция)» form', async () => {
    renderHome();
    const territory = screen.getByTestId('nation-territory-block');
    const capitalChip = await within(territory).findByText(
      '★ Столицево (Альфа)',
    );
    const chips = within(territory).getAllByText(/Бета|Столицево/);
    expect(chips[0]).toBe(capitalChip);
    expect(chips).toHaveLength(2);
  });

  it('drops the service rows: no gender, notifications, succession, anthem, delete', async () => {
    renderHome({
      ...NATION,
      anthem_url: 'https://vk.com/music/playlist/-1_2',
    });
    await screen.findByText('★ Столицево (Альфа)');

    expect(screen.queryByText('Пол')).not.toBeInTheDocument();
    expect(screen.queryByText('Мужской')).not.toBeInTheDocument();
    expect(screen.queryByText('Уведомления')).not.toBeInTheDocument();
    expect(screen.queryByText('Гимн')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Способ смены лидера'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('Демократические выборы'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /удалить/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'Слушать гимн' }),
    ).not.toBeInTheDocument();
    // The old row captions are gone too.
    for (const caption of [
      'Название',
      'Краткое название',
      'Цвет',
      'Лидер',
      'Должность',
      'Столица',
    ]) {
      expect(screen.queryByText(caption)).not.toBeInTheDocument();
    }
  });

  it('legacy nation without flag/portrait shows the stubs and «не указано» leader', async () => {
    renderHome(LEGACY_NATION);
    await within(screen.getByTestId('nation-territory-block')).findByText(
      'Альфа',
    );
    expect(screen.getByLabelText('Заглушка флага')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Заглушка портрета').length)
      .toBeGreaterThan(0);
    // No short name → no «Кратко:» line at all.
    expect(
      within(screen.getByTestId('nation-card-header')).queryByText(
        /Кратко:/,
      ),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId('nation-leader-block')).getByText(
        'не указано',
      ),
    ).toBeInTheDocument();
    // No capital mark — no starred chip.
    expect(
      within(screen.getByTestId('nation-territory-block')).queryByText(
        /★/,
      ),
    ).not.toBeInTheDocument();
  });

  it('hides the «Описание» block when description and history are both empty', () => {
    renderHome({ ...NATION, description: null, history_url: null });
    expect(
      screen.queryByTestId('nation-description-block'),
    ).not.toBeInTheDocument();
  });

  it('shows the «Описание» block for the history link alone', async () => {
    renderHome({ ...NATION, description: null });
    const block = await screen.findByTestId('nation-description-block');
    expect(within(block).queryByText('Профиль государства'))
      .not.toBeInTheDocument();
    expect(
      within(block).getByRole('link', { name: 'История государства ↗' }),
    ).toBeInTheDocument();
  });

  it.each(['javascript:alert(1)', 'http://vk.com/@open'])(
    'does not render %s as a link — plain text only',
    (url) => {
      renderHome({ ...NATION, history_url: url });
      expect(
        screen.queryByRole('link', { name: 'История государства ↗' }),
      ).not.toBeInTheDocument();
      expect(screen.getByText(url)).toBeInTheDocument();
    },
  );

  it('keeps every block inside the 910 px window', () => {
    renderHome();
    const panel = screen.getByTestId('panel-nation-home');
    expect(panel.style.maxWidth).toBe('910px');
    expect(panel.style.boxSizing).toBe('border-box');
  });

  it('shows same-size placeholders while province names load — no numbers flash', async () => {
    let resolveManifest!: () => void;
    server.use(
      http.get('*/api/v1/map/manifest', async () => {
        await new Promise<void>((resolve) => {
          resolveManifest = resolve;
        });
        return HttpResponse.json(mswMap.manifest);
      }),
    );
    renderHome();
    const territory = screen.getByTestId('nation-territory-block');
    await within(territory).findAllByTestId('province-chip-placeholder');
    expect(within(territory).queryByText(/1001|1002/))
      .not.toBeInTheDocument();

    resolveManifest();
    expect(await within(territory).findByText('Бета'))
      .toBeInTheDocument();
  });

  it('shows «Провинция» without the number for a province missing from the manifest', async () => {
    renderHome({
      ...NATION,
      province_ids: [9999],
      capital_province_id: null,
      capital_name: null,
    });
    const territory = screen.getByTestId('nation-territory-block');
    // Wait until the names settled — the loading placeholder is a
    // detached node by then and cannot match anymore.
    await waitFor(() =>
      expect(
        within(territory).queryByTestId('province-chip-placeholder'),
      ).not.toBeInTheDocument(),
    );
    expect(within(territory).getByText('Провинция'))
      .toBeInTheDocument();
    expect(within(territory).queryByText(/9999/)).not.toBeInTheDocument();
  });

  it('loads province names once through the shared map cache', async () => {
    let manifestCalls = 0;
    let geometryCalls = 0;
    server.use(
      http.get('*/api/v1/map/manifest', () => {
        manifestCalls += 1;
        return HttpResponse.json(mswMap.manifest);
      }),
      http.get('*/api/v1/map/geometry/:version', () => {
        geometryCalls += 1;
        return HttpResponse.json(mswMap.geometry);
      }),
    );
    renderHome();

    const territory = screen.getByTestId('nation-territory-block');
    await within(territory).findByText('Бета');
    // One manifest request total — the names ride the shared map
    // data, not a second download; geometry is never touched.
    expect(manifestCalls).toBe(1);
    expect(geometryCalls).toBe(0);
  });
});

describe('PanelNationHome — edit form', () => {
  it('uses the registration shell: «РЕДАКТИРОВАНИЕ ГОСУДАРСТВА», «ШАГ N ИЗ 4», the four tabs', async () => {
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    await openEdit(user);

    expect(
      screen.getByText('Редактирование государства'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 1 из 4',
    );
    for (const title of [
      'Основные данные и символика',
      'Глава государства',
      'История',
      'Территории',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    }

    // Tab navigation is the same strip; «Сохранить»/«Отмена» stay.
    await goToTab(user, 3);
    expect(
      screen.getByLabelText('Ссылка на статью с историей государства'),
    ).toBeInTheDocument();
    // No anthem field anywhere in the edit form either.
    expect(screen.queryByLabelText(/гимн/i)).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('form-item-anthem-url'),
    ).not.toBeInTheDocument();
  });

  it('a legacy NULL flag/portrait opens on the first catalog tile — the first save carries both ids', async () => {
    const bodies = capturePatch(NATION);
    const { onChanged } = renderHome(NATION); // flag_id/portrait_id: null
    const user = userEvent.setup();
    const save = await openEdit(user);

    // Once the catalog lands the first flag stands selected, and the
    // PATCH already differs — «Сохранить» is armed by the fallback.
    const flag = await screen.findByRole('button', { name: 'flag_stub' });
    await waitFor(() => expect(flag).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.queryByText('Без флага')).not.toBeInTheDocument();
    expect(save).toBeEnabled();

    await goToTab(user, 2);
    const portrait = await screen.findByRole('button', {
      name: 'portrait_stub',
    });
    await waitFor(() =>
      expect(portrait).toHaveAttribute('aria-pressed', 'true'),
    );
    expect(screen.queryByText('Без портрета')).not.toBeInTheDocument();

    // The player changed nothing else — the PATCH still carries the ids.
    await user.click(save);
    await waitFor(() =>
      expect(bodies).toEqual([
        { flag_id: 'flag_stub', portrait_id: 'portrait_stub' },
      ]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('the «Территории» tab is read-only: named rows, capital first, no actions', async () => {
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    await openEdit(user);
    await goToTab(user, 4);

    const provincesItem = screen.getByTestId('form-item-provinces');
    // Rows keep the real names (manifest), the capital leads with «★» —
    // and no «Выбрать на карте», «Сделать столицей» or «×» anywhere.
    const rows = await within(provincesItem).findAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('★ Альфа');
    expect(provincesItem).toHaveTextContent('Бета');
    expect(
      screen.queryByTestId('open-province-picker'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Сделать столицей' }),
    ).not.toBeInTheDocument();
    expect(
      within(provincesItem).queryByRole('button', { name: /убрать/i }),
    ).not.toBeInTheDocument();
    // The capital name stays editable for a nation that has a capital.
    expect(screen.getByLabelText('Название столицы')).toHaveValue(
      'Столицево',
    );
  });

  it('keeps Сохранить disabled until a field actually changes', async () => {
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    const save = await openEdit(user);
    expect(save).toBeDisabled();

    await goToTab(user, 2);
    await user.type(screen.getByLabelText('Имя лидера'), 'X');
    expect(save).toBeEnabled();
  });

  it('PATCHes only the changed fields — and never anthem_url', async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.patch('*/api/v1/nations/me', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          { ...FULL_NATION, leader_name: 'Пётр Первый' },
        );
      }),
    );
    const { onChanged } = renderHome(FULL_NATION);
    const user = userEvent.setup();
    const save = await openEdit(user);

    await goToTab(user, 2);
    const input = screen.getByLabelText('Имя лидера');
    await user.clear(input);
    await user.type(input, 'Пётр Первый');
    await user.click(save);

    await waitFor(() =>
      expect(bodies).toEqual([{ leader_name: 'Пётр Первый' }]),
    );
    expect(bodies[0]).not.toHaveProperty('anthem_url');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(
      screen.queryByTestId('edit-nation-form'),
    ).not.toBeInTheDocument();
    // The shared success bar reports «Изменения сохранены» (UI Spec 7).
    expect(await screen.findByTestId('notice')).toHaveTextContent(
      'Изменения сохранены',
    );
  });

  it('Enter in a one-line field does not submit the edit form', async () => {
    let patches = 0;
    server.use(
      http.patch('*/api/v1/nations/me', () => {
        patches += 1;
        return HttpResponse.json(FULL_NATION);
      }),
    );
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    await openEdit(user);

    const nameInput = screen.getByLabelText('Полное название');
    await user.click(nameInput);
    await user.keyboard('{Enter}');
    expect(patches).toBe(0);
    expect(screen.getByTestId('edit-nation-form')).toBeInTheDocument();
  });

  it('legacy nation: no capital input; the tab-4 rows stay; the PATCH adds the catalog fallbacks', async () => {
    const bodies = capturePatch({
      ...LEGACY_NATION,
      short_name: 'Тестия',
      flag_id: 'flag_stub',
      portrait_id: 'portrait_stub',
    });
    const { onChanged } = renderHome(LEGACY_NATION);

    // Card: no capital mark and the render is error-free.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    const user = userEvent.setup();
    const save = await openEdit(user);
    // The territory tab is read-only and the capital-name input is
    // hidden — the server refuses capital_name for a nation without one.
    await goToTab(user, 4);
    expect(
      await within(screen.getByTestId('form-item-provinces')).findAllByRole(
        'listitem',
      ),
    ).toHaveLength(2);
    expect(
      screen.queryByLabelText('Название столицы'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('open-province-picker'),
    ).not.toBeInTheDocument();

    await goToTab(user, 1);
    await user.type(screen.getByLabelText('Краткое название'), 'Тестия');
    await user.click(save);
    await waitFor(() =>
      expect(bodies).toEqual([
        {
          short_name: 'Тестия',
          flag_id: 'flag_stub',
          portrait_id: 'portrait_stub',
        },
      ]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('a cleared optional field is sent as an empty string — motto only', async () => {
    const mottoNation: NationDTO = {
      ...FULL_NATION,
      motto: 'Север помнит всё',
    };
    const bodies = capturePatch({ ...mottoNation, motto: null });
    renderHome(mottoNation);

    const user = userEvent.setup();
    const save = await openEdit(user);
    await user.clear(screen.getByLabelText('Девиз'));
    await user.click(save);

    await waitFor(() => expect(bodies).toEqual([{ motto: '' }]));
  });

  it('lets a legacy nation rename itself without touching the profile', async () => {
    const bodies = capturePatch({
      ...LEGACY_NATION,
      name: 'Новая Тестия',
      flag_id: 'flag_stub',
      portrait_id: 'portrait_stub',
    });
    const { onChanged } = renderHome(LEGACY_NATION);
    const user = userEvent.setup();
    const save = await openEdit(user);

    const nameInput = screen.getByLabelText('Полное название');
    await user.clear(nameInput);
    await user.type(nameInput, 'Новая Тестия');
    // The profile fields were left empty — the nation may still be renamed.
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() =>
      expect(bodies).toEqual([
        {
          name: 'Новая Тестия',
          flag_id: 'flag_stub',
          portrait_id: 'portrait_stub',
        },
      ]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('blocks saving when a previously filled profile field is emptied', async () => {
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    const save = await openEdit(user);

    await goToTab(user, 2);
    await user.clear(screen.getByLabelText('Имя лидера'));
    expect(save).toBeDisabled();
  });

  it('blocks saving when the name is shorter than the rules minimum', async () => {
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    const save = await openEdit(user);
    // Wait until the rules-driven «N из M» counter rendered — the
    // gating must use the same numbers.
    await within(screen.getByTestId('form-item-name')).findByText(
      `${'Testia'.length} из ${RULES.name_max_length}`,
    );

    const nameInput = screen.getByLabelText('Полное название');
    await user.clear(nameInput);
    await user.type(nameInput, 'ab'); // < msw name_min_length = 4
    expect(save).toBeDisabled();
  });

  it('shows HISTORY_URL_INVALID inline in the edit form', async () => {
    server.use(
      http.patch('*/api/v1/nations/me', () =>
        HttpResponse.json(
          {
            detail: 'History url must point to a VK article',
            code: 'HISTORY_URL_INVALID',
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    const save = await openEdit(user);

    await goToTab(user, 3);
    await user.type(
      screen.getByLabelText('Ссылка на статью с историей государства'),
      'x',
    );
    await user.click(save);

    const item = screen.getByTestId('form-item-history-url');
    await waitFor(() =>
      expect(
        within(item).getByText(/должна вести на статью ВКонтакте/i),
      ).toBeInTheDocument(),
    );
    // Editing the field clears the inline error (the static hint stays).
    await user.type(
      screen.getByLabelText('Ссылка на статью с историей государства'),
      'y',
    );
    expect(
      within(item).queryByText(/должна вести на статью ВКонтакте/i),
    ).not.toBeInTheDocument();
  });

  it('falls back to the generic banner for errors with no field mapping', async () => {
    server.use(
      http.patch('*/api/v1/nations/me', () =>
        HttpResponse.json(
          { detail: 'Nation not found', code: 'NATION_NOT_FOUND' },
          { status: 404 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderHome(FULL_NATION);
    const save = await openEdit(user);

    await goToTab(user, 2);
    await user.type(screen.getByLabelText('Должность лидера'), 'X');
    await user.click(save);

    await screen.findByText('Не удалось обновить государство');
    // The English detail never reaches the screen — the dictionary
    // text of NATION_NOT_FOUND does.
    expect(
      screen.getByText('Государство не найдено.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nation not found/i),
    ).not.toBeInTheDocument();
  });

  it('hosts the bot-consent row at the bottom of the edit view', async () => {
    server.use(
      http.get('*/api/v1/bot/status', () =>
        HttpResponse.json({
          enabled: true,
          consent: 'UNKNOWN',
          stale: false,
          throttled: false,
          registration_requires_consent: false,
          chat_url: 'https://vk.me/join/test',
          consent_poll_interval_seconds: 2,
          consent_poll_timeout_seconds: 60,
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <BotStatusProvider>
        <PanelNationHome nation={NATION} onChanged={() => {}} />
      </BotStatusProvider>,
    );

    // Not on the card — the row moved into the edit view (unit 8b).
    expect(screen.queryByText('Уведомления')).not.toBeInTheDocument();

    await openEdit(user);
    expect(await screen.findByText('Уведомления')).toBeInTheDocument();
  });
});

describe('PanelNationHome — edit draft memory', () => {
  it('restores typed values on remount and deletes them on «Отмена»', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelNationHome nation={FULL_NATION} onChanged={() => {}} />,
    );

    // Type, leave (the panel unmounts like a screen switch) — the
    // draft must survive.
    await openEdit(user);
    await goToTab(user, 2);
    await user.type(screen.getByLabelText('Имя лидера'), 'X');
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван ГрозныйX',
    );
    first.unmount();

    const second = renderWithProviders(
      <PanelNationHome nation={FULL_NATION} onChanged={() => {}} />,
    );
    await openEdit(user);
    await goToTab(user, 2);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван ГрозныйX',
    );

    // «Отмена» deletes the draft — the next visit shows the nation.
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    second.unmount();

    renderWithProviders(
      <PanelNationHome nation={FULL_NATION} onChanged={() => {}} />,
    );
    await openEdit(user);
    await goToTab(user, 2);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван Грозный',
    );
  });
});
