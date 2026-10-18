/**
 * PanelCreateNation — the registration window of four tabs.
 *
 * Covers: tab navigation and state retention, rules-driven hints and
 * gating (msw returns non-default numbers — nothing may be hardcoded),
 * the single POST /nations with the whole form's data, Russian field-level
 * error texts with tab badges, and the v2 session draft. Fields without
 * inputs yet (Issue 15) are seeded through the draft — that is the only
 * way to reach an enabled submit for them this issue.
 */

import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UserEvent } from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { writeFormDraft } from '../../../../shared/formDraft';
import { PanelCreateNation } from '../PanelCreateNation';
import {
  fieldToTab,
  mapErrorCodeToField,
} from '../registrationForm';
import {
  goToTab,
  pickProvinces,
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  seedRegistrationDraft,
  SESSION,
} from './helpers';

const NATION = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Testia',
  color_hex: '#e64545',
  owner_player_id: SESSION.player.id,
  province_ids: [1005, 1006, 1007],
  leader_name: 'Иван Грозный',
  leader_title: 'Верховный правитель',
  history_url: 'https://vk.com/@testia-istoriya',
  created_at: '2026-09-27T00:00:00Z',
};

const submitButton = () =>
  screen.getByRole('button', { name: /основать государство/i });

beforeEach(registerDefaultHandlers);

describe('PanelCreateNation — four-tab shell', () => {
  it('the key path: empty start, a full tab tour, then a server error lands on the right tab', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelCreateNation onCreated={() => {}} />,
    );

    // A user with an empty form starts on tab 1 of 4.
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 1 из 4',
    );

    // Walking forward by arrows…
    await user.type(screen.getByLabelText('Название государства'), 'Testia');
    await user.click(screen.getByTestId('step-next'));
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 2 из 4',
    );
    await user.type(screen.getByLabelText('Имя лидера'), 'Иван Грозный');
    await user.click(screen.getByTestId('step-next'));
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 3 из 4',
    );
    await user.type(
      screen.getByLabelText('Ссылка на историю государства'),
      'https://vk.com/@testia-istoriya',
    );
    await user.click(screen.getByTestId('step-next'));
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 4 из 4',
    );

    // …and back by clickable titles — every typed value survives.
    await goToTab(user, 1);
    expect(screen.getByLabelText('Название государства')).toHaveValue(
      'Testia',
    );
    await goToTab(user, 2);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Иван Грозный');
    await goToTab(user, 3);
    expect(screen.getByLabelText('Ссылка на историю государства')).toHaveValue(
      'https://vk.com/@testia-istoriya',
    );
    first.unmount();

    // The remaining required fields have no inputs until Issues 13–15 —
    // a complete v2 draft stands in for them so the submit can fire.
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'History url must point to a VK article', code: 'HISTORY_URL_INVALID' },
          { status: 422 },
        ),
      ),
    );
    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await user.click(submitButton());

    // The error belongs to tab 3: a badge marks its title while tab 1
    // stays open…
    await screen.findByTestId('step-error-3');
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 1 из 4',
    );

    // …and the Russian text waits under the history field on tab 3.
    await goToTab(user, 3);
    expect(
      within(screen.getByTestId('form-item-history-url')).getByText(
        /статью ВКонтакте/,
      ),
    ).toBeInTheDocument();
  });

  it('walks all four tabs via the chevron arrows with disabled ends', async () => {
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    const indicator = screen.getByTestId('step-indicator');

    expect(indicator).toHaveTextContent('Шаг 1 из 4');
    expect(screen.getByTestId('step-prev')).toBeDisabled();
    expect(screen.getByTestId('step-next')).toBeEnabled();
    expect(screen.getByLabelText('Название государства')).toBeInTheDocument();
    expect(
      screen.queryByLabelText('Ссылка на историю государства'),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 2 из 4');
    expect(screen.getByLabelText('Имя лидера')).toBeInTheDocument();

    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 3 из 4');
    expect(
      screen.getByLabelText('Ссылка на историю государства'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Ссылка на гимн')).toBeInTheDocument();

    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 4 из 4');
    expect(screen.getByTestId('step-next')).toBeDisabled();
    expect(screen.getByTestId('form-item-provinces')).toBeInTheDocument();

    await user.click(screen.getByTestId('step-prev'));
    expect(indicator).toHaveTextContent('Шаг 3 из 4');
  });

  it('marks inactive tabs with missing required fields after the first edit', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    // A pristine form shows no badges at all.
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-3')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-4')).not.toBeInTheDocument();

    // One typed field turns the missing-required marks on for the
    // inactive tabs; the active tab is never badged.
    await user.type(screen.getByLabelText('Название государства'), 'T');
    await screen.findByTestId('step-error-2');
    expect(screen.getByTestId('step-error-3')).toBeInTheDocument();
    expect(screen.getByTestId('step-error-4')).toBeInTheDocument();
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();

    // Leaving tab 1 exposes its own mark (short name is still empty).
    await goToTab(user, 2);
    await screen.findByTestId('step-error-1');
  });
});

