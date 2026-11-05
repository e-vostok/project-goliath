/**
 * PanelCreateNation — the registration window of four tabs (UI Spec 9.6,
 * unit 8c).
 *
 * Covers: the shared-UI frame (BlockTitle, «ШАГ N ИЗ 4», the numbered
 * tab strip, one block per tab, the «Назад»/«Далее»/«Основать
 * государство» row), tab navigation and state retention, rules-driven
 * counters and hints (msw returns non-default numbers — nothing may be
 * hardcoded), the PUT /applications/me draft save followed by POST
 * /applications/me/submit — a failure keeps the draft, Russian field-level error texts with tab dots, the
 * v2 session draft and the keyboard rule (Enter never submits).
 */

import { Blob as NodeBlob } from 'node:buffer';

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
  APPLICATION_DRAFT,
  APPLICATION_PENDING,
  goToTab,
  pickProvinces,
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  seedRegistrationDraft,
} from './helpers';

const submitButton = () =>
  screen.getByRole('button', { name: /отправить анкету/i });

beforeEach(registerDefaultHandlers);

describe('PanelCreateNation — four-tab shell', () => {
  it('a player without a nation sees no orders block — the badges are nation-gated (unit 7b)', async () => {
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await screen.findByText('Создание государства');

    expect(screen.queryByTestId('orders-block')).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Мои приказы' }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Приказы других игроков' }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Подать приказ' }),
    ).toBeNull();
  });

  it('the key path: empty start, a full tab tour, then a server error lands on the right tab', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelCreateNation onSubmitted={() => {}} />,
    );

    // A user with an empty form starts on tab 1 of 4 under the shared
    // title «СОЗДАНИЕ ГОСУДАРСТВА».
    expect(screen.getByText('Создание государства')).toBeInTheDocument();
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 1 из 4',
    );

    // Walking forward by «Далее →»…
    await user.type(screen.getByLabelText('Полное название'), 'Testia');
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
      screen.getByLabelText('Ссылка на статью с историей государства'),
      'https://vk.com/@testia-istoriya',
    );
    await user.click(screen.getByTestId('step-next'));
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 4 из 4',
    );

    // …and back by clickable titles — every typed value survives.
    await goToTab(user, 1);
    expect(screen.getByLabelText('Полное название')).toHaveValue('Testia');
    await goToTab(user, 2);
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Иван Грозный');
    await goToTab(user, 3);
    expect(
      screen.getByLabelText('Ссылка на статью с историей государства'),
    ).toHaveValue('https://vk.com/@testia-istoriya');
    first.unmount();

    // The remaining required fields have no inputs until Issues 13–15 —
    // a complete v2 draft stands in for them so the submit can fire.
    server.use(
      http.post('*/api/v1/applications/me/submit', () =>
        HttpResponse.json(
          { detail: 'History url must point to a VK article', code: 'HISTORY_URL_INVALID' },
          { status: 422 },
        ),
      ),
    );
    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);
    await user.click(submitButton());

    // The error belongs to tab 3: a dot marks its title while tab 4
    // stays open…
    await screen.findByTestId('step-error-3');
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 4 из 4',
    );

    // …and the Russian text waits under the history field on tab 3.
    await goToTab(user, 3);
    expect(
      within(screen.getByTestId('form-item-history-url')).getByText(
        /Ссылка должна вести/,
      ),
    ).toBeInTheDocument();
  });

  it('shows the four exact tab titles, one block per tab, and the nav row', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    const indicator = screen.getByTestId('step-indicator');

    // The strip carries the exact titles of the UI spec — the titles
    // never truncate (flex 1 1 auto). Each also titles its block, so
    // more than one node may carry it.
    for (const title of [
      'Основные данные и символика',
      'Глава государства',
      'История',
      'Территории',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    }

    expect(indicator).toHaveTextContent('Шаг 1 из 4');
    // Tab 1 hides «← Назад», the right button is «Далее →».
    expect(screen.queryByTestId('step-prev')).not.toBeInTheDocument();
    expect(screen.getByTestId('step-next')).toBeEnabled();
    expect(screen.getByLabelText('Полное название')).toBeInTheDocument();
    expect(
      screen.queryByLabelText('Ссылка на статью с историей государства'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 2 из 4');
    expect(screen.getByTestId('step-prev')).toBeInTheDocument();
    expect(screen.getByLabelText('Имя лидера')).toBeInTheDocument();

    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 3 из 4');
    expect(
      screen.getByLabelText('Ссылка на статью с историей государства'),
    ).toBeInTheDocument();
    // The anthem field is gone from the interface entirely.
    expect(
      screen.queryByLabelText(/гимн/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('form-item-anthem-url'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 4 из 4');
    // On tab 4 the right button is «Отправить анкету», not «Далее →».
    expect(screen.queryByTestId('step-next')).not.toBeInTheDocument();
    expect(submitButton()).toBeInTheDocument();
    expect(screen.getByTestId('form-item-provinces')).toBeInTheDocument();

    await user.click(screen.getByTestId('step-prev'));
    expect(indicator).toHaveTextContent('Шаг 3 из 4');
  });

  it('marks inactive tabs with missing required fields after the first edit', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    // A pristine form shows no dots at all.
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-3')).not.toBeInTheDocument();
    expect(screen.queryByTestId('step-error-4')).not.toBeInTheDocument();

    // One typed field turns the missing-required dots on for the
    // inactive tabs; the active tab is never dotted.
    await user.type(screen.getByLabelText('Полное название'), 'T');
    await screen.findByTestId('step-error-2');
    expect(screen.getByTestId('step-error-3')).toBeInTheDocument();
    expect(screen.getByTestId('step-error-4')).toBeInTheDocument();
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();

    // Leaving tab 1 exposes its own dot (short name is still empty).
    await goToTab(user, 2);
    await screen.findByTestId('step-error-1');
  });
});

describe('PanelCreateNation — field grammar', () => {
  it('«N / M» counters, star only on required fields, no «необязательно»', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    // The counter sits in the label row: «N / M» with the rules limit.
    const nameItem = await screen.findByTestId('form-item-name');
    expect(
      within(nameItem).getByText(`0 / ${RULES.name_max_length}`),
    ).toBeInTheDocument();
    // maxlength comes from the same rules body.
    expect(screen.getByLabelText('Полное название')).toHaveAttribute(
      'maxlength',
      String(RULES.name_max_length),
    );

    // The star marks required fields only: «Полное название *» has it,
    // «Описание» and «Девиз» do not.
    expect(within(nameItem).getByText('*')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('form-item-description')).queryByText('*'),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId('form-item-motto')).queryByText('*'),
    ).not.toBeInTheDocument();

    // Tab 1 order: «Описание» left of «Девиз» (the wider TextArea).
    const description = screen.getByLabelText('Описание');
    const motto = screen.getByLabelText('Девиз');
    expect(
      description.compareDocumentPosition(motto) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // No «необязательно» anywhere, no «до N символов» under a field.
    expect(screen.queryByText(/необязательно/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/до \d+ символов/)).not.toBeInTheDocument();

    await goToTab(user, 2);
    expect(screen.queryByText(/необязательно/i)).not.toBeInTheDocument();
    await goToTab(user, 4);
    // «Название столицы *» is required and carries its star.
    expect(
      within(screen.getByTestId('form-item-capital-name')).getByText('*'),
    ).toBeInTheDocument();
  });

  it('Enter in a one-line field submits nothing; Enter in a textarea adds a line break', async () => {
    let posts = 0;
    server.use(
      http.put('*/api/v1/applications/me', () => {
        posts += 1;
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    const nameInput = await screen.findByLabelText('Полное название');
    await user.click(nameInput);
    await user.keyboard('{Enter}');
    // No POST, no tab switch, focus stays in the field.
    expect(posts).toBe(0);
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 1 из 4',
    );
    expect(nameInput).toHaveFocus();

    const description = screen.getByLabelText('Описание');
    await user.type(description, 'строка{Enter}две');
    expect(description).toHaveValue('строка\nдве');
    expect(posts).toBe(0);
  });
});

describe('PanelCreateNation — rules hints', () => {
  it('history: one field, the helper names the allowed domains from rules', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    await goToTab(user, 3);
    const historyItem = screen.getByTestId('form-item-history-url');
    // One field on the tab — the star and the rules-driven hint.
    expect(within(historyItem).getByText('*')).toBeInTheDocument();
    expect(historyItem).toHaveTextContent(
      `Допустимые домены: ${RULES.history_url_allowed_hosts.join(', ')}`,
    );
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(
      screen.getByLabelText('Ссылка на статью с историей государства'),
    ).toHaveAttribute('maxlength', String(RULES.history_url_max_length));
  });

  it('stays usable without hints when GET /nations/rules fails', async () => {
    server.use(
      http.get('*/api/v1/nations/rules', () =>
        HttpResponse.json(
          { detail: 'boom', code: 'INTERNAL' },
          { status: 500 },
        ),
      ),
      http.post('*/api/v1/applications/me/submit', () =>
        HttpResponse.json(APPLICATION_PENDING),
      ),
    );
    seedRegistrationDraft();
    const onSubmitted = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);

    // Rules failed → no counters and no maxLength anywhere, yet the
    // seeded form still submits (fallback = non-empty checks).
    await goToTab(user, 4);
    expect(submitButton()).toBeEnabled();
    await user.click(submitButton());
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(APPLICATION_PENDING));

    expect(screen.queryByText(/символов/)).not.toBeInTheDocument();
    // No «N / M» counter inside the form block («Шаг 4 из 4» of the
    // title row is outside it and does not count).
    await goToTab(user, 1);
    expect(
      within(screen.getByTestId('create-nation-form')).queryByText(
        /\d+ \/ \d+/,
      ),
    ).not.toBeInTheDocument();
    await goToTab(user, 3);
    expect(
      screen.getByLabelText('Ссылка на статью с историей государства'),
    ).not.toHaveAttribute('maxlength');
  });
});

