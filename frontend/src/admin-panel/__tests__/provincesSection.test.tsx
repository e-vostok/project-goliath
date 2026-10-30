/**
 * «Провинции» section (0.11.0 unit 9b, screens 04/04b/04c): the
 * searchable list renders owner short names or «свободна», the
 * withdraw segment stays disabled for a free province, card 3 shows
 * the seize banner/bullets/checkbox, the capital banner and select,
 * the bordered LAST_PROVINCE refusal and the ALREADY_OWNER line from
 * GET /admin/provinces/{id}/transfer-preview, the action button keeps
 * its conditions, POST /transfer carries to_nation_id, confirm_seize
 * and new_capital_province_id, a refusal lands inside the card and a
 * success notices + reloads the list.
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
      owner_name: null,
      provinces_count: 6,
      capital_name: 'Мурманск',
    },
    {
      id: 'n-2',
      short_name: 'Лига',
      name: 'Балтийская Лига',
      owner_vk_user_id: 100000002,
      owner_name: null,
      provinces_count: 4,
      capital_name: 'Рига',
    },
    {
      id: 'n-3',
      short_name: 'Союз',
      name: 'Дунайский Союз',
      owner_vk_user_id: 100000003,
      owner_name: null,
      provinces_count: 1,
      capital_name: 'Вена',
    },
  ],
  total: 3,
};

const PROVINCES = {
  items: [
    {
      id: 201,
      name: 'Выборг',
      nation_id: 'n-2',
      nation_short_name: 'Лига',
      flag_thumb_url: '/api/v1/images/cc33/thumb',
    },
    {
      id: 202,
      name: 'Вышний Волочёк',
      nation_id: null,
      nation_short_name: null,
      flag_thumb_url: null,
    },
    {
      id: 203,
      name: 'Вена',
      nation_id: 'n-3',
      nation_short_name: 'Союз',
      flag_thumb_url: null,
    },
    {
      id: 204,
      name: 'Рига',
      nation_id: 'n-2',
      nation_short_name: 'Лига',
      flag_thumb_url: '/api/v1/images/cc33/thumb',
    },
  ],
  total: 4,
};

/** The seize case — screen 04: Выборг (Лига) → Синдикат. */
const PREVIEW_SEIZE = {
  province: { id: 201, name: 'Выборг' },
  from_nation: {
    id: 'n-2',
    short_name: 'Лига',
    provinces_count: 4,
    capital_province_id: 204,
    capital_name: 'Рига',
  },
  to_nation: { id: 'n-1', short_name: 'Синдикат', provinces_count: 6 },
  seizes: true,
  capital_choice_needed: false,
  capital_candidates: [],
  donor_after: 3,
  receiver_after: 7,
  blocker: null,
};

/** The capital case — screen 04b: Рига (capital of Лига) → Синдикат. */
const PREVIEW_CAPITAL = {
  province: { id: 204, name: 'Рига' },
  from_nation: {
    id: 'n-2',
    short_name: 'Лига',
    provinces_count: 4,
    capital_province_id: 204,
    capital_name: 'Рига',
  },
  to_nation: { id: 'n-1', short_name: 'Синдикат', provinces_count: 6 },
  seizes: true,
  capital_choice_needed: true,
  capital_candidates: [
    { id: 205, name: 'Юрмала' },
    { id: 206, name: 'Лиепая' },
    { id: 207, name: 'Вентспилс' },
  ],
  donor_after: 3,
  receiver_after: 7,
  blocker: null,
};

/** Screen 04c — Вена is the Союз's last province. */
const PREVIEW_LAST = {
  province: { id: 203, name: 'Вена' },
  from_nation: {
    id: 'n-3',
    short_name: 'Союз',
    provinces_count: 1,
    capital_province_id: 203,
    capital_name: 'Вена',
  },
  to_nation: null,
  seizes: false,
  capital_choice_needed: true,
  capital_candidates: [],
  donor_after: 0,
  receiver_after: null,
  blocker: 'LAST_PROVINCE',
};

/** Выборг → Лига — already the target's. */
const PREVIEW_ALREADY = {
  ...PREVIEW_SEIZE,
  to_nation: { id: 'n-2', short_name: 'Лига', provinces_count: 4 },
  seizes: false,
  receiver_after: 5,
  blocker: 'ALREADY_OWNER',
};

