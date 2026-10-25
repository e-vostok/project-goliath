/**
 * «Приказы» section (0.11.0 unit 10b, screen 05): the list renders
 * every derived status with the right badge and row action, the
 * status segment and the search send their query values, the judge
 * popup's title and grey card differ for an assigned and an
 * unassigned order, «Назначить себя» fills the field from the admins
 * list's `is_self` row, the warning card shows the lead, the server
 * warnings and the fixed sentence, each blocker disables the button
 * and shows its line, POST /admin/orders/{n}/judge carries
 * {judge_vk_user_id}, a refusal lands inside the popup and a success
 * notices + reloads the list.
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

const ORDERS = {
  items: [
    {
      number: 12,
      title: 'Укрепление северных портов',
      author_nation_short_name: 'Синдикат',
      author_nation_flag_id: 'flag_placeholder_1',
      author_name: 'Автор Синдиката',
      judge_vk_user_id: 777,
      judge_name: 'Дмитрий Соколов',
      status: 'AWAITING_VERDICT',
      deadline_at: '2026-10-26 00:00:00',
      overdue: false,
    },
    {
      number: 13,
      title: 'Торговый договор с Лигой',
      author_nation_short_name: 'Союз',
      author_nation_flag_id: 'flag_placeholder_2',
      author_name: 'Автор Союза',
      judge_vk_user_id: null,
      judge_name: null,
      status: 'NO_JUDGE',
      deadline_at: null,
      overdue: false,
    },
    {
      number: 14,
      title: 'Разведка побережья',
      author_nation_short_name: 'Лига',
      author_nation_flag_id: null,
      author_name: 'Автор Лиги',
      judge_vk_user_id: 888,
      judge_name: 'Ольга Ветрова',
      status: 'AWAITING_VERDICT',
      deadline_at: '2026-10-20 00:00:00',
      overdue: true,
    },
    {
      number: 11,
      title: 'Восстановление Выборга',
      author_nation_short_name: 'Лига',
      author_nation_flag_id: 'flag_placeholder_3',
      author_name: 'Автор Лиги',
      judge_vk_user_id: 888,
      judge_name: 'Ольга Ветрова',
      status: 'DECIDED',
      deadline_at: '2026-10-19 00:00:00',
      overdue: false,
    },
  ],
  total: 4,
};

const STATE_VIEW = {
  modules: {
    '04_orders': {
      orders_total: 4,
      worker_mode: 'RUNNING',
      last_pass_at: '2026-10-25 12:00:00',
      stages: { SUBMITTED: 1, DISTRIBUTED: 2, VERDICT: 1 },
      overdue_total: 1,
      unassigned_total: 1,
      oldest_unassigned_age_minutes: 30,
    },
  },
};

const ADMINS = [
  {
    vk_user_id: 555,
    display_name: 'Евдоким Восточный',
    source: 'env',
    granted_by_vk_user_id: null,
    granted_by_name: null,
    granted_at: null,
    is_self: true,
  },
];

const SELF_PLAYER = {
  vk_user_id: 555,
  display_name: 'Евдоким Восточный',
  nation_short_name: 'Синдикат',
  created_at: '2026-10-01 10:00:00',
  is_admin: true,
};

const PLAYERS = {
  items: [
    {
      vk_user_id: 888,
      display_name: 'Ольга Ветрова',
      nation_short_name: 'Лига',
      created_at: '2026-10-01 10:00:00',
      is_admin: false,
    },
    {
      vk_user_id: 777,
      display_name: 'Дмитрий Соколов',
      nation_short_name: null,
      created_at: '2026-10-01 10:00:00',
      is_admin: false,
    },
    {
      vk_user_id: 999,
      display_name: 'Иван Грозный',
      nation_short_name: 'Союз',
      created_at: '2026-10-01 10:00:00',
      is_admin: false,
    },
  ],
  total: 3,
};

const WARNING_TEXT =
  'Игрок «Ольга Ветрова» без государства и без согласия на сообщения ' +
  'не узнает об этом приказе.';

function previewFor(orderNumber: string, judgeVk: string | null) {
  const base = {
    current_judge: null as { vk_user_id: number; name: string } | null,
    new_judge: {
      vk_user_id: judgeVk === null ? 0 : Number(judgeVk),
      name: 'Ольга Ветрова',
    },
    blocker: null as string | null,
    warnings: [{ code: 'JUDGE_UNREACHABLE', text: WARNING_TEXT }],
  };
  if (orderNumber === '12') {
    base.current_judge = { vk_user_id: 777, name: 'Дмитрий Соколов' };
  }
  // vk 999 stands for "the verdict landed between the list load and
  // the preview" — the decided-order blocker.
  if (judgeVk === '999') {
    base.blocker = 'ORDER_ALREADY_DECIDED';
  } else if (judgeVk === '888' && orderNumber === '12') {
    base.blocker = 'JUDGE_IS_AUTHOR';
  } else if (judgeVk === '777' && orderNumber === '12') {
    base.blocker = 'ALREADY_JUDGE';
  }
  return base;
}

interface Counters {
  orders: number;
  ordersQueries: string[];
  playersSearches: string[];
  assignBody: Record<string, unknown> | null;
}

function allowSection({
  assignAnswer,
}: {
  assignAnswer?: { status: number; body: { detail: string; code: string } };
} = {}): Counters {
  const counters: Counters = {
    orders: 0,
    ordersQueries: [],
    playersSearches: [],
    assignBody: null,
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
    http.get('*/api/v1/admin/orders', ({ request }) => {
      counters.orders += 1;
      counters.ordersQueries.push(new URL(request.url).search);
      return HttpResponse.json(ORDERS);
    }),
    http.get('*/api/v1/admin/state', () => HttpResponse.json(STATE_VIEW)),
    http.get('*/api/v1/admin/admins', () => HttpResponse.json(ADMINS)),
    http.get('*/api/v1/admin/players', ({ request }) => {
      const search = new URL(request.url).searchParams.get('search') ?? '';
      counters.playersSearches.push(search);
      if (search === '555') {
        return HttpResponse.json({ items: [SELF_PLAYER], total: 1 });
      }
      return HttpResponse.json(PLAYERS);
    }),
    http.get(
      '*/api/v1/admin/orders/:number/judge-preview',
      ({ params, request }) => {
        const judgeVk = new URL(request.url).searchParams.get(
          'judge_vk_user_id',
        );
        return HttpResponse.json(
          previewFor(String(params.number), judgeVk),
        );
      },
    ),
    http.post(
      '*/api/v1/admin/orders/:number/judge',
      async ({ request, params }) => {
        counters.assignBody = (await request.json()) as Record<
          string,
          unknown
        >;
        if (assignAnswer !== undefined) {
          return HttpResponse.json(assignAnswer.body, {
            status: assignAnswer.status,
          });
        }
        const updated = ORDERS.items.find(
          (o) => o.number === Number(params.number),
        );
        return HttpResponse.json(updated);
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

/** Enter through the one-time link, then route to «Приказы». */
async function enterSection() {
  window.location.hash = `#t=${LINK_TOKEN}`;
  renderPanel();
  window.location.hash = '#/orders';
  await screen.findByTestId('orders-table');
}

/** Open the judge popup for the order and pick a suggestion. */
async function pickJudge(vkUserId: number) {
  const field = screen.getByTestId('judge-search');
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: 'Ве' } });
  const option = await screen.findByTestId(`judge-suggest-${vkUserId}`);
  fireEvent.mouseDown(option);
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('renders every status with the right badge and action', async () => {
  allowSection();
  await enterSection();

  const table = screen.getByTestId('orders-table');
  expect(table).toHaveTextContent('Укрепление северных портов');
  expect(
    screen.getByText('Судью видят только администраторы'),
  ).toBeInTheDocument();

  expect(screen.getByTestId('status-12')).toHaveTextContent(
    'Ждёт вердикта',
  );
  expect(screen.getByTestId('status-13')).toHaveTextContent('Нет судьи');
  expect(screen.getByTestId('status-11')).toHaveTextContent(
    'Вердикт вынесен',
  );
  expect(screen.getByTestId('overdue-14')).toHaveTextContent('Просрочен');

  expect(screen.getByTestId('assign-12')).toHaveTextContent(
    'Переназначить…',
  );
  expect(screen.getByTestId('assign-13')).toHaveTextContent('Назначить…');
  expect(screen.queryByTestId('assign-11')).not.toBeInTheDocument();

  // The kept state-view block: the worker's mode and counters.
  expect(screen.getByTestId('orders-state')).toHaveTextContent('работает');
});

