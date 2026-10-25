/**
 * «Государства» section (0.11.0 units 8a/8b): the list renders from
 * GET /admin/nations with a «Править» per row, «Создать государство»
 * opens the create page (screen 03c) whose submit stays disabled
 * until the owner, every mandatory field and at least one province
 * are set, a click on a chip moves it to the front as the capital,
 * a server refusal lands next to its field, and a success notices +
 * returns to the list. The edit page (screen 03b) loads
 * GET /admin/nations/{id}, keeps «Сохранить» disabled until a field
 * changes, sends only the changed fields, shows a refusal next to
 * its field, and a success returns to the list.
 *
 * msw stands at the HTTP boundary — the real api-client does the
 * requests.
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { ThemeProvider } from '../../shared/ui/theme';
import { AdminApp } from '../AdminApp';
import { clearSession } from '../session';

const LINK_TOKEN = 'one-time-link-abc123';

const CLOCK_DTO = {
  current_turn: 1,
  game_date: '2040-01-01',
  game_date_text: 'январь 2040',
  next_tick_at: '25.10.2026 00:00:00',
};

const NATIONS = {
  items: [
    {
      id: 'n-1',
      short_name: 'Синдикат',
      name: 'Северный Синдикат',
      flag_id: 'flag_placeholder_1',
      owner_vk_user_id: 100000001,
      owner_name: 'Алексей Морозов',
      provinces_count: 6,
      capital_name: 'Мурманск',
    },
    {
      id: 'n-2',
      short_name: 'Лига',
      name: 'Балтийская Лига',
      flag_id: null,
      owner_vk_user_id: 100000002,
      owner_name: null,
      provinces_count: 4,
      capital_name: 'Рига',
    },
  ],
  total: 2,
};

const RULES = {
  name_min_length: 3,
  name_max_length: 60,
  short_name_min_length: 2,
  short_name_max_length: 20,
  motto_max_length: 50,
  description_max_length: 200,
  leader_name_min_length: 2,
  leader_name_max_length: 60,
  leader_title_min_length: 2,
  leader_title_max_length: 60,
  leader_bio_max_length: 2000,
  capital_name_min_length: 2,
  capital_name_max_length: 40,
  history_url_max_length: 2000,
  history_url_allowed_hosts: ['vk.com'],
  anthem_url_max_length: 2000,
  anthem_url_allowed_hosts: [],
  min_provinces: 1,
  max_provinces: 5,
  palette: [],
  flags: [{ id: 'flag_placeholder_1', url: '/f.png' }],
  portraits: [{ id: 'portrait_placeholder_1', url: '/p.png' }],
  genders: ['male', 'female'],
  succession_types: ['elections', 'appointment', 'criteria', 'inheritance'],
};

const PLAYERS = {
  items: [
    {
      vk_user_id: 100000002,
      display_name: 'Мария Волкова',
      nation_short_name: null,
      created_at: '2026-10-21 00:00:03',
      is_admin: false,
    },
  ],
  total: 1,
};

const PROVINCES = {
  items: [
    { id: 1001, name: 'Генуя', nation_id: null, nation_short_name: null },
    { id: 1002, name: 'Специя', nation_id: null, nation_short_name: null },
    { id: 1003, name: 'Савона', nation_id: null, nation_short_name: null },
  ],
  total: 3,
};

const CREATED = {
  id: 'n-new',
  short_name: 'Лигурия',
  name: 'Лигурийская Республика',
  flag_id: 'flag_placeholder_1',
  owner_vk_user_id: 100000002,
  owner_name: 'Мария Волкова',
  provinces_count: 1,
  capital_name: 'Генуя',
};

/** GET /admin/nations/n-1 — the edit page's seed (screen 03b). */
const NATION_DETAIL = {
  id: 'n-1',
  owner_vk_user_id: 100000001,
  owner_name: 'Алексей Морозов',
  capital_province_id: 42,
  provinces_count: 6,
  name: 'Северный Синдикат',
  short_name: 'Синдикат',
  color_hex: '#1A2B3C',
  motto: '«Север помнит всё»',
  description: 'Торговая федерация.',
  leader_name: 'Алексей Морозов',
  leader_title: 'Председатель Совета',
  gender: 'male',
  succession_type: 'appointment',
  leader_bio: 'Бывший начальник порта.',
  history_url: 'https://vk.com/@sever-history',
  capital_name: 'Мурманск',
};

