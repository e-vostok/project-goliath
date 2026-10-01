/**
 * PanelNationHome — the nation profile cells and the edit form.
 *
 * Covers: leader/title/history SimpleCells (with «не указано» for legacy
 * nations), the https-only history link, the PATCH that must carry only
 * changed fields, and inline error mapping inside the edit form.
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
  name: 'Testia',
  color_hex: '#e64545',
  owner_player_id: SESSION.player.id,
  province_ids: [1, 2],
  leader_name: 'Иван Грозный',
  leader_title: 'Верховный правитель',
  history_url: 'https://vk.com/@testia-istoriya',
  created_at: '2026-09-27T00:00:00Z',
};

const LEGACY_NATION: NationDTO = {
  ...NATION,
  leader_name: null,
  leader_title: null,
  history_url: null,
};

function renderHome(nation: NationDTO = NATION) {
  const onChanged = vi.fn();
  const onDeleteRequest = vi.fn();
  renderWithProviders(
    <PanelNationHome
      nation={nation}
      onChanged={onChanged}
      onDeleteRequest={onDeleteRequest}
    />,
  );
  return { onChanged, onDeleteRequest };
}

async function openEdit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Изменить' }));
  return screen.getByRole('button', { name: 'Сохранить' });
}

beforeEach(registerDefaultHandlers);

describe('PanelNationHome — profile cells', () => {
  it('renders leader, title and a safe external history link', () => {
    renderHome();
    expect(screen.getByText('Иван Грозный')).toBeInTheDocument();
    expect(screen.getByText('Верховный правитель')).toBeInTheDocument();

    const link = screen.getByRole('link', { name: 'Открыть статью' });
    expect(link).toHaveAttribute('href', NATION.history_url);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('shows «не указано» three times for a legacy (null-profile) nation', () => {
    renderHome(LEGACY_NATION);
    expect(screen.getAllByText('не указано')).toHaveLength(3);
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
    const bodies: unknown[] = [];
    server.use(
      http.patch('*/api/v1/nations/me', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({
          ...NATION,
          leader_name: 'Пётр Первый',
        });
      }),
    );
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
  });

  it('lets a legacy nation rename itself without touching the profile', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.patch('*/api/v1/nations/me', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ ...LEGACY_NATION, name: 'Новая Тестия' });
      }),
    );
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
    await within(screen.getByTestId('form-item-edit-name')).findByText(
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

    const item = screen.getByTestId('form-item-edit-history-url');
    await waitFor(() =>
      expect(within(item).getByText(/VK article/i)).toBeInTheDocument(),
    );
    // Editing the field clears the inline error.
    await user.type(
      screen.getByLabelText('Ссылка на историю государства'),
      'y',
    );
    expect(within(item).queryByText(/VK article/i)).not.toBeInTheDocument();
  });

  it('falls back to the generic banner for errors outside the edit form', async () => {
    server.use(
      http.patch('*/api/v1/nations/me', () =>
        HttpResponse.json(
          { detail: 'Province 3 is taken', code: 'PROVINCE_TAKEN' },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderHome();
    const save = await openEdit(user);

    await user.type(screen.getByLabelText('Должность лидера'), 'X');
    await user.click(save);

    await screen.findByText('Не удалось обновить государство');
    expect(screen.getByText(/Province 3 is taken/i)).toBeInTheDocument();
  });
});