describe('PanelCreateNation — submit', () => {
  it('gates «Отправить анкету» on the required fields, with the red-dot hint', async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(
      <PanelCreateNation onSubmitted={() => {}} />,
    );
    await goToTab(user, 4);
    expect(submitButton()).toBeDisabled();
    expect(
      screen.getByText(
        'Заполните обязательные поля (отмечены *) на вкладках с красной точкой',
      ),
    ).toBeInTheDocument();
    first.unmount();

    // A complete seeded draft enables it…
    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);
    expect(submitButton()).toBeEnabled();
    expect(
      screen.queryByText(/вкладках с красной точкой/),
    ).not.toBeInTheDocument();

    // …and emptying a required field disables it again.
    await goToTab(user, 1);
    await user.clear(screen.getByLabelText('Полное название'));
    await goToTab(user, 4);
    expect(submitButton()).toBeDisabled();
  });

  it('requires exactly rules.max_provinces provinces', async () => {
    seedRegistrationDraft({
      provinces: [
        { value: 1005, label: 'Провинция 1005' },
        { value: 1006, label: 'Провинция 1006' },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);
    // Wait for the rules-driven «Выбрано N из M» line so the
    // exact-count gating is in force.
    await screen.findByText(`Выбрано 2 из ${RULES.max_provinces}`);
    expect(submitButton()).toBeDisabled();
  });

  it('sends exactly one PUT /applications/me with trimmed values and null optionals — no anthem_url', async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.put('*/api/v1/applications/me', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(APPLICATION_PENDING);
      }),
    );
    const onSubmitted = vi.fn();
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
      capitalName: ' Столицево ',
    });
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);
    await goToTab(user, 4);
    await user.click(submitButton());

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(APPLICATION_PENDING));
    expect(bodies).toEqual([
      {
        name: 'Testia',
        short_name: 'Тестия',
        color_hex: '#E64545',
        motto: 'Мы победим',
        description: null,
        province_ids: [1005, 1006, 1007],
        capital_province_id: null,
        capital_name: 'Столицево',
        leader_name: 'Иван Грозный',
        gender: 'male',
        leader_title: 'Верховный правитель',
        leader_bio: null,
        succession_type: 'elections',
        history_url: 'https://vk.com/@testia-istoriya',
      },
    ]);
    expect(bodies[0]).not.toHaveProperty('anthem_url');
    // 0.12.0 unit 4: no catalog ids ever leave the form.
    expect(bodies[0]).not.toHaveProperty('flag_id');
    expect(bodies[0]).not.toHaveProperty('portrait_id');
    // No notice — the player lands on the application window.
    expect(screen.queryByTestId('notice')).not.toBeInTheDocument();
  });
});