interface Counters {
  nations: number;
  create: number;
  patch: number;
  patchBody: Record<string, unknown> | null;
  colorCheck: number;
}

function allowSection({
  createAnswer,
  patchAnswer,
}: {
  createAnswer?: { status: number; body: { detail: string; code: string } };
  patchAnswer?: { status: number; body: { detail: string; code: string } };
} = {}): Counters {
  const counters: Counters = {
    nations: 0,
    create: 0,
    patch: 0,
    patchBody: null,
    colorCheck: 0,
  };
  server.use(
    http.post('*/api/v1/admin/session', () =>
      HttpResponse.json({
        access_token: 'panel-session-jwt-xyz',
        expires_in_seconds: 3600,
      }),
    ),
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/admin/overview', () => HttpResponse.json([])),
    http.get('*/api/v1/admin/tick-log', () => HttpResponse.json([])),
    http.get('*/api/v1/nations/rules', () => HttpResponse.json(RULES)),
    http.post('*/api/v1/admin/nations/color-check', () => {
      counters.colorCheck += 1;
      return HttpResponse.json({ status: 'OK' });
    }),
    http.get('*/api/v1/admin/nations/n-1', () =>
      HttpResponse.json(NATION_DETAIL),
    ),
    http.patch('*/api/v1/admin/nations/n-1', async ({ request }) => {
      counters.patch += 1;
      counters.patchBody = (await request.json()) as Record<string, unknown>;
      if (patchAnswer !== undefined) {
        return HttpResponse.json(patchAnswer.body, {
          status: patchAnswer.status,
        });
      }
      return HttpResponse.json({
        ...NATION_DETAIL,
        ...counters.patchBody,
      });
    }),
    http.get('*/api/v1/admin/nations', () => {
      counters.nations += 1;
      return HttpResponse.json(NATIONS);
    }),
    http.get('*/api/v1/admin/provinces', () => HttpResponse.json(PROVINCES)),
    http.get('*/api/v1/admin/players', () => HttpResponse.json(PLAYERS)),
    http.post('*/api/v1/admin/nations', () => {
      counters.create += 1;
      if (createAnswer !== undefined) {
        return HttpResponse.json(createAnswer.body, {
          status: createAnswer.status,
        });
      }
      return HttpResponse.json(CREATED);
    }),
  );
  return counters;
}

function renderPanel() {
  return render(
    <ThemeProvider listenVkScheme={false}>
      <AdminApp />
    </ThemeProvider>,
  );
}

/** Enter through the one-time link, then route to «Государства». */
async function enterSection() {
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();
  window.location.hash = '#/nations';
  await screen.findByTestId('nations-table');
}

/** Reach the create page from the list. */
async function enterCreate() {
  await enterSection();
  fireEvent.click(screen.getByTestId('nations-create-open'));
  await screen.findByTestId('nation-create-submit');
}

/** Pick the suggested owner from the dropdown. */
async function pickOwner() {
  fireEvent.focus(screen.getByTestId('nation-owner-input'));
  const option = await screen.findByTestId('owner-option-0');
  fireEvent.mouseDown(option);
}