describe('PanelCreateNation — rules hints', () => {
  it('shows limits and allowed hosts from GET /nations/rules', async () => {
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    // All hint numbers come from the msw body, not from the code.
    expect(
      await screen.findByText(
        `от ${RULES.name_min_length} до ${RULES.name_max_length} символов`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Название государства')).toHaveAttribute(
      'maxlength',
      String(RULES.name_max_length),
    );

    const user = userEvent.setup();
    await goToTab(user, 2);
    expect(
      screen.getByText(
        `от ${RULES.leader_name_min_length} до ${RULES.leader_name_max_length} символов`,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `от ${RULES.leader_title_min_length} до ${RULES.leader_title_max_length} символов`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Имя лидера')).toHaveAttribute(
      'maxlength',
      String(RULES.leader_name_max_length),
    );
    expect(screen.getByLabelText('Должность лидера')).toHaveAttribute(
      'maxlength',
      String(RULES.leader_title_max_length),
    );

    await goToTab(user, 3);
    const historyItem = screen.getByTestId('form-item-history-url');
    expect(historyItem).toHaveTextContent('Поле обязательное');
    expect(historyItem).toHaveTextContent(
      `до ${RULES.history_url_max_length} символов`,
    );
    expect(historyItem).toHaveTextContent(
      `Допустимые домены: ${RULES.history_url_allowed_hosts.join(', ')}`,
    );
    const anthemItem = screen.getByTestId('form-item-anthem-url');
    expect(anthemItem).toHaveTextContent(
      'музыка внутри игры не воспроизводится',
    );
    expect(anthemItem).toHaveTextContent(
      `до ${RULES.anthem_url_max_length} символов`,
    );
    expect(anthemItem).toHaveTextContent(
      `Допустимые домены: ${RULES.anthem_url_allowed_hosts.join(', ')}`,
    );

    await goToTab(user, 4);
    expect(
      screen.getByText(`Нужно выбрать ровно ${RULES.max_provinces}`),
    ).toBeInTheDocument();
  });

  it('stays usable without hints when GET /nations/rules fails', async () => {
    server.use(
      http.get('*/api/v1/nations/rules', () =>
        HttpResponse.json(
          { detail: 'boom', code: 'INTERNAL' },
          { status: 500 },
        ),
      ),
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(NATION, { status: 201 }),
      ),
    );
    seedRegistrationDraft();
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    // Rules failed → no hints and no maxLength anywhere, yet the seeded
    // form still submits (fallback = non-empty checks).
    expect(submitButton()).toBeEnabled();
    await user.click(submitButton());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(NATION));

    expect(screen.queryByText(/символов/)).not.toBeInTheDocument();
    await goToTab(user, 3);
    expect(
      screen.getByLabelText('Ссылка на историю государства'),
    ).not.toHaveAttribute('maxlength');
  });
});

