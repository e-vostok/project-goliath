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
      owner_vk_user_id: 100000001,
      owner_name: 'Алексей Морозов',
      provinces_count: 6,
      capital_name: 'Мурманск',
      flag_thumb_url: '/api/v1/images/aa11/thumb',
    },
    {
      id: 'n-2',
      short_name: 'Лига',
      name: 'Балтийская Лига',
      owner_vk_user_id: 100000002,
      owner_name: null,
      provinces_count: 4,
      capital_name: 'Рига',
      flag_thumb_url: null,
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
  owner_vk_user_id: 100000002,
  owner_name: 'Мария Волкова',
  provinces_count: 1,
  capital_name: 'Генуя',
};

/** The delete-preview answer — the screen-03d popup's seed. */
const NATION_DELETE_PREVIEW = {
  nation_id: 'n-2',
  short_name: 'Лига',
  name: 'Балтийская Лига',
  owner_vk_user_id: 100000002,
  owner_name: null,
  provinces: [
    { id: 101, name: 'Рига' },
    { id: 102, name: 'Юрмала' },
    { id: 103, name: 'Лиепая' },
    { id: 104, name: 'Вентспилс' },
  ],
  consequences: [
    {
      code: 'scheduled_actions',
      text: 'запланированных действий государства: 1 — они останутся без государства',
    },
    {
      code: 'ownership_journal',
      text: 'в журнал владения карты запишутся 4 освобождения провинций',
    },
  ],
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
  images: {
    flag: {
      url: '/api/v1/images/aa11/full',
      thumb_url: '/api/v1/images/aa11/thumb',
      uploaded_at: '2026-10-26T11:05:00+00:00',
      uploaded_by: { vk_user_id: 100000001, name: 'Иван Петров' },
      size_bytes: 42000,
      width: 600,
      height: 400,
    },
    portrait: null,
  },
};

/** The image delete-preview answer — the screen-18b popup's seed. */
const IMAGE_DELETE_PREVIEW = {
  nation_id: 'n-1',
  short_name: 'Синдикат',
  kind: 'flag',
  uploaded_at: '2026-10-26T11:05:00+00:00',
  uploaded_by: { vk_user_id: 100000001, name: 'Иван Петров' },
  consequences: [
    {
      code: 'image_deleted',
      text: 'картинка удаляется с сервера насовсем; в приказах, где показан этот флаг, тоже появится заглушка',
    },
    {
      code: 'audit_journal',
      text: 'в журнал попадёт запись «Удаление картинки государства»',
    },
  ],
};

interface Counters {
  nations: number;
  create: number;
  patch: number;
  patchBody: Record<string, unknown> | null;
  colorCheck: number;
  preview: number;
  del: number;
  imgPreview: number;
  imgDelete: number;
}