/** Fill every mandatory field with valid values. */
async function fillMandatory() {
  fireEvent.change(screen.getByLabelText('Полное название'), {
    target: { value: 'Лигурийская Республика' },
  });
  fireEvent.change(screen.getByLabelText('Краткое название'), {
    target: { value: 'Лигурия' },
  });
  fireEvent.change(screen.getByTestId('nf-color-input'), {
    target: { value: '#8A5FBF' },
  });
  fireEvent.change(screen.getByLabelText('Имя лидера'), {
    target: { value: 'Мария Волкова' },
  });
  fireEvent.change(screen.getByLabelText('Должность лидера'), {
    target: { value: 'Дож' },
  });
  fireEvent.change(screen.getByTestId('nf-gender-select'), {
    target: { value: 'female' },
  });
  fireEvent.change(screen.getByTestId('nf-succession-select'), {
    target: { value: 'elections' },
  });
  fireEvent.change(screen.getByLabelText('Ссылка на историю (статья ВК)'), {
    target: { value: 'https://vk.com/@liguria-history' },
  });
}

/** Pick the first province suggestion. */
async function pickProvince() {
  fireEvent.focus(screen.getByTestId('nation-province-input'));
  const option = await screen.findByTestId('province-option-0');
  fireEvent.mouseDown(option);
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('renders the list from GET /admin/nations', async () => {
  allowSection();
  await enterSection();

  const table = screen.getByTestId('nations-table');
  expect(table).toHaveTextContent('Синдикат');
  expect(table).toHaveTextContent('Северный Синдикат');
  expect(table).toHaveTextContent('Алексей Морозов');
  expect(table).toHaveTextContent('VK 100000002');
  expect(table).toHaveTextContent('Мурманск');
  expect(screen.getByTestId('nations-shown')).toHaveTextContent(
    'Показано 2 из 2',
  );
  // Unit 8b adds «Править» per row; deletion is still 8c's.
  expect(screen.getAllByText('Править')).toHaveLength(2);
  expect(screen.queryByText(/Удалить/)).not.toBeInTheDocument();
});

it('the submit stays disabled until the form is complete', async () => {
  allowSection();
  await enterCreate();

  const submit = screen.getByTestId('nation-create-submit');
  expect(submit).toBeDisabled();

  await fillMandatory();
  expect(submit).toBeDisabled(); // no owner, no province yet

  await pickOwner();
  await waitFor(() =>
    expect(screen.getByTestId('nation-owner-hint')).toHaveTextContent(
      'VK ID 100000002 · государства нет — можно создать.',
    ),
  );
  expect(submit).toBeDisabled(); // provinces still missing

  await pickProvince();
  await waitFor(() => expect(submit).toBeEnabled());
});

it('the first chip is the capital and a click moves another there', async () => {
  allowSection();
  await enterCreate();

  await pickProvince(); // Генуя → chip 1, capital
  await screen.findByTestId('province-chip-1001');
  expect(screen.getByTestId('province-chip-1001')).toHaveTextContent(
    '★ столица',
  );

  // Pick the second suggestion: after removing Генуя from the
  // available list the first remaining option is Специя.
  fireEvent.focus(screen.getByTestId('nation-province-input'));
  fireEvent.mouseDown(await screen.findByTestId('province-option-0'));
  await screen.findByTestId('province-chip-1002');

  // Clicking Специя makes it the capital (the first chip).
  fireEvent.click(screen.getByTestId('province-capital-1002'));
  const chips = screen.getByTestId('province-chips');
  expect(chips.firstElementChild).toHaveTextContent('Специя');
  expect(chips.firstElementChild).toHaveTextContent('★ столица');
  expect(screen.getByTestId('province-chip-1001')).not.toHaveTextContent(
    'столица',
  );
});

it('a server refusal lands next to its field', async () => {
  allowSection({
    createAnswer: {
      status: 409,
      body: { detail: 'short name taken', code: 'SHORT_NAME_TAKEN' },
    },
  });
  await enterCreate();
  await pickOwner();
  await fillMandatory();
  await pickProvince();
  await waitFor(() =>
    expect(screen.getByTestId('nation-create-submit')).toBeEnabled(),
  );

  fireEvent.click(screen.getByTestId('nation-create-submit'));

  await screen.findByText('Это краткое название уже занято');
  // The create page stays open — the administrator can fix the field.
  expect(screen.getByTestId('nation-create-submit')).toBeInTheDocument();
});

it('a success notices and returns to the list', async () => {
  const counters = allowSection();
  await enterCreate();
  await pickOwner();
  await fillMandatory();
  await pickProvince();
  await waitFor(() =>
    expect(screen.getByTestId('nation-create-submit')).toBeEnabled(),
  );

  fireEvent.click(screen.getByTestId('nation-create-submit'));

  await waitFor(() => expect(counters.create).toBe(1));
  await screen.findByText('Государство «Лигурия» создано.');
  // Back on the list — reloaded (a second GET /admin/nations).
  await screen.findByTestId('nations-table');
  await waitFor(() => expect(counters.nations).toBe(2));
});

/* ---------------------------------------------------------------- */
/* The edit page (screen 03b, unit 8b).                              */
/* ---------------------------------------------------------------- */

/** Reach the edit page for nation n-1 from the list. */
async function enterEdit() {
  await enterSection();
  fireEvent.click(screen.getByTestId('nation-edit-n-1'));
  await screen.findByTestId('nation-edit-submit');
}

it('the edit page loads the nation and keeps Сохранить disabled', async () => {
  allowSection();
  await enterEdit();

  // Breadcrumb «Государства / Синдикат», all fields seeded.
  expect(screen.getByTestId('nation-edit-back')).toHaveTextContent(
    'Государства',
  );
  expect(screen.getByLabelText('Полное название')).toHaveValue(
    'Северный Синдикат',
  );
  expect(screen.getByLabelText('Краткое название')).toHaveValue('Синдикат');
  expect(screen.getByLabelText('Столица')).toHaveValue('Мурманск');

  const submit = screen.getByTestId('nation-edit-submit');
  expect(submit).toBeDisabled(); // nothing changed yet
});

it('sends only the changed fields', async () => {
  const counters = allowSection();
  await enterEdit();

  fireEvent.change(screen.getByLabelText('Девиз'), {
    target: { value: 'Новый девиз' },
  });
  await waitFor(() =>
    expect(screen.getByTestId('nation-edit-submit')).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId('nation-edit-submit'));

  await waitFor(() => expect(counters.patch).toBe(1));
  expect(counters.patchBody).toEqual({ motto: 'Новый девиз' });
});

it('an unchanged colour sends no colour-check and no patch field', async () => {
  const counters = allowSection();
  await enterEdit();

  // Retype the same colour (a lower-case equivalent counts as unchanged).
  fireEvent.change(screen.getByTestId('ef-color-input'), {
    target: { value: '#1a2b3c' },
  });
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(counters.colorCheck).toBe(0);

  // Still nothing to save — the colour did not change.
  expect(screen.getByTestId('nation-edit-submit')).toBeDisabled();
  expect(counters.patch).toBe(0);
});

it('a server refusal lands next to its field', async () => {
  allowSection({
    patchAnswer: {
      status: 409,
      body: { detail: 'name taken', code: 'NAME_TAKEN' },
    },
  });
  await enterEdit();

  fireEvent.change(screen.getByLabelText('Полное название'), {
    target: { value: 'Чужое название' },
  });
  await waitFor(() =>
    expect(screen.getByTestId('nation-edit-submit')).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId('nation-edit-submit'));

  await screen.findByText('Это название уже занято');
  expect(screen.getByTestId('nation-edit-submit')).toBeInTheDocument();
});

it('a success notices and returns to the list', async () => {
  const counters = allowSection();
  await enterEdit();

  fireEvent.change(screen.getByLabelText('Краткое название'), {
    target: { value: 'Синд' },
  });
  await waitFor(() =>
    expect(screen.getByTestId('nation-edit-submit')).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId('nation-edit-submit'));

  await waitFor(() => expect(counters.patch).toBe(1));
  await screen.findByText('Данные государства «Синд» сохранены.');
  await screen.findByTestId('nations-table');
  await waitFor(() => expect(counters.nations).toBe(2));
});