describe('PanelCreateNation — tab 1 symbols', () => {
  it('debounced color-check hint, palette swatch fills HEX, upper-case color submit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const bodies: unknown[] = [];
      server.use(
        http.post('*/api/v1/nations/color-check', () =>
          HttpResponse.json({ status: 'TOO_CLOSE' }),
        ),
        http.put('*/api/v1/applications/me', async ({ request }) => {
          bodies.push(await request.json());
          return HttpResponse.json(APPLICATION_PENDING);
        }),
      );
      seedRegistrationDraft({ color: '' });
      const user = userEvent.setup({
        advanceTimers: vi.advanceTimersByTime,
      });
      renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

      const hexInput = await screen.findByLabelText('Цвет государства');
      // Wait for the rules so the palette grid renders.
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

      // Submit sends an upper-case
      // color_hex — the «слишком похож» hint never blocks the button.
      fireEvent.change(hexInput, { target: { value: 'a1b2c3' } });
      await goToTab(user, 4);
      await user.click(submitButton());
      await waitFor(() => expect(bodies).toHaveLength(1));
      expect(bodies[0]).toMatchObject({
        color_hex: '#A1B2C3',
      });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('PanelCreateNation — tab 2 leadership', () => {
  it('«Пол» is two small icon buttons — Mars first, one active at a time', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 2);

    const genderItem = await screen.findByTestId('form-item-gender');
    const radios = within(genderItem).getAllByRole('radio');
    expect(radios).toHaveLength(2);
    // Mockup «Reg2» order: the Mars spear (male) first, the Venus
    // mirror (female) second.
    expect(radios.map((r) => r.getAttribute('aria-label'))).toEqual([
      'Мужской',
      'Женский',
    ]);
    expect(radios.map((r) => r.getAttribute('aria-checked'))).toEqual([
      'false',
      'false',
    ]);

    const male = within(genderItem).getByRole('radio', {
      name: 'Мужской',
    });
    await user.click(male);
    expect(male).toHaveAttribute('aria-checked', 'true');
    expect(
      within(genderItem).getByRole('radio', { name: 'Женский' }),
    ).toHaveAttribute('aria-checked', 'false');
  });

  it('gender and a succession card submit their codes; the four cards form one radio group', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.put('*/api/v1/applications/me', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
    );
    // All required fields filled except gender and succession on tab 2.
    seedRegistrationDraft({ gender: '', successionType: '' });
    const onSubmitted = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);
    await goToTab(user, 2);

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

    await goToTab(user, 4);
    await user.click(submitButton());
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(APPLICATION_PENDING));
    expect(bodies).toEqual([
      expect.objectContaining({
        gender: 'female',
        succession_type: 'criteria',
      }),
    ]);
  });
});