/** A plain release — Выборг leaves Лига (not its capital). */
const PREVIEW_RELEASE = {
  ...PREVIEW_SEIZE,
  to_nation: null,
  seizes: false,
  receiver_after: null,
  blocker: null,
};

const TRANSFER_RESULT = {
  province_id: 201,
  previous_nation_id: 'n-2',
  new_nation_id: 'n-1',
  new_capital_province_id: null,
};

interface Counters {
  provinces: number;
  transferBody: Record<string, unknown> | null;
}

function allowSection({
  transferAnswer,
}: {
  transferAnswer?: { status: number; body: { detail: string; code: string } };
} = {}): Counters {
  const counters: Counters = { provinces: 0, transferBody: null };
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
    http.get('*/api/v1/admin/provinces', () => {
      counters.provinces += 1;
      return HttpResponse.json(PROVINCES);
    }),
    http.get('*/api/v1/admin/nations', () => HttpResponse.json(NATIONS)),
    http.get(
      '*/api/v1/admin/provinces/:provinceId/transfer-preview',
      ({ params, request }) => {
        const to = new URL(request.url).searchParams.get('to_nation_id');
        if (params.provinceId === '203') {
          return HttpResponse.json(PREVIEW_LAST);
        }
        if (params.provinceId === '204') {
          return HttpResponse.json(PREVIEW_CAPITAL);
        }
        if (to === 'n-2') {
          return HttpResponse.json(PREVIEW_ALREADY);
        }
        if (to === null) {
          return HttpResponse.json(PREVIEW_RELEASE);
        }
        return HttpResponse.json(PREVIEW_SEIZE);
      },
    ),
    http.post(
      '*/api/v1/admin/provinces/:provinceId/transfer',
      async ({ request }) => {
        counters.transferBody = (await request.json()) as Record<
          string,
          unknown
        >;
        if (transferAnswer !== undefined) {
          return HttpResponse.json(transferAnswer.body, {
            status: transferAnswer.status,
          });
        }
        return HttpResponse.json(TRANSFER_RESULT);
      },
    ),
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

/** Enter through the one-time link, then route to «Провинции». */
async function enterSection() {
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();
  window.location.hash = '#/provinces';
  await screen.findByTestId('province-list');
}

/** Pick the first nation suggestion in the recipient field. */
async function pickRecipient(index = 0) {
  fireEvent.focus(screen.getByTestId('recipient-input'));
  const option = await screen.findByTestId(`recipient-option-${index}`);
  fireEvent.mouseDown(option);
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('renders the list rows with the owner or «свободна»', async () => {
  allowSection();
  await enterSection();

  const list = screen.getByTestId('province-list');
  expect(list).toHaveTextContent('Выборг');
  expect(list).toHaveTextContent('Вышний Волочёк');
  expect(list).toHaveTextContent('Вена');
  expect(list).toHaveTextContent('Лига');
  expect(list).toHaveTextContent('Союз');
  expect(list).toHaveTextContent('свободна');
});

it('keeps the withdraw segment disabled for a free province', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-202'));
  expect(screen.getByTestId('action-withdraw')).toBeDisabled();

  fireEvent.click(screen.getByTestId('province-row-201'));
  expect(screen.getByTestId('action-withdraw')).not.toBeDisabled();
});

it('shows the seize banner, bullets and gates the button (screen 04)', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-201'));
  await pickRecipient(0);

  const banner = await screen.findByTestId('preview-seize-banner');
  expect(banner).toHaveTextContent('Провинция занята другим государством.');
  expect(banner).toHaveTextContent(
    '«Выборг» сейчас принадлежит государству «Лига» и будет у него изъята.',
  );

  const bullets = screen.getByTestId('preview-bullets');
  expect(bullets).toHaveTextContent(
    '«Синдикат» получит ещё одну провинцию: станет 7.',
  );
  expect(bullets).toHaveTextContent(
    'У «Лиги» останется 3 провинции, столица (Рига) на месте.',
  );
  expect(bullets).toHaveTextContent(
    'Запись попадёт в журнал владения карты и в журнал администратора.',
  );

  const submit = screen.getByTestId('province-submit');
  expect(submit).toHaveTextContent('Передать провинцию');
  expect(submit).toBeDisabled();
  fireEvent.click(screen.getByTestId('seize-confirm'));
  expect(submit).not.toBeDisabled();
});