it('the segment and the search send their query values', async () => {
  const counters = allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('filter-waiting'));
  await waitFor(() =>
    expect(
      counters.ordersQueries.some((q) => q.includes('status=waiting')),
    ).toBe(true),
  );

  fireEvent.change(screen.getByTestId('orders-search'), {
    target: { value: 'договор' },
  });
  await waitFor(() =>
    expect(
      counters.ordersQueries.some(
        (q) =>
          q.includes('status=waiting') &&
          q.includes(encodeURIComponent('договор')),
      ),
    ).toBe(true),
  );
});

it('the popup title and grey card differ for assigned and unassigned', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('assign-12'));
  let popup = await screen.findByTestId('judge-popup');
  expect(popup).toHaveTextContent('Переназначить судью');
  expect(screen.getByTestId('judge-order-card')).toHaveTextContent(
    'Приказ № 12',
  );
  expect(screen.getByTestId('judge-order-card')).toHaveTextContent(
    'судья сейчас: Дмитрий Соколов',
  );
  fireEvent.click(screen.getByText('Отмена'));

  fireEvent.click(screen.getByTestId('assign-13'));
  popup = await screen.findByTestId('judge-popup');
  expect(popup).toHaveTextContent('Назначить судью');
  expect(screen.getByTestId('judge-order-card')).toHaveTextContent(
    'судьи пока нет',
  );
});