describe('PanelCreateNation — submit', () => {
  it('gates the submit button on the required fields', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelCreateNation onCreated={() => {}} />,
    );
    expect(submitButton()).toBeDisabled();
    first.unmount();

    // A complete seeded draft enables it…
    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    expect(submitButton()).toBeEnabled();

    // …and emptying a required field disables it again.
    await user.clear(screen.getByLabelText('Название государства'));
    expect(submitButton()).toBeDisabled();
  });

  it('requires exactly rules.max_provinces provinces', async () => {
    seedRegistrationDraft({
      provinces: [
        { value: 1005, label: 'Провинция 1005' },
        { value: 1006, label: 'Провинция 1006' },
      ],
    });
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    // Wait for the rules-driven hint so the exact-count gating is in force.
    await screen.findByText(
      `от ${RULES.name_min_length} до ${RULES.name_max_length} символов`,
    );
    expect(submitButton()).toBeDisabled();
  });

  it('sends exactly one POST /nations with trimmed values and null optionals', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/v1/nations', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(NATION, { status: 201 });
      }),
    );
    const onCreated = vi.fn();
    const user = userEvent.setup();
    seedRegistrationDraft({
      name: '  Testia  ',
      shortName: ' Тестия ',
      motto: '  Мы победим  ',
      description: '   ',
      leaderName: '  Иван Грозный ',
      leaderTitle: ' Верховный правитель   ',
      leaderBio: '  ',
      historyUrl: '  https://vk.com/@testia-istoriya ',
      anthemUrl: '  ',
      capitalName: ' Столицево ',
    });
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);
    await user.click(submitButton());

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(NATION));
    expect(bodies).toEqual([
      {
        name: 'Testia',
        short_name: 'Тестия',
        color_hex: '#E64545',
        motto: 'Мы победим',
        description: null,
        flag_id: null,
        province_ids: [1005, 1006, 1007],
        capital_province_id: null,
        capital_name: 'Столицево',
        leader_name: 'Иван Грозный',
        gender: 'male',
        leader_title: 'Верховный правитель',
        leader_bio: null,
        portrait_id: null,
        succession_type: 'elections',
        history_url: 'https://vk.com/@testia-istoriya',
        anthem_url: null,
      },
    ]);
  });
});

describe('PanelCreateNation — tab 1 symbols', () => {
  it('debounced color-check hint, palette swatch fills HEX, flag + upper-case color submit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const bodies: unknown[] = [];
      server.use(
        http.post('*/api/v1/nations/color-check', () =>
          HttpResponse.json({ status: 'TOO_CLOSE' }),
        ),
        http.post('*/api/v1/nations', async ({ request }) => {
          bodies.push(await request.json());
          return HttpResponse.json(NATION, { status: 201 });
        }),
      );
      seedRegistrationDraft({ color: '', flagId: null });
      const user = userEvent.setup({
        advanceTimers: vi.advanceTimersByTime,
      });
      renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

      const hexInput = await screen.findByLabelText('Цвет государства');
      // Wait for the rules so the palette and flag grids render.
      const swatch = await screen.findByTestId('color-swatch-#102030');

      // A typed valid HEX calls color-check only after the debounce.
      fireEvent.change(hexInput, { target: { value: 'a1b2c3' } });
      expect(
        screen.queryByText(/слишком похож/i),
      ).not.toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(
        await screen.findByText(/слишком похож/i),
      ).toBeInTheDocument();

      // A palette click sets the color and the HEX field.
      await user.click(swatch);
      expect(hexInput).toHaveValue(RULES.palette[0]);

      // A flag pick then submit sends flag_id and an upper-case
      // color_hex — the «слишком похож» hint never blocks the button.
      await user.click(screen.getByRole('button', { name: 'flag_stub' }));
      fireEvent.change(hexInput, { target: { value: 'a1b2c3' } });
      await user.click(submitButton());
      await waitFor(() => expect(bodies).toHaveLength(1));
      expect(bodies[0]).toMatchObject({
        flag_id: 'flag_stub',
        color_hex: '#A1B2C3',
      });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('PanelCreateNation — tab 2 leadership', () => {
  it('portrait, gender and a succession card submit their codes; the four cards form one radio group', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/v1/nations', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(NATION, { status: 201 });
      }),
    );
    // All required fields filled except the three picked on tab 2.
    seedRegistrationDraft({ portraitId: null, gender: '', successionType: '' });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);
    await goToTab(user, 2);

    // The grids render once GET /nations/rules has landed.
    await user.click(
      await screen.findByRole('button', { name: 'portrait_stub' }),
    );
    const genderItem = screen.getByTestId('form-item-gender');
    await user.click(
      within(genderItem).getByRole('radio', { name: 'Женский' }),
    );

    // Four cards = one radio group: only one checked at a time, clicks
    // and arrow keys alike (spec order comes from rules.succession_types).
    const successionItem = screen.getByTestId('form-item-succession');
    const cards = within(successionItem).getAllByRole('radio');
    expect(cards).toHaveLength(4);
    expect(cards.map((c) => c.getAttribute('aria-checked'))).toEqual([
      'false',
      'false',
      'false',
      'false',
    ]);
    for (const title of [
      'Демократические выборы',
      'Назначение игроком',
      'Назначение по критериям',
      'Наследование',
    ]) {
      expect(successionItem).toHaveTextContent(title);
    }
    expect(successionItem).toHaveTextContent('Пока без последствий в игре');

    const elections = within(successionItem).getByRole('radio', {
      name: 'Демократические выборы',
    });
    const appointment = within(successionItem).getByRole('radio', {
      name: 'Назначение игроком',
    });
    await user.click(elections);
    expect(elections).toHaveAttribute('aria-checked', 'true');
    await user.click(appointment);
    expect(appointment).toHaveAttribute('aria-checked', 'true');
    expect(elections).toHaveAttribute('aria-checked', 'false');

    // ArrowDown from «Назначение игроком» selects the next card.
    fireEvent.keyDown(appointment, { key: 'ArrowDown' });
    const criteria = within(successionItem).getByRole('radio', {
      name: 'Назначение по критериям',
    });
    expect(criteria).toHaveAttribute('aria-checked', 'true');
    expect(appointment).toHaveAttribute('aria-checked', 'false');

    await user.click(submitButton());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(NATION));
    expect(bodies).toEqual([
      expect.objectContaining({
        portrait_id: 'portrait_stub',
        gender: 'female',
        succession_type: 'criteria',
      }),
    ]);
  });
});

