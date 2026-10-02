/**
 * PanelCreateNation — the two-window wizard.
 *
 * Covers: step navigation and state retention, rules-driven hints and
 * gating (msw returns non-default numbers — nothing may be hardcoded), the
 * single POST /nations with both windows' data, and field-level error
 * mapping where an error on the inactive window marks its title with a
 * Badge instead of auto-switching.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import {
  fieldToStep,
  mapErrorCodeToField,
  PanelCreateNation,
} from '../PanelCreateNation';
import {
  fillStep1,
  fillStep2,
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  SESSION,
} from './helpers';

const NATION = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Testia',
  color_hex: '#e64545',
  owner_player_id: SESSION.player.id,
  province_ids: [1],
  leader_name: 'Иван Грозный',
  leader_title: 'Верховный правитель',
  history_url: 'https://vk.com/@testia-istoriya',
  created_at: '2026-09-27T00:00:00Z',
};

const submitButton = () =>
  screen.getByRole('button', { name: /основать государство/i });

beforeEach(registerDefaultHandlers);

describe('PanelCreateNation — wizard', () => {
  it('starts on step 1 and switches windows via the chevron arrows', async () => {
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    const indicator = screen.getByTestId('step-indicator');
    expect(indicator).toHaveTextContent('Шаг 1 из 2');
    expect(screen.getByTestId('step-prev')).toBeDisabled();
    expect(screen.getByTestId('step-next')).toBeEnabled();
    expect(screen.getByLabelText('Название государства')).toBeInTheDocument();
    expect(
      screen.queryByLabelText('Ссылка на историю государства'),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('step-next'));
    expect(indicator).toHaveTextContent('Шаг 2 из 2');
    expect(screen.getByTestId('step-next')).toBeDisabled();
    expect(screen.getByTestId('step-prev')).toBeEnabled();
    expect(
      screen.getByLabelText('Ссылка на историю государства'),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText('Название государства'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByTestId('step-prev'));
    expect(indicator).toHaveTextContent('Шаг 1 из 2');
    expect(screen.getByLabelText('Название государства')).toBeInTheDocument();
  });

  it('keeps all entered values when switching between windows', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await fillStep1(user);
    await user.click(screen.getByTestId('step-next'));
    await user.type(
      screen.getByLabelText('Ссылка на историю государства'),
      'https://vk.com/@x',
    );

    await user.click(screen.getByTestId('step-prev'));
    expect(screen.getByLabelText('Название государства')).toHaveValue(
      'Testia',
    );
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Иван Грозный');
    expect(screen.getByLabelText('Должность лидера')).toHaveValue(
      'Верховный правитель',
    );

    await user.click(screen.getByTestId('step-next'));
    expect(screen.getByLabelText('Ссылка на историю государства')).toHaveValue(
      'https://vk.com/@x',
    );
  });

  it('shows limits and allowed hosts from GET /nations/rules', async () => {
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    // All hint numbers come from the msw body, not from the code.
    expect(
      await screen.findByText(
        `от ${RULES.name_min_length} до ${RULES.name_max_length} символов`,
      ),
    ).toBeInTheDocument();
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
    expect(
      screen.getByText(
        new RegExp(
          `Нужно выбрать от ${RULES.min_provinces} до ${RULES.max_provinces}`,
        ),
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Название государства')).toHaveAttribute(
      'maxlength',
      String(RULES.name_max_length),
    );
    expect(screen.getByLabelText('Имя лидера')).toHaveAttribute(
      'maxlength',
      String(RULES.leader_name_max_length),
    );
    expect(screen.getByLabelText('Должность лидера')).toHaveAttribute(
      'maxlength',
      String(RULES.leader_title_max_length),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId('step-next'));
    const historyItem = screen.getByTestId('form-item-history-url');
    expect(historyItem).toHaveTextContent('Поле обязательное');
    expect(historyItem).toHaveTextContent(
      `до ${RULES.history_url_max_length} символов`,
    );
    expect(historyItem).toHaveTextContent(
      `Допустимые домены: ${RULES.history_url_allowed_hosts.join(', ')}`,
    );
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
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    await fillStep1(user);
    await fillStep2(user);
    expect(submitButton()).toBeEnabled();
    await user.click(submitButton());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(NATION));

    // Rules failed → no hints and no maxLength anywhere, yet the form worked.
    expect(screen.queryByText(/символов/)).not.toBeInTheDocument();
    expect(
      screen.getByLabelText('Ссылка на историю государства'),
    ).not.toHaveAttribute('maxlength');
  });
});

describe('PanelCreateNation — submit', () => {
  it('gates the submit button on required fields and rules name_min_length', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    expect(submitButton()).toBeDisabled();

    // 'abc' is shorter than the msw name_min_length — a hardcoded ≥3 or ≥1
    // gate would wrongly enable the button here.
    await fillStep1(user, { name: 'abc' });
    await fillStep2(user);
    await screen.findByText(/Допустимые домены/); // rules resolved
    expect(submitButton()).toBeDisabled();

    await user.click(screen.getByTestId('step-prev'));
    await user.type(screen.getByLabelText('Название государства'), 'd');
    // 'abcd' now — enabled on step 1…
    expect(submitButton()).toBeEnabled();

    await user.click(screen.getByTestId('step-next'));
    // …and still enabled on step 2.
    expect(submitButton()).toBeEnabled();
  });

  it('sends exactly one POST /nations with trimmed values from both windows', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/v1/nations', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(NATION, { status: 201 });
      }),
    );
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    await fillStep1(user, {
      name: '  Testia  ',
      leaderName: '  Иван Грозный ',
      leaderTitle: ' Верховный правитель   ',
    });
    await fillStep2(user, '  https://vk.com/@testia-istoriya ');
    // Submit from step 1 — the button works under both windows.
    await user.click(screen.getByTestId('step-prev'));
    await user.click(submitButton());

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(NATION));
    expect(bodies).toEqual([
      {
        name: 'Testia',
        color_hex: '#e64545',
        province_ids: [1],
        leader_name: 'Иван Грозный',
        leader_title: 'Верховный правитель',
        history_url: 'https://vk.com/@testia-istoriya',
      },
    ]);
  });
});

describe('PanelCreateNation — server error mapping', () => {
  it('NAME_TAKEN on step 2 does not switch windows; a badge marks step 1', async () => {
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
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(submitButton());

    // Still on step 2 — the erroring window is flagged, not focused.
    await screen.findByTestId('step-error-1');
    expect(screen.getByTestId('step-indicator')).toHaveTextContent(
      'Шаг 2 из 2',
    );
    expect(screen.queryByTestId('step-error-2')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('step-prev'));
    const nameItem = screen.getByTestId('form-item-name');
    expect(
      within(nameItem).getByText(/already taken/i),
    ).toBeInTheDocument();
    // The badge is gone now that step 1 is active…
    expect(screen.queryByTestId('step-error-1')).not.toBeInTheDocument();
    // …and editing the field clears the inline error.
    await user.type(screen.getByLabelText('Название государства'), '!');
    expect(
      within(nameItem).queryByText(/already taken/i),
    ).not.toBeInTheDocument();
  });

  it('shows LEADER_NAME_INVALID inline on the leader name FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'Leader name contains invalid characters', code: 'LEADER_NAME_INVALID' },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(screen.getByTestId('step-prev'));
    await user.click(submitButton());

    const item = screen.getByTestId('form-item-leader-name');
    await waitFor(() =>
      expect(
        within(item).getByText(/invalid characters/i),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId('form-item-name')).not.toHaveTextContent(
      /invalid characters/i,
    );
  });

  it('shows LEADER_TITLE_INVALID inline on the leader title FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'Leader title is too long', code: 'LEADER_TITLE_INVALID' },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(screen.getByTestId('step-prev'));
    await user.click(submitButton());

    const item = screen.getByTestId('form-item-leader-title');
    await waitFor(() =>
      expect(within(item).getByText(/too long/i)).toBeInTheDocument(),
    );
  });

  it('shows HISTORY_URL_INVALID inline on step 2 and clears it on edit', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'History url must point to a VK article', code: 'HISTORY_URL_INVALID' },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(submitButton());

    const item = screen.getByTestId('form-item-history-url');
    await waitFor(() =>
      expect(within(item).getByText(/VK article/i)).toBeInTheDocument(),
    );
    // Current-step errors render inline only — no badge on step 2…
    expect(screen.queryByTestId('step-error-2')).not.toBeInTheDocument();

    // …but leaving the window flags it.
    await user.click(screen.getByTestId('step-prev'));
    await screen.findByTestId('step-error-2');

    // Editing the field clears both the error and the badge.
    await user.click(screen.getByTestId('step-next'));
    await user.type(
      screen.getByLabelText('Ссылка на историю государства'),
      'x',
    );
    expect(within(item).queryByText(/VK article/i)).not.toBeInTheDocument();
    await user.click(screen.getByTestId('step-prev'));
    expect(screen.queryByTestId('step-error-2')).not.toBeInTheDocument();
  });

  it('shows PROVINCE_COUNT_OUT_OF_RANGE inline on the provinces FormItem', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          {
            detail:
              'Province count 12 is out of range (must be between 1 and 5)',
            code: 'PROVINCE_COUNT_OUT_OF_RANGE',
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(screen.getByTestId('step-prev'));
    await user.click(submitButton());

    const provincesItem = screen.getByTestId('form-item-provinces');
    await waitFor(() =>
      expect(
        within(provincesItem).getByText(/out of range/i),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId('form-item-name')).not.toHaveTextContent(
      /out of range/i,
    );
  });

  it('shows unmapped codes in the generic banner', async () => {
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'You already own a nation', code: 'NATION_ALREADY_EXISTS' },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);
    await fillStep1(user);
    await fillStep2(user);
    await user.click(submitButton());

    await screen.findByText('Не удалось создать государство');
    expect(screen.getByText(/already own a nation/i)).toBeInTheDocument();
  });
});

describe('PanelCreateNation — province chips', () => {
  const provincesItem = () => screen.getByTestId('form-item-provinces');
  // The placeholder disappears once a chip is present — target the input
  // by role inside the provinces FormItem instead.
  const provinceInput = () =>
    within(provincesItem()).getByRole('textbox');
  const removeButtonFor = (id: string) =>
    within(provincesItem()).getByRole('button', { name: `Удалить ${id}` });

  it('removes a chip when its remove button is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await user.type(provinceInput(), '1001{Enter}');
    expect(within(provincesItem()).getByRole('option')).toHaveTextContent(
      '1001',
    );

    await user.click(removeButtonFor('1001'));
    expect(
      within(provincesItem()).queryByRole('option'),
    ).not.toBeInTheDocument();
  });

  it('removes only the clicked chip and submits exactly the remaining ids', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/v1/nations', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(NATION, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await user.type(screen.getByLabelText('Название государства'), 'Testia');
    await user.type(screen.getByLabelText('Имя лидера'), 'Иван Грозный');
    await user.type(
      screen.getByLabelText('Должность лидера'),
      'Верховный правитель',
    );
    await user.type(provinceInput(), '1001{Enter}');
    await user.type(provinceInput(), '1122{Enter}');
    expect(within(provincesItem()).getAllByRole('option')).toHaveLength(2);

    await user.click(removeButtonFor('1001'));

    const remaining = within(provincesItem()).getAllByRole('option');
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toHaveTextContent('1122');
    // Removing a chip must not wipe the other fields.
    expect(screen.getByLabelText('Название государства')).toHaveValue(
      'Testia',
    );
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Иван Грозный');

    await fillStep2(user);
    await user.click(submitButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ province_ids: [1122] });
  });

  it('does not add the same province id twice', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await user.type(provinceInput(), '1001{Enter}');
    await user.type(provinceInput(), '1001{Enter}');

    const chips = within(provincesItem()).getAllByRole('option');
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent('1001');
  });

  it('rejects a non-numeric entry', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await user.type(provinceInput(), 'abc{Enter}');

    expect(provinceInput()).toHaveValue('');
    expect(
      within(provincesItem()).queryByRole('option'),
    ).not.toBeInTheDocument();
  });

  it('keeps the entered chips when switching to window 2 and back', async () => {
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={() => {}} />);

    await user.type(provinceInput(), '1001{Enter}');
    await user.click(screen.getByTestId('step-next'));
    await user.click(screen.getByTestId('step-prev'));

    expect(within(provincesItem()).getByRole('option')).toHaveTextContent(
      '1001',
    );
  });
});

describe('mapErrorCodeToField', () => {
  it('maps every spec code to its FormItem', () => {
    expect(mapErrorCodeToField('NAME_TAKEN')).toBe('name');
    expect(mapErrorCodeToField('COLOR_TAKEN')).toBe('color');
    expect(mapErrorCodeToField('PROVINCE_TAKEN')).toBe('provinces');
    expect(mapErrorCodeToField('PROVINCE_NOT_FOUND')).toBe('provinces');
    expect(mapErrorCodeToField('PROVINCE_COUNT_OUT_OF_RANGE')).toBe(
      'provinces',
    );
    expect(mapErrorCodeToField('LEADER_NAME_INVALID')).toBe('leaderName');
    expect(mapErrorCodeToField('LEADER_TITLE_INVALID')).toBe('leaderTitle');
    expect(mapErrorCodeToField('HISTORY_URL_INVALID')).toBe('historyUrl');
    expect(mapErrorCodeToField('NATION_ALREADY_EXISTS')).toBeNull();
    expect(mapErrorCodeToField('NATION_NOT_FOUND')).toBeNull();
    expect(mapErrorCodeToField('SOME_UNKNOWN_CODE')).toBeNull();
  });
});

describe('fieldToStep', () => {
  it('assigns historyUrl to step 2 and every other field to step 1', () => {
    expect(fieldToStep('historyUrl')).toBe(2);
    for (const field of [
      'name',
      'color',
      'provinces',
      'leaderName',
      'leaderTitle',
    ] as const) {
      expect(fieldToStep(field)).toBe(1);
    }
  });
});