it('«Назначить себя» fills the field with the administrator', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('assign-13'));
  await screen.findByTestId('judge-popup');
  fireEvent.click(screen.getByTestId('judge-assign-self'));

  await waitFor(() =>
    expect(screen.getByTestId('judge-search')).toHaveValue(
      'Евдоким Восточный',
    ),
  );
  expect(
    screen.getByTestId('judge-warning'),
  ).toBeInTheDocument();
});

it('the warning card shows the lead, the server warnings and the fixed sentence', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('assign-13'));
  await screen.findByTestId('judge-popup');
  await pickJudge(888);

  const warning = await screen.findByTestId('judge-warning');
  expect(warning).toHaveTextContent('Бот ничего не напишет.');
  expect(warning).toHaveTextContent(WARNING_TEXT);
  expect(warning).toHaveTextContent(
    'Порог рейтинга и предел вердиктов на одного судью к ' +
      'администратору не применяются.',
  );
  expect(warning).toHaveTextContent(
    'Для игроков судья по-прежнему анонимен.',
  );
});

it.each([
  ['12', 999, 'уже вынесен вердикт'],
  ['12', 888, 'Автор приказа не может быть его судьёй'],
  ['12', 777, 'уже назначен судьёй'],
])(
  'the blocker on order %s for judge %s disables the button and shows its line',
  async (orderNumber, judgeVk, expected) => {
    allowSection();
    await enterSection();

    fireEvent.click(screen.getByTestId(`assign-${orderNumber}`));
    await screen.findByTestId('judge-popup');
    await pickJudge(judgeVk);

    const blocker = await screen.findByTestId('judge-blocker');
    expect(blocker).toHaveTextContent(expected);
    expect(screen.getByTestId('judge-assign')).toBeDisabled();
  },
);

it('the empty field keeps «Назначить судью» disabled', async () => {
  allowSection();
  await enterSection();

  fireEvent.click(screen.getByTestId('assign-13'));
  await screen.findByTestId('judge-popup');
  expect(screen.getByTestId('judge-assign')).toBeDisabled();
});

it('posts {judge_vk_user_id} and reloads the list with a Notice', async () => {
  const counters = allowSection();
  await enterSection();
  const before = counters.orders;

  fireEvent.click(screen.getByTestId('assign-13'));
  await screen.findByTestId('judge-popup');
  await pickJudge(888);
  await screen.findByTestId('judge-warning');
  fireEvent.click(screen.getByTestId('judge-assign'));

  await screen.findByText('Приказу № 13 назначен судья.');
  await waitFor(() =>
    expect(counters.assignBody).toEqual({ judge_vk_user_id: 888 }),
  );
  await waitFor(() => expect(counters.orders).toBeGreaterThan(before));
  expect(screen.queryByTestId('judge-popup')).not.toBeInTheDocument();
});

it('a server refusal shows its line inside the popup', async () => {
  allowSection({
    assignAnswer: {
      status: 409,
      body: {
        detail: 'Автор приказа №13 не может быть его судьёй',
        code: 'JUDGE_IS_AUTHOR',
      },
    },
  });
  await enterSection();

  fireEvent.click(screen.getByTestId('assign-13'));
  await screen.findByTestId('judge-popup');
  await pickJudge(888);
  await screen.findByTestId('judge-warning');
  fireEvent.click(screen.getByTestId('judge-assign'));

  expect(await screen.findByTestId('judge-assign-error')).toHaveTextContent(
    'Автор приказа не может быть его судьёй',
  );
  expect(screen.getByTestId('judge-popup')).toBeInTheDocument();
});