describe('PanelCreateNation — server error mapping', () => {
  it('NAME_TAKEN marks tab 1 while another tab is open; the Russian text waits under the field', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          {
            detail: "Nation name 'Testia' is already taken",
            code: 'NAME_TAKEN',
          },
          { status: 409 },
        ),
      ),
    );
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await goToTab(user, 4);
    await user.click(submitButton());

    // Still on tab 4 — the erroring tab is flagged, not focused.
    await screen.findByTestId('step-error-1');
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 4 из 4',
    );

    await goToTab(user, 1);
    const nameItem = screen.getByTestId('form-item-name');
    expect(
      within(nameItem).getByText('Это название уже занято'),
    ).toBeInTheDocument();
    // The badge is gone now that tab 1 is active…
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();
    // …and editing the field clears the inline error.
    await user.type(screen.getByLabelText('Название государства'), '!');
    expect(
      within(nameItem).queryByText('Это название уже занято'),
    ).not.toBeInTheDocument();
  });

  it('shows LEADER_NAME_INVALID in Russian under the leader name FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'Leader name contains invalid characters', code: 'LEADER_NAME_INVALID' },
          { status: 422 },
        ),
      ),
    );
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await user.click(submitButton());

    await screen.findByTestId('step-error-2');
    await goToTab(user, 2);
    const item = screen.getByTestId('form-item-leader-name');
    expect(
      within(item).getByText(
        `Имя лидера: от ${RULES.leader_name_min_length} до ${RULES.leader_name_max_length} символов, без служебных символов`,
      ),
    ).toBeInTheDocument();
    expect(within(item).queryByText(/invalid characters/i)).toBeNull();
  });

  it.each([
    [
      'PROVINCE_COUNT_OUT_OF_RANGE',
      'Province count 12 is out of range (must be between 1 and 5)',
      /out of range/i,
      'form-item-provinces',
    ],
    [
      'PROVINCE_TAKEN',
      'Province 1003 is already taken',
      /already taken/i,
      'form-item-provinces',
    ],
    [
      'PROVINCE_NOT_FOUND',
      'Province 9999 not found',
      /not found/i,
      'form-item-provinces',
    ],
    [
      'PROVINCE_NOT_LAND',
      'Province 2087 is a sea zone',
      /sea zone/i,
      'form-item-provinces',
    ],
    [
      'STARTING_GROUP_NOT_CONNECTED',
      'Starting provinces are not connected (2 parts)',
      /not connected/i,
      'form-item-provinces',
    ],
    [
      'CAPITAL_NAME_INVALID',
      'Capital name is too short',
      /Название столицы: от \d+ до \d+ символов, без служебных символов/,
      'form-item-capital-name',
    ],
    [
      'CAPITAL_NOT_IN_PROVINCES',
      'Capital province is not among the selected provinces',
      /Столица должна быть одной из выбранных провинций/,
      'form-item-provinces',
    ],
  ])(
    'shows %s on its tab-4 FormItem',
    async (code, detail, pattern, itemTestId) => {
      server.use(
        http.post('*/api/v1/nations', () =>
          HttpResponse.json({ detail, code }, { status: 422 }),
        ),
      );
      seedRegistrationDraft();
      const user = userEvent.setup();
      renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
      await user.click(submitButton());

      await screen.findByTestId('step-error-4');
      await goToTab(user, 4);
      const item = screen.getByTestId(itemTestId);
      expect(within(item).getByText(pattern)).toBeInTheDocument();
    },
  );

  it('shows unmapped codes in the generic banner', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'You already own a nation', code: 'NATION_ALREADY_EXISTS' },
          { status: 409 },
        ),
      ),
    );
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await user.click(submitButton());

    await screen.findByText('Не удалось создать государство');
    expect(screen.getByText(/already own a nation/i)).toBeInTheDocument();
  });
});