function allowSection({
  createAnswer,
  patchAnswer,
  deleteAnswer,
  imageDeleteAnswer,
}: {
  createAnswer?: { status: number; body: { detail: string; code: string } };
  patchAnswer?: { status: number; body: { detail: string; code: string } };
  deleteAnswer?: { status: number; body: { detail: string; code: string } };
  imageDeleteAnswer?: {
    status: number;
    body: { detail: string; code: string };
  };
} = {}): Counters {
  const counters: Counters = {
    nations: 0,
    create: 0,
    patch: 0,
    patchBody: null,
    colorCheck: 0,
    preview: 0,
    del: 0,
    imgPreview: 0,
    imgDelete: 0,
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
    http.get('*/api/v1/admin/nations/*/images/*/delete-preview', () => {
      counters.imgPreview += 1;
      return HttpResponse.json(IMAGE_DELETE_PREVIEW);
    }),
    http.get('*/api/v1/admin/nations', () => {
      counters.nations += 1;
      return HttpResponse.json(NATIONS);
    }),
    http.get('*/api/v1/admin/nations/*/delete-preview', () => {
      counters.preview += 1;
      return HttpResponse.json(NATION_DELETE_PREVIEW);
    }),
    http.get('*/api/v1/admin/nations/*/images/*/delete-preview', () => {
      counters.imgPreview += 1;
      return HttpResponse.json(IMAGE_DELETE_PREVIEW);
    }),
    http.post('*/api/v1/admin/nations/*/images/*/delete', () => {
      counters.imgDelete += 1;
      if (imageDeleteAnswer !== undefined) {
        return HttpResponse.json(imageDeleteAnswer.body, {
          status: imageDeleteAnswer.status,
        });
      }
      return HttpResponse.json(IMAGE_DELETE_PREVIEW);
    }),
    http.post('*/api/v1/admin/nations/*/delete', () => {
      counters.del += 1;
      if (deleteAnswer !== undefined) {
        return HttpResponse.json(deleteAnswer.body, {
          status: deleteAnswer.status,
        });
      }
      return HttpResponse.json(NATION_DELETE_PREVIEW);
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
  // Units 8b/8c add «Править» and the red «Удалить…» per row.
  expect(screen.getAllByText('Править')).toHaveLength(2);
  expect(screen.getAllByText('Удалить…')).toHaveLength(2);
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

/* ---------------------------------------------------------------- */
/* The deletion popup (screen 03d, unit 8c).                         */
/* ---------------------------------------------------------------- */

const CONFIRM_LABEL = 'Для подтверждения введите краткое название: Лига';

it('«Удалить…» opens the screen-03d popup with the consequence bullets', async () => {
  const counters = allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('nation-delete-n-2'));
  const popup = await screen.findByTestId('nation-delete-popup');
  const list = await screen.findByTestId('nation-delete-consequences');

  expect(counters.preview).toBe(1);
  expect(popup).toHaveTextContent('Удалить государство «Лига»?');
  expect(popup).toHaveTextContent(
    'Игрок VK 100000002 останется в игре без государства и сможет создать новое.',
  );
  expect(list).toHaveTextContent('государство «Лига» (Балтийская Лига)');
  expect(list).toHaveTextContent(
    '4 провинции станут свободными: Рига, Юрмала, Лиепая, Вентспилс',
  );
  expect(list).toHaveTextContent(
    'запланированных действий государства: 1 — они останутся без государства',
  );
  expect(list).toHaveTextContent(
    'в журнал владения карты запишутся 4 освобождения провинций',
  );
});

it('«Удалить государство» stays disabled until the exact short name is typed', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('nation-delete-n-2'));
  await screen.findByTestId('nation-delete-consequences');

  const confirm = screen.getByTestId('confirm-nation-delete');
  expect(confirm).toBeDisabled();

  const input = screen.getByLabelText(CONFIRM_LABEL);
  // Wrong case — the short name comparison is exact.
  fireEvent.change(input, { target: { value: 'лига' } });
  expect(confirm).toBeDisabled();
  fireEvent.change(input, { target: { value: 'Лига2' } });
  expect(confirm).toBeDisabled();

  // Surrounding whitespace trims; the exact name enables the button.
  fireEvent.change(input, { target: { value: '  Лига  ' } });
  expect(confirm).toBeEnabled();
});

it('a refusal shows its Russian line inside the open popup', async () => {
  allowSection({
    deleteAnswer: {
      status: 422,
      body: { detail: 'mismatch', code: 'CONFIRMATION_MISMATCH' },
    },
  });
  await enterSection();

  fireEvent.click(screen.getByTestId('nation-delete-n-2'));
  await screen.findByTestId('nation-delete-consequences');
  fireEvent.change(screen.getByLabelText(CONFIRM_LABEL), {
    target: { value: 'Лига' },
  });
  fireEvent.click(screen.getByTestId('confirm-nation-delete'));

  const error = await screen.findByTestId('nation-delete-error');
  expect(error).toHaveTextContent(
    'Подтверждение не совпало — проверьте ввод.',
  );
  expect(screen.getByTestId('nation-delete-popup')).toBeInTheDocument();
});

it('a success closes the popup, notices and reloads the list', async () => {
  const counters = allowSection();
  await enterSection();
  expect(counters.nations).toBe(1);

  fireEvent.click(screen.getByTestId('nation-delete-n-2'));
  await screen.findByTestId('nation-delete-consequences');
  fireEvent.change(screen.getByLabelText(CONFIRM_LABEL), {
    target: { value: 'Лига' },
  });
  fireEvent.click(screen.getByTestId('confirm-nation-delete'));

  await waitFor(() => expect(counters.del).toBe(1));
  await waitFor(() =>
    expect(
      screen.queryByTestId('nation-delete-popup'),
    ).not.toBeInTheDocument(),
  );
  await screen.findByText('Государство «Лига» удалено.');
  await waitFor(() => expect(counters.nations).toBe(2));
});

/* ---------------------------------------------------------------- */
/* The «Картинки государства» block and the 18b popup (0.12.0 u9).    */
/* ---------------------------------------------------------------- */

it('the block shows the loaded flag and the empty portrait', async () => {
  allowSection();
  await enterEdit();

  expect(screen.getByText('Картинки государства')).toBeInTheDocument();
  const flag = screen.getByTestId('nation-image-flag');
  expect(flag).toHaveTextContent('Флаг');
  expect(flag).toHaveTextContent('Загружен 26.10.2026, 14:05');
  expect(flag).toHaveTextContent('Игрок: Иван Петров');
  expect(flag).toHaveTextContent('600×400 · 41 КБ');
  expect(flag).toHaveTextContent(
    'Показывается в «Штабе», «Реестре» и приказах.',
  );
  expect(flag.querySelector('img')).toHaveAttribute(
    'src',
    '/api/v1/images/aa11/full',
  );

  const portrait = screen.getByTestId('nation-image-portrait');
  expect(portrait).toHaveTextContent('Портрет лидера');
  expect(portrait).toHaveTextContent('Не загружен');
  expect(portrait).toHaveTextContent('Игрокам показывается силуэт.');
  expect(screen.getByTestId('nation-image-delete-portrait')).toBeDisabled();
});

it('«Удалить флаг» loads the preview and confirming drops to the stub', async () => {
  const counters = allowSection();
  await enterEdit();

  fireEvent.click(screen.getByTestId('nation-image-delete-flag'));
  const popup = await screen.findByTestId('nation-image-delete-popup');
  await screen.findByTestId('image-delete-consequences');
  expect(counters.imgPreview).toBe(1);
  expect(popup).toHaveTextContent('Удаление флага');
  expect(popup).toHaveTextContent(
    'Удалить флаг государства «Синдикат»?',
  );
  expect(
    screen.getByTestId('image-delete-consequences'),
  ).toHaveTextContent(
    'Что будет: картинка удаляется с сервера насовсем; в приказах, ' +
      'где показан этот флаг, тоже появится заглушка. В журнал попадёт ' +
      'запись «Удаление картинки государства».',
  );

  fireEvent.click(screen.getByTestId('confirm-image-delete'));
  await waitFor(() => expect(counters.imgDelete).toBe(1));
  await waitFor(() =>
    expect(
      screen.queryByTestId('nation-image-delete-popup'),
    ).not.toBeInTheDocument(),
  );
  await screen.findByText('Флаг государства «Синдикат» удалён.');
  // The block shows the «Не загружен» stub state at once.
  const flag = screen.getByTestId('nation-image-flag');
  expect(flag).toHaveTextContent('Не загружен');
  expect(flag.querySelector('img')).toBeNull();
  expect(screen.getByTestId('nation-image-delete-flag')).toBeDisabled();
});

it('a deletion keeps the unsaved text in the form', async () => {
  allowSection();
  await enterEdit();

  fireEvent.change(screen.getByLabelText('Девиз'), {
    target: { value: 'Ещё не сохранено' },
  });
  fireEvent.click(screen.getByTestId('nation-image-delete-flag'));
  await screen.findByTestId('image-delete-consequences');
  fireEvent.click(screen.getByTestId('confirm-image-delete'));
  await waitFor(() =>
    expect(
      screen.queryByTestId('nation-image-delete-popup'),
    ).not.toBeInTheDocument(),
  );

  expect(screen.getByLabelText('Девиз')).toHaveValue('Ещё не сохранено');
});

it('a 404 IMAGE_NOT_FOUND closes the popup and notices neutrally', async () => {
  allowSection({
    imageDeleteAnswer: {
      status: 404,
      body: { detail: 'gone', code: 'IMAGE_NOT_FOUND' },
    },
  });
  await enterEdit();

  fireEvent.click(screen.getByTestId('nation-image-delete-flag'));
  await screen.findByTestId('image-delete-consequences');
  fireEvent.click(screen.getByTestId('confirm-image-delete'));

  await waitFor(() =>
    expect(
      screen.queryByTestId('nation-image-delete-popup'),
    ).not.toBeInTheDocument(),
  );
  await screen.findByText('Картинки уже нет.');
  expect(screen.getByTestId('nation-image-flag')).toHaveTextContent(
    'Не загружен',
  );
});

it('the nations table shows the flag thumb or the stub', async () => {
  allowSection();
  await enterSection();

  const rows = screen.getAllByTestId('nation-row');
  const thumb = rows[0].querySelector('img');
  expect(thumb).toHaveAttribute('src', '/api/v1/images/aa11/thumb');
  // The nation without an upload shows the stub.
  expect(
    rows[1].querySelector('[aria-label="Заглушка флага"]'),
  ).not.toBeNull();
  // A broken image falls back to the stub.
  fireEvent.error(thumb!);
  await waitFor(() =>
    expect(
      rows[0].querySelector('[aria-label="Заглушка флага"]'),
    ).not.toBeNull(),
  );
});