it('shows the capital banner and select (screen 04b)', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-204'));
  await pickRecipient(0);

  const banner = await screen.findByTestId('preview-capital-banner');
  expect(banner).toHaveTextContent('«Рига» — столица «Лиги».');

  const submit = screen.getByTestId('province-submit');
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByTestId('capital-select'), {
    target: { value: '205' },
  });
  expect(screen.getByTestId('preview-bullets')).toHaveTextContent(
    'столица — Юрмала.',
  );
  fireEvent.click(screen.getByTestId('seize-confirm'));
  expect(submit).not.toBeDisabled();
});

it('shows the bordered LAST_PROVINCE refusal (screen 04c)', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-203'));
  fireEvent.click(screen.getByTestId('action-withdraw'));

  const blocker = await screen.findByTestId('preview-blocker');
  expect(blocker).toHaveTextContent('Это последняя провинция «Союза».');
  expect(blocker).toHaveTextContent(
    'удалите его целиком в разделе «Государства».',
  );
  expect(screen.getByTestId('province-submit')).toBeDisabled();
});

it('shows the ALREADY_OWNER line and keeps the button disabled', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-201'));
  await pickRecipient(1); // Лига — the current owner

  const blocker = await screen.findByTestId('preview-blocker');
  expect(blocker).toHaveTextContent(
    'Провинция уже принадлежит этому государству.',
  );
  expect(screen.getByTestId('province-submit')).toBeDisabled();
});

it('sends to_nation_id, confirm_seize and new_capital_province_id', async () => {
  const counters = allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-201'));
  await pickRecipient(0);
  await screen.findByTestId('preview-seize-banner');
  fireEvent.click(screen.getByTestId('seize-confirm'));
  fireEvent.click(screen.getByTestId('province-submit'));

  await waitFor(() => expect(counters.transferBody).not.toBeNull());
  expect(counters.transferBody).toEqual({
    to_nation_id: 'n-1',
    confirm_seize: true,
    new_capital_province_id: null,
  });
});

it('shows the server refusal inside the card', async () => {
  allowSection({
    transferAnswer: {
      status: 422,
      body: { detail: 'seize not confirmed', code: 'SEIZE_NOT_CONFIRMED' },
    },
  });
  await enterSection();

  fireEvent.click(screen.getByTestId('province-row-201'));
  await pickRecipient(0);
  await screen.findByTestId('preview-seize-banner');
  fireEvent.click(screen.getByTestId('seize-confirm'));
  fireEvent.click(screen.getByTestId('province-submit'));

  expect(await screen.findByTestId('preview-error')).toHaveTextContent(
    'Подтвердите изъятие провинции у другого государства.',
  );
});

it('notices and reloads the list on success', async () => {
  const counters = allowSection();
  await enterSection();
  const before = counters.provinces;

  fireEvent.click(screen.getByTestId('province-row-201'));
  await pickRecipient(0);
  await screen.findByTestId('preview-seize-banner');
  fireEvent.click(screen.getByTestId('seize-confirm'));
  fireEvent.click(screen.getByTestId('province-submit'));

  await screen.findByText(
    'Провинция «Выборг» передана государству «Синдикат».',
  );
  await waitFor(() => expect(counters.provinces).toBeGreaterThan(before));
  // The selection is cleared — card 3 is back to the empty state.
  expect(
    screen.getByText('Выберите провинцию слева — здесь появится, что произойдёт.'),
  ).toBeInTheDocument();
});

it('the owner cell shows the flag thumb or the stub (0.12.0 u9)', async () => {
  allowSection();
  await enterSection();

  const withFlag = screen.getByTestId('province-row-201');
  const img = withFlag.querySelector('img');
  expect(img).toHaveAttribute('src', '/api/v1/images/cc33/thumb');
  const other = screen.getByTestId('province-row-203');
  expect(
    other.querySelector('[aria-label="Заглушка флага"]'),
  ).not.toBeNull();
  fireEvent.error(img!);
  await waitFor(() =>
    expect(
      withFlag.querySelector('[aria-label="Заглушка флага"]'),
    ).not.toBeNull(),
  );
});