describe('PanelCreateNation — province picker', () => {
  const provincesItem = () => screen.getByTestId('form-item-provinces');

  it('opens the picker, returns named chips, submits their ids', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/v1/nations', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(NATION, { status: 201 });
      }),
    );
    // Every required field is seeded except the provinces — the picker
    // completes the form.
    seedRegistrationDraft({ provinces: [] });
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('option'),
      ).toHaveLength(3),
    );
    expect(provincesItem()).toHaveTextContent('Эпсилон');
    expect(provincesItem()).toHaveTextContent('Дзета');
    expect(provincesItem()).toHaveTextContent('Эта');

    await user.click(submitButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ province_ids: [1005, 1006, 1007] });
  });

  it('cancel leaves the form unchanged', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    // Pick the connected triple first.
    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('option'),
      ).toHaveLength(3),
    );

    // Reopen, deselect one province, then cancel — nothing changes.
    await user.click(screen.getByTestId('open-province-picker'));
    await waitFor(() =>
      expect(
        document.querySelectorAll(
          '[data-testid="map-view"] path[data-id]',
        ).length,
      ).toBeGreaterThan(0),
    );
    fireEvent.mouseDown(
      document.querySelector(
        '[data-testid="map-view"] path[data-id="1005"]',
      ) as Element,
      { button: 0, clientX: 5, clientY: 5 },
    );
    fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));
    await screen.findByText(/Выбрано 2 из 3/);
    await user.click(screen.getByRole('button', { name: 'Отмена' }));

    await waitFor(() =>
      expect(
        screen.queryByText(/Выбрано 2 из 3/),
      ).not.toBeInTheDocument(),
    );
    expect(within(provincesItem()).getAllByRole('option')).toHaveLength(3);
  });

  it('removing a chip updates the form state', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('option'),
      ).toHaveLength(3),
    );

    await user.click(
      within(provincesItem()).getByRole('button', {
        name: 'Удалить Эпсилон',
      }),
    );
    const remaining = within(provincesItem()).getAllByRole('option');
    expect(remaining).toHaveLength(2);
    expect(provincesItem()).not.toHaveTextContent('Эпсилон');
    // 2 < RULES.max_provinces — the form notices the missing province.
    expect(submitButton()).toBeDisabled();
  });

  it('keeps the selection when switching tabs', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('option'),
      ).toHaveLength(3),
    );

    await goToTab(user, 1);
    await goToTab(user, 4);
    expect(provincesItem()).toHaveTextContent('Эпсилон');
    expect(provincesItem()).toHaveTextContent('Эта');
  });
});

