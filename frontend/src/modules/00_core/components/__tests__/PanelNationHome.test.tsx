/**
 * PanelNationHome — the nation card and the edit form (Spec 1.3 Part 5).
 *
 * Covers: the full card (short name, motto/description when present,
 * capital line, gender/succession labels, flag/portrait images),
 * «не указано» for the null fields of a pre-0.8.0 nation with the
 * optional ones simply hidden, the https-only external links, the PATCH
 * that must carry only changed fields (an emptied optional field goes
 * as ''), partial saves for legacy nations and inline error mapping.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import type { NationDTO } from '../../../../shared/types';
import { PanelNationHome } from '../PanelNationHome';
import {
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  SESSION,
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
  province_ids: [1, 2],
  capital_province_id: 1,
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
  it('renders the full card: names, color, provinces, capital, leader, links', () => {
    const nation: NationDTO = {
      ...NATION,
      motto: 'Север помнит всё',
      description: 'Профиль государства',
      flag_url: '/assets/nations/flags/flag_stub.png',
      portrait_url: '/assets/nations/portraits/portrait_stub.png',
      leader_bio: 'Правил долго и грозно',
      anthem_url: 'https://vk.com/music/playlist/-1_2',
    };
    renderHome(nation);

    expect(screen.getByAltText('Флаг Testia')).toBeInTheDocument();
    expect(
      screen.getByAltText('Портрет лидера Testia'),
    ).toBeInTheDocument();
    // The header and the «Название» cell both carry the full name.
    expect(screen.getAllByText('Testia')).toHaveLength(2);
    expect(screen.getByText('Тестия')).toBeInTheDocument();
    expect(screen.getByText('Север помнит всё')).toBeInTheDocument();
    expect(screen.getByText('Профиль государства')).toBeInTheDocument();
    expect(screen.getByText('#e64545')).toBeInTheDocument();
    expect(screen.getByText('1, 2')).toBeInTheDocument();
    expect(
      screen.getByText('Столицево (провинция 1)'),
    ).toBeInTheDocument();
    expect(screen.getByText('Иван Грозный')).toBeInTheDocument();
    expect(screen.getByText('Мужской')).toBeInTheDocument();
    expect(screen.getByText('Верховный правитель')).toBeInTheDocument();
    expect(screen.getByText('Правил долго и грозно')).toBeInTheDocument();
    expect(
      screen.getByText('Демократические выборы'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Пока без последствий в игре'),
    ).toBeInTheDocument();

    const history = screen.getByRole('link', { name: 'Открыть статью' });
    expect(history).toHaveAttribute('href', nation.history_url);
    expect(history).toHaveAttribute('target', '_blank');
    expect(history).toHaveAttribute('rel', 'noopener noreferrer');
    const anthem = screen.getByRole('link', { name: 'Слушать гимн' });
    expect(anthem).toHaveAttribute('href', nation.anthem_url);
    expect(anthem).toHaveAttribute('target', '_blank');
    expect(anthem).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('hides the optional cells and the images when they are not set', () => {
    renderHome();
    expect(screen.queryByText('Девиз')).not.toBeInTheDocument();
    expect(screen.queryByText('Описание')).not.toBeInTheDocument();
    expect(screen.queryByText('Биография лидера')).not.toBeInTheDocument();
    expect(screen.queryByText('Гимн')).not.toBeInTheDocument();
    expect(
      screen.queryByAltText(/Флаг|Портрет/),
    ).not.toBeInTheDocument();
  });

  it('shows «не указано» for the null fields of a legacy nation', () => {
    renderHome(LEGACY_NATION);
    // short name, leader name, gender, leader title, succession, history.
    expect(screen.getAllByText('не указано')).toHaveLength(6);
    expect(
      screen.queryByRole('link', { name: 'Открыть статью' }),
    ).not.toBeInTheDocument();
  });

  it.each(['javascript:alert(1)', 'http://vk.com/@open'])(
    'does not render %s as a link — plain text only',
    (url) => {
      renderHome({ ...NATION, history_url: url });
      expect(
        screen.queryByRole('link', { name: 'Открыть статью' }),
      ).not.toBeInTheDocument();
      expect(screen.getByText(url)).toBeInTheDocument();
    },
  );
});

describe('PanelNationHome — edit form', () => {
  it('keeps Сохранить disabled until a field actually changes', async () => {
    const user = userEvent.setup();
    renderHome();
    const save = await openEdit(user);
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText('Имя лидера'), 'X');
    expect(save).toBeEnabled();
  });

  it('PATCHes only the changed fields and closes on success', async () => {
    const bodies = capturePatch({
      ...NATION,
      leader_name: 'Пётр Первый',
    });
    const { onChanged } = renderHome();
    const user = userEvent.setup();
    const save = await openEdit(user);

    const input = screen.getByLabelText('Имя лидера');
    await user.clear(input);
    await user.type(input, 'Пётр Первый');
    await user.click(save);

    await waitFor(() =>
      expect(bodies).toEqual([{ leader_name: 'Пётр Первый' }]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(
      screen.queryByTestId('edit-nation-form'),
    ).not.toBeInTheDocument();
    // The shared success bar reports «Изменения сохранены» (UI Spec 7).
    expect(await screen.findByTestId('notice')).toHaveTextContent(
      'Изменения сохранены',
    );
  });

  it('legacy nation: no capital line/input; a short-name edit patches only short_name', async () => {
    const bodies = capturePatch({
      ...LEGACY_NATION,
      short_name: 'Тестия',
    });
    const { onChanged } = renderHome(LEGACY_NATION);

    // Card: the capital row is hidden and the render is error-free.
    expect(screen.queryByText('Столица')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    const user = userEvent.setup();
    const save = await openEdit(user);
    // The territory block is read-only and the capital-name input is
    // hidden — the server refuses capital_name for a nation without one.
    expect(screen.getByTestId('form-item-provinces')).toBeInTheDocument();
    expect(screen.queryByTestId('capital-line')).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('Название столицы'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('open-province-picker'),
    ).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Краткое название'), 'Тестия');
    await user.click(save);
    await waitFor(() =>
      expect(bodies).toEqual([{ short_name: 'Тестия' }]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('a cleared optional field is sent as an empty string — motto only', async () => {
    const mottoNation: NationDTO = { ...NATION, motto: 'Север помнит всё' };
    const bodies = capturePatch({ ...mottoNation, motto: null });
    renderHome(mottoNation);

    const user = userEvent.setup();
    const save = await openEdit(user);
    await user.clear(screen.getByLabelText('Девиз (необязательно)'));
    await user.click(save);

    await waitFor(() => expect(bodies).toEqual([{ motto: '' }]));
  });

  it('lets a legacy nation rename itself without touching the profile', async () => {
    const bodies = capturePatch({ ...LEGACY_NATION, name: 'Новая Тестия' });
    const { onChanged } = renderHome(LEGACY_NATION);
    const user = userEvent.setup();
    const save = await openEdit(user);

    const nameInput = screen.getByLabelText('Название государства');
    await user.clear(nameInput);
    await user.type(nameInput, 'Новая Тестия');
    // The profile fields were left empty — the nation may still be renamed.
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() =>
      expect(bodies).toEqual([{ name: 'Новая Тестия' }]),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('blocks saving when a previously filled profile field is emptied', async () => {
    const user = userEvent.setup();
    renderHome();
    const save = await openEdit(user);

    await user.clear(screen.getByLabelText('Имя лидера'));
    expect(save).toBeDisabled();
  });

  it('blocks saving when the name is shorter than the rules minimum', async () => {
    const user = userEvent.setup();
    renderHome();
    const save = await openEdit(user);
    // Wait until the rules-driven hint rendered — gating must use it.
    await within(screen.getByTestId('form-item-name')).findByText(
      `от ${RULES.name_min_length} до ${RULES.name_max_length} символов`,
    );

    const nameInput = screen.getByLabelText('Название государства');
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
    renderHome();
    const save = await openEdit(user);

    await user.type(
      screen.getByLabelText('Ссылка на историю государства'),
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
      screen.getByLabelText('Ссылка на историю государства'),
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
    renderHome();
    const save = await openEdit(user);

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
});

describe('PanelNationHome — edit draft memory', () => {
  it('restores typed values on remount and deletes them on «Отмена»', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelNationHome nation={NATION} onChanged={() => {}} />,
    );

    // Type, leave (the panel unmounts like a screen switch) — the
    // draft must survive.
    await openEdit(user);
    await user.type(screen.getByLabelText('Имя лидера'), 'X');
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван ГрозныйX',
    );
    first.unmount();

    const second = renderWithProviders(
      <PanelNationHome nation={NATION} onChanged={() => {}} />,
    );
    await openEdit(user);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван ГрозныйX',
    );

    // «Отмена» deletes the draft — the next visit shows the nation.
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    second.unmount();

    renderWithProviders(
      <PanelNationHome nation={NATION} onChanged={() => {}} />,
    );
    await openEdit(user);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue(
      'Иван Грозный',
    );
  });
});