describe('PanelCreateNation — server error mapping', () => {
  it('NAME_TAKEN marks tab 1 while another tab is open; the Russian text waits under the field', async () => {
    server.use(
      http.post('*/api/v1/applications/me/submit', () =>
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
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
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
    // The dot is gone now that tab 1 is active…
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();
    // …and editing the field clears the inline error.
    await user.type(screen.getByLabelText('Полное название'), '!');
    expect(
      within(nameItem).queryByText('Это название уже занято'),
    ).not.toBeInTheDocument();
  });

  it('shows LEADER_NAME_INVALID in Russian under the leader name field', async () => {
    server.use(
      http.post('*/api/v1/applications/me/submit', () =>
        HttpResponse.json(
          { detail: 'Leader name contains invalid characters', code: 'LEADER_NAME_INVALID' },
          { status: 422 },
        ),
      ),
    );
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);
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

  // The field shows the dictionary text of the code — the English
  // `detail` never reaches the screen (UI Spec 7).
  it.each([
    [
      'PROVINCE_COUNT_OUT_OF_RANGE',
      'Province count 12 is out of range (must be between 1 and 5)',
      'Число выбранных провинций не подходит.',
      'form-item-provinces',
    ],
    [
      'PROVINCE_TAKEN',
      'Province 1003 is already taken',
      'Одна из провинций уже занята другим государством. Выберите другие.',
      'form-item-provinces',
    ],
    [
      'PROVINCE_NOT_FOUND',
      'Province 9999 not found',
      'Такой провинции нет.',
      'form-item-provinces',
    ],
    [
      'PROVINCE_NOT_LAND',
      'Province 2087 is a sea zone',
      'Выбрать можно только сухопутные провинции.',
      'form-item-provinces',
    ],
    [
      'STARTING_GROUP_NOT_CONNECTED',
      'Starting provinces are not connected (2 parts)',
      'Выбранные провинции должны быть связаны между собой.',
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
    'shows %s on its tab-4 field',
    async (code, detail, pattern, itemTestId) => {
      server.use(
        http.post('*/api/v1/applications/me/submit', () =>
          HttpResponse.json({ detail, code }, { status: 422 }),
        ),
      );
      seedRegistrationDraft();
      const user = userEvent.setup();
      renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
      await goToTab(user, 4);
      await user.click(submitButton());

      // The error lands on the OPEN tab — the Russian text shows
      // inline; the dot appears only once another tab is active.
      const item = screen.getByTestId(itemTestId);
      await within(item).findByText(pattern);
      expect(within(item).queryByText(detail)).not.toBeInTheDocument();
      expect(screen.queryByTestId('step-error-4')).not.toBeInTheDocument();
      await goToTab(user, 3);
      await screen.findByTestId('step-error-4');
    },
  );

  it('shows unmapped codes in the generic banner', async () => {
    server.use(
      http.post('*/api/v1/applications/me/submit', () =>
        HttpResponse.json(
          { detail: 'You already own a nation', code: 'NATION_ALREADY_EXISTS' },
          { status: 409 },
        ),
      ),
    );
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);
    await user.click(submitButton());

    await screen.findByText('Не удалось отправить анкету');
    // The English detail never reaches the screen — the dictionary
    // text of NATION_ALREADY_EXISTS does.
    expect(
      screen.getByText('У вас уже есть государство.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/already own a nation/i),
    ).not.toBeInTheDocument();
  });
});

describe('PanelCreateNation — province picker', () => {
  const provincesItem = () => screen.getByTestId('form-item-provinces');

  it('opens the picker, returns named rows, submits their ids', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.put('*/api/v1/applications/me', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
    );
    // Every required field is seeded except the provinces — the picker
    // completes the form.
    seedRegistrationDraft({ provinces: [] });
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('listitem'),
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
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    // Pick the connected triple first.
    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('listitem'),
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
    expect(within(provincesItem()).getAllByRole('listitem')).toHaveLength(3);
  });

  it('removing a row updates the form state', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('listitem'),
      ).toHaveLength(3),
    );

    await user.click(
      within(provincesItem()).getByRole('button', {
        name: 'Убрать Эпсилон',
      }),
    );
    const remaining = within(provincesItem()).getAllByRole('listitem');
    expect(remaining).toHaveLength(2);
    expect(provincesItem()).not.toHaveTextContent('Эпсилон');
    // 2 < RULES.max_provinces — the form notices the missing province.
    expect(submitButton()).toBeDisabled();
  });

  it('keeps the selection when switching tabs', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);

    await pickProvinces(user, [1005, 1006, 1007]);
    await waitFor(() =>
      expect(
        within(provincesItem()).getAllByRole('listitem'),
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
  const provincesItem = () => screen.getByTestId('form-item-provinces');

  /** The ★-marked row leads the list; the rest keep selection order. */
  const rowTexts = () =>
    within(provincesItem())
      .getAllByRole('listitem')
      .map((row) => row.textContent ?? '');

  /** The row that carries `name` — for its own «Сделать столицей». */
  const rowOf = (name: string) =>
    within(provincesItem())
      .getAllByRole('listitem')
      .find((row) => (row.textContent ?? '').includes(name)) as HTMLElement;

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

  it('the capital row is first with «★», «Сделать столицей» moves the mark, and the name follows until a manual edit', async () => {
    seedRegistrationDraft({ provinces: [], capitalName: '' });
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(user, 4);

    // No provinces yet — no rows, the capital-name field still shows.
    expect(
      within(provincesItem()).queryAllByRole('listitem'),
    ).toHaveLength(0);
    expect(provincesItem()).toHaveTextContent('Выбрано 0');

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

    // After the picker returns: Дзета leads with «★», the name
    // auto-fills from it.
    await waitFor(() => expect(capitalInput()).toHaveValue('Дзета'));
    await waitFor(() =>
      expect(rowTexts()[0]).toContain('★ Дзета'),
    );

    // «Сделать столицей» on the Эта row moves the mark — the name follows.
    await user.click(
      within(rowOf('Эта')).getByRole('button', {
        name: 'Сделать столицей',
      }),
    );
    await waitFor(() => expect(capitalInput()).toHaveValue('Эта'));
    await waitFor(() => expect(rowTexts()[0]).toContain('★ Эта'));

    // A manual edit pins the name: moving the mark no longer rewrites it.
    await user.clear(capitalInput());
    await user.type(capitalInput(), 'Моя Столица');
    await user.click(
      within(rowOf('Эпсилон')).getByRole('button', {
        name: 'Сделать столицей',
      }),
    );
    await waitFor(() => expect(rowTexts()[0]).toContain('★ Эпсилон'));
    expect(capitalInput()).toHaveValue('Моя Столица');

    // Clearing the mark → the first selected row is the capital again,
    // and the hand-typed name still is not overwritten.
    await pickAgain(user);
    await waitFor(() => expect(rowTexts()[0]).toContain('★ Эпсилон'));
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
    // Tab 2.
    expect(mapErrorCodeToField('LEADER_NAME_INVALID')).toBe('leaderName');
    expect(mapErrorCodeToField('GENDER_INVALID')).toBe('gender');
    expect(mapErrorCodeToField('LEADER_TITLE_INVALID')).toBe('leaderTitle');
    expect(mapErrorCodeToField('LEADER_BIO_INVALID')).toBe('leaderBio');
    expect(mapErrorCodeToField('SUCCESSION_INVALID')).toBe('successionType');
    // Tab 3 — history only.
    expect(mapErrorCodeToField('HISTORY_URL_INVALID')).toBe('historyUrl');
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
    ] as const) {
      expect(fieldToTab(field)).toBe(1);
    }
    for (const field of [
      'leaderName',
      'gender',
      'leaderTitle',
      'leaderBio',
      'successionType',
    ] as const) {
      expect(fieldToTab(field)).toBe(2);
    }
    expect(fieldToTab('historyUrl')).toBe(3);
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
      <PanelCreateNation onSubmitted={() => {}} />,
    );

    await user.type(
      screen.getByLabelText('Полное название'),
      'Черновия',
    );
    await goToTab(user, 2);
    await user.type(screen.getByLabelText('Имя лидера'), 'Черновик');
    first.unmount();

    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    expect(screen.getByLabelText('Полное название')).toHaveValue(
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
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    expect(await screen.findByLabelText('Полное название')).toHaveValue(
      '',
    );
  });
});

describe('PanelCreateNation — «Отправить анкету» (0.13.0 unit 7a)', () => {
  function bitmap(width: number, height: number) {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => ({ width, height, close: () => {} }) as ImageBitmap),
    );
  }
  const rawPngFile = (name: string) =>
    Object.assign(new NodeBlob(['PNGDATA'], { type: 'image/png' }), {
      name,
    }) as unknown as File;

  /** The flag slot's own file input — see PanelImageUpload tests. */
  function pickFile(slotButton: HTMLElement, file: File) {
    let host: HTMLElement | null = slotButton;
    let input: HTMLInputElement | null = null;
    while (host !== null && input === null) {
      input = host.querySelector('input[type="file"]');
      host = host.parentElement;
    }
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });
  }

  beforeEach(() => {
    bitmap(1920, 1080);
    (URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(
      () => 'blob:mock',
    );
    (URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Picks `file` on the flag slot of tab 1 (register preview →
   *  «Использовать флаг»); returns after the popup closed. */
  async function pickFlag(user: UserEvent, file: File) {
    const slot = await screen.findByRole('button', {
      name: 'Загрузить флаг',
    });
    pickFile(slot, file);
    const popup = await screen.findByTestId('popup-image-upload');
    await user.click(
      within(popup).getByRole('button', { name: 'Использовать флаг' }),
    );
    await waitFor(() =>
      expect(
        screen.queryByTestId('popup-image-upload'),
      ).not.toBeInTheDocument(),
    );
  }

  it('runs draft PUT → image uploads → submit, in that order', async () => {
    const calls: string[] = [];
    server.use(
      http.put('*/api/v1/applications/me', () => {
        calls.push('draft');
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
      http.put('*/api/v1/applications/me/images/flag', () => {
        calls.push('flag');
        return HttpResponse.json({
          kind: 'flag',
          url: '/i/f/full',
          thumb_url: '/i/f/thumb',
        });
      }),
      http.post('*/api/v1/applications/me/submit', () => {
        calls.push('submit');
        return HttpResponse.json(APPLICATION_PENDING);
      }),
    );
    const onSubmitted = vi.fn();
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);

    await pickFlag(user, rawPngFile('flag.png'));
    await goToTab(user, 4);
    await user.click(submitButton());

    await waitFor(() =>
      expect(onSubmitted).toHaveBeenCalledWith(APPLICATION_PENDING),
    );
    expect(calls).toEqual(['draft', 'flag', 'submit']);
  });

  it('a failed upload keeps the draft, marks its own tab, and the same button retries', async () => {
    const calls: string[] = [];
    let flagFails = 1;
    server.use(
      http.put('*/api/v1/applications/me', () => {
        calls.push('draft');
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
      http.put('*/api/v1/applications/me/images/flag', () => {
        calls.push('flag');
        if (flagFails-- > 0) {
          return HttpResponse.json(
            { detail: 'too large', code: 'IMAGE_TOO_LARGE' },
            { status: 413 },
          );
        }
        return HttpResponse.json({
          kind: 'flag',
          url: '/i/f/full',
          thumb_url: '/i/f/thumb',
        });
      }),
      http.post('*/api/v1/applications/me/submit', () => {
        calls.push('submit');
        return HttpResponse.json(APPLICATION_PENDING);
      }),
    );
    const onSubmitted = vi.fn();
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onSubmitted={onSubmitted} />);

    await pickFlag(user, rawPngFile('flag.png'));
    await goToTab(user, 4);
    await user.click(submitButton());

    // The upload failed: the submit never ran, tab 1 is marked and
    // its slot carries the Russian text — the draft stayed (PUT ok).
    await waitFor(() => expect(calls).toEqual(['draft', 'flag']));
    await screen.findByTestId('step-error-1');
    expect(onSubmitted).not.toHaveBeenCalled();
    await goToTab(user, 1);
    expect(
      screen.getByText(/Сожмите картинку или выберите другую/),
    ).toBeInTheDocument();

    // The same button repeats the whole sequence — now it lands.
    await goToTab(user, 4);
    await user.click(submitButton());
    await waitFor(() =>
      expect(onSubmitted).toHaveBeenCalledWith(APPLICATION_PENDING),
    );
    expect(calls).toEqual(['draft', 'flag', 'draft', 'flag', 'submit']);
  });

  it('the tab-4 note names the reservation window («на N ч», «на сутки» at 24) and keeps its own height (13a)', async () => {
    seedRegistrationDraft();
    const first = renderWithProviders(
      <PanelCreateNation onSubmitted={() => {}} />,
    );
    await goToTab(await userEvent.setup(), 4);
    // «Выбрано N из M» proves the rules arrived — the note reads hours.
    await screen.findByText(`Выбрано 3 из ${RULES.max_provinces}`);

    const note = screen.getByTestId('reservation-note');
    expect(note).toHaveTextContent(
      `После отправки анкеты, территория бронируется за вами на ${RULES.application.review_hours} ч`,
    );
    // The note keeps its own height at the input's top edge — never
    // stretched to the field-plus-hint column (13a, stray bottom gap).
    expect(note).toHaveStyle('align-self: flex-start');
    expect(note.parentElement).toHaveStyle('align-items: flex-start');
    first.unmount();

    // 24 h reads «на сутки».
    server.use(
      http.get('*/api/v1/nations/rules', () =>
        HttpResponse.json({
          ...RULES,
          application: { ...RULES.application, review_hours: 24 },
        }),
      ),
    );
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    await goToTab(await userEvent.setup(), 4);
    await screen.findByText(`Выбрано 3 из ${RULES.max_provinces}`);
    expect(screen.getByTestId('reservation-note')).toHaveTextContent(
      'После отправки анкеты, территория бронируется за вами на сутки',
    );
  });

  it('the tab-4 footer: full button labels, flexShrink: 0, the hint on its own row (13a)', async () => {
    const first = renderWithProviders(
      <PanelCreateNation onSubmitted={() => {}} />,
    );
    // Tabs 1–3: no hint row at all — nothing leaves a gap.
    expect(screen.queryByTestId('step-hint')).toBeNull();
    first.unmount();

    seedRegistrationDraft();
    renderWithProviders(<PanelCreateNation onSubmitted={() => {}} />);
    const user = userEvent.setup();
    await goToTab(user, 4);

    const row = screen.getByTestId('step-buttons');
    const prev = screen.getByTestId('step-prev');
    const submit = screen.getByRole('button', { name: 'Отправить анкету' });
    // Both labels render in full — the buttons never shrink or clip.
    expect(prev).toHaveTextContent('← Назад');
    expect(submit).toHaveTextContent('Отправить анкету');
    expect(prev).toHaveStyle('flex-shrink: 0');
    expect(submit).toHaveStyle('flex-shrink: 0');
    expect(row).toHaveStyle('justify-content: space-between');
    // The hint is its own row above the buttons, not a sibling
    // stealing their width.
    const hint = screen.getByTestId('step-hint');
    expect(hint).toHaveTextContent(
      'Анкета уйдёт на рассмотрение администратору',
    );
    expect(row.contains(hint)).toBe(false);
    expect(within(row).queryByText(/Анкета уйдёт/)).toBeNull();
  });
});

describe('PanelCreateNation — the server draft (0.13.0 unit 7a)', () => {
  const returnedDraft = {
    ...APPLICATION_DRAFT,
    draft_reason: 'returned' as const,
    return_comment: 'Ссылка на историю ведёт на пустую страницу.',
    submissions: 1,
  };

  it('fills the form from the draft — it wins over the session copy — and shows the returned plate', async () => {
    // A stale local draft must lose to the server's.
    seedRegistrationDraft({ name: 'Локальная Черновия' });
    renderWithProviders(
      <PanelCreateNation draft={returnedDraft} onSubmitted={() => {}} />,
    );

    const plate = await screen.findByTestId('application-returned-plate');
    expect(plate).toHaveTextContent('Анкета возвращена администратором');
    expect(plate).toHaveTextContent(
      '«Ссылка на историю ведёт на пустую страницу.»',
    );

    expect(screen.getByLabelText('Полное название')).toHaveValue('Testia');
    await goToTab(await userEvent.setup(), 4);
    const provincesItem = screen.getByTestId('form-item-provinces');
    expect(provincesItem).toHaveTextContent('Эпсилон');
    expect(provincesItem).toHaveTextContent('Эта');
    expect(screen.getByLabelText('Название столицы')).toHaveValue(
      'Столицево',
    );
    // The draft was complete — the submit is armed right away.
    expect(submitButton()).toBeEnabled();
  });
});

describe('PanelCreateNation — the state changed elsewhere (audit of PR 267)', () => {
  it('a 409 APPLICATION_NOT_EDITABLE refreshes the application — no banner', async () => {
    // The draft went PENDING in another window/device: instead of the
    // generic banner the shell refetches and moves to «Анкета».
    server.use(
      http.put('*/api/v1/applications/me', () =>
        HttpResponse.json(
          {
            detail: 'Application is not editable',
            code: 'APPLICATION_NOT_EDITABLE',
          },
          { status: 409 },
        ),
      ),
    );
    const onRefresh = vi.fn();
    const onSubmitted = vi.fn();
    seedRegistrationDraft();
    const user = userEvent.setup();
    renderWithProviders(
      <PanelCreateNation onSubmitted={onSubmitted} onRefresh={onRefresh} />,
    );
    await goToTab(user, 4);
    await user.click(submitButton());

    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(
      screen.queryByText('Не удалось отправить анкету'),
    ).not.toBeInTheDocument();
  });
});