describe('PanelCreateNation — tab 4 territories', () => {
  const capitalInput = () => screen.getByLabelText('Название столицы');

  /** Reopens the picker on the current form and, optionally, presses
   *  the right button on `capital` before «Готово». */
  async function pickAgain(user: UserEvent, capital?: number) {
    await user.click(screen.getByTestId('open-province-picker'));
    await waitFor(() =>
      expect(
        document.querySelectorAll(
          '[data-testid="map-view"] path[data-id]',
        ).length,
      ).toBeGreaterThan(0),
    );
    if (capital !== undefined) {
      fireEvent(
        document.querySelector(
          `[data-testid="map-view"] path[data-id="${capital}"]`,
        ) as Element,
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true }),
      );
    }
    await user.click(screen.getByRole('button', { name: 'Готово' }));
  }

  it('the capital name follows the marked province and stops after a manual edit', async () => {
    seedRegistrationDraft({ provinces: [], capitalName: '' });
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await goToTab(user, 4);

    // No provinces yet — the default-capital line is hidden.
    expect(screen.queryByTestId('capital-line')).not.toBeInTheDocument();

    // Pick the connected triple and mark Дзета (1006) as capital via
    // the right button inside the picker.
    await user.click(screen.getByTestId('open-province-picker'));
    await waitFor(() =>
      expect(
        document.querySelectorAll(
          '[data-testid="map-view"] path[data-id]',
        ).length,
      ).toBeGreaterThan(0),
    );
    for (const id of [1005, 1006, 1007]) {
      fireEvent.mouseDown(
        document.querySelector(
          `[data-testid="map-view"] path[data-id="${id}"]`,
        ) as Element,
        { button: 0, clientX: 5, clientY: 5 },
      );
      fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));
    }
    fireEvent(
      document.querySelector(
        '[data-testid="map-view"] path[data-id="1006"]',
      ) as Element,
      new MouseEvent('contextmenu', { bubbles: true, cancelable: true }),
    );
    await user.click(screen.getByRole('button', { name: 'Готово' }));

    // After the picker returns: the marked chip, the line and the
    // auto-filled name all say Дзета.
    await waitFor(() => expect(capitalInput()).toHaveValue('Дзета'));
    const capitalLine = screen.getByTestId('capital-line');
    expect(capitalLine).toHaveTextContent('Столица: Дзета');
    expect(capitalLine).not.toHaveTextContent('по умолчанию');

    // Reopen and move the mark to Эта — the name follows.
    await pickAgain(user, 1007);
    await waitFor(() => expect(capitalInput()).toHaveValue('Эта'));
    expect(screen.getByTestId('capital-line')).toHaveTextContent(
      'Столица: Эта',
    );

    // A manual edit pins the name: moving the mark no longer rewrites it.
    await user.clear(capitalInput());
    await user.type(capitalInput(), 'Моя Столица');
    await pickAgain(user, 1005);
    await waitFor(() =>
      expect(screen.getByTestId('capital-line')).toHaveTextContent(
        'Столица: Эпсилон',
      ),
    );
    expect(capitalInput()).toHaveValue('Моя Столица');

    // Clearing the mark → the line falls back to «по умолчанию», and
    // the hand-typed name still is not overwritten.
    await user.click(screen.getByTestId('open-province-picker'));
    await waitFor(() =>
      expect(
        document.querySelectorAll(
          '[data-testid="map-view"] path[data-id]',
        ).length,
      ).toBeGreaterThan(0),
    );
    const path1005 = document.querySelector(
      '[data-testid="map-view"] path[data-id="1005"]',
    ) as Element;
    fireEvent(
      path1005,
      new MouseEvent('contextmenu', { bubbles: true, cancelable: true }),
    );
    await user.click(screen.getByRole('button', { name: 'Готово' }));
    await waitFor(() =>
      expect(screen.getByTestId('capital-line')).toHaveTextContent(
        'Столица: Эпсилон (по умолчанию — первая выбранная)',
      ),
    );
    expect(capitalInput()).toHaveValue('Моя Столица');
  });
});

describe('mapErrorCodeToField', () => {
  it('maps every spec code to its field', () => {
    // Tab 1.
    expect(mapErrorCodeToField('NAME_TAKEN')).toBe('name');
    expect(mapErrorCodeToField('SHORT_NAME_TAKEN')).toBe('shortName');
    expect(mapErrorCodeToField('SHORT_NAME_INVALID')).toBe('shortName');
    expect(mapErrorCodeToField('MOTTO_INVALID')).toBe('motto');
    expect(mapErrorCodeToField('DESCRIPTION_INVALID')).toBe('description');
    expect(mapErrorCodeToField('COLOR_TAKEN')).toBe('color');
    expect(mapErrorCodeToField('COLOR_TOO_CLOSE')).toBe('color');
    expect(mapErrorCodeToField('FLAG_INVALID')).toBe('flagId');
    // Tab 2.
    expect(mapErrorCodeToField('LEADER_NAME_INVALID')).toBe('leaderName');
    expect(mapErrorCodeToField('GENDER_INVALID')).toBe('gender');
    expect(mapErrorCodeToField('LEADER_TITLE_INVALID')).toBe('leaderTitle');
    expect(mapErrorCodeToField('LEADER_BIO_INVALID')).toBe('leaderBio');
    expect(mapErrorCodeToField('PORTRAIT_INVALID')).toBe('portraitId');
    expect(mapErrorCodeToField('SUCCESSION_INVALID')).toBe('successionType');
    // Tab 3.
    expect(mapErrorCodeToField('HISTORY_URL_INVALID')).toBe('historyUrl');
    expect(mapErrorCodeToField('ANTHEM_URL_INVALID')).toBe('anthemUrl');
    // Tab 4.
    for (const code of [
      'PROVINCE_TAKEN',
      'PROVINCE_NOT_FOUND',
      'PROVINCE_COUNT_OUT_OF_RANGE',
      'PROVINCE_NOT_LAND',
      'STARTING_GROUP_NOT_CONNECTED',
    ]) {
      expect(mapErrorCodeToField(code)).toBe('provinces');
    }
    expect(mapErrorCodeToField('CAPITAL_NAME_INVALID')).toBe('capitalName');
    expect(mapErrorCodeToField('CAPITAL_NOT_IN_PROVINCES')).toBe(
      'capitalProvinceId',
    );
    // Unmapped → generic banner.
    expect(mapErrorCodeToField('NATION_ALREADY_EXISTS')).toBeNull();
    expect(mapErrorCodeToField('NATION_NOT_FOUND')).toBeNull();
    expect(mapErrorCodeToField('SOME_UNKNOWN_CODE')).toBeNull();
  });
});

describe('fieldToTab', () => {
  it('assigns every field to its tab', () => {
    for (const field of [
      'name',
      'shortName',
      'color',
      'motto',
      'description',
      'flagId',
    ] as const) {
      expect(fieldToTab(field)).toBe(1);
    }
    for (const field of [
      'leaderName',
      'gender',
      'leaderTitle',
      'leaderBio',
      'portraitId',
      'successionType',
    ] as const) {
      expect(fieldToTab(field)).toBe(2);
    }
    expect(fieldToTab('historyUrl')).toBe(3);
    expect(fieldToTab('anthemUrl')).toBe(3);
    for (const field of [
      'provinces',
      'capitalProvinceId',
      'capitalName',
    ] as const) {
      expect(fieldToTab(field)).toBe(4);
    }
  });
});

describe('PanelCreateNation — draft memory', () => {
  it('restores the typed values after the screen is reopened', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelCreateNation onCreated={() => {}} />,
    );

    await user.type(
      screen.getByLabelText('Название государства'),
      'Черновия',
    );
    await goToTab(user, 2);
    await user.type(screen.getByLabelText('Имя лидера'), 'Черновик');
    first.unmount();

    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    expect(screen.getByLabelText('Название государства')).toHaveValue(
      'Черновия',
    );
    await goToTab(user, 2);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Черновик');
    expect(screen.getByLabelText('Должность лидера')).toHaveValue('');
  });

  it('ignores drafts saved under the old v1 key', async () => {
    writeFormDraft('nation-create', {
      name: 'Старая Черновия',
      color: '#123456',
      chips: [],
      leaderName: 'Старый лидер',
      leaderTitle: '',
      historyUrl: '',
    });
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    expect(await screen.findByLabelText('Название государства')).toHaveValue(
      '',
    );
  });
});
