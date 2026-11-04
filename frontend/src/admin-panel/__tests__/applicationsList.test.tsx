/**
 * «Анкеты» — the sub-view of the «Государства» section (0.13.0 unit
 * 9b; mockups docs/06_DESIGN/0.13.0 screens 22/22b): the switcher
 * tab, the «В рассмотрении | Все» filter against status=PENDING|ALL,
 * every decision cell (countdown, «срок вышел», the outcome pills),
 * every reviewer case («вам» pill, «вы», name, «нет рецензента»,
 * «—»), a null `link` (plain name, disabled «Открыть» with the
 * VK_APP_ID hint), the attention badge at 0 and above, and a 401
 * ending the session through the frame. msw stands at the HTTP
 * boundary — the real api-client does the requests.
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { ThemeProvider } from '../../shared/ui/theme';
import { AdminApp } from '../AdminApp';
import { clearSession } from '../session';

const SESSION_KEY = 'pax.admin.panel.session';

const CLOCK_DTO = {
  current_turn: 1,
  game_date: '2040-01-01',
  game_date_text: 'январь 2040',
  next_tick_at: '25.10.2026 00:00:00',
};

const APP_LINK = 'https://vk.com/app54753774#application/';

function pendingRow(over: Record<string, unknown> = {}) {
  return {
    id: 'app-1',
    short_name: 'Синдикат',
    name: 'Северный Синдикат',
    status: 'PENDING',
    owner_name: 'Иван Петров',
    provinces_count: 5,
    reviewer_name: null,
    submitted_at: '2026-10-31T14:20:00Z',
    review_deadline_at: new Date(Date.now() + (21 * 60 + 40) * 60_000).toISOString(),
    assigned_to_me: true,
    submissions: 2,
    draft_reason: null,
    auto_accepted: null,
    decided_at: null,
    link: `${APP_LINK}app-1`,
    ...over,
  };
}

const PENDING_PAGE = {
  items: [
    pendingRow(),
    pendingRow({
      id: 'app-2',
      short_name: 'Нордланд',
      name: 'Республика Нордланд',
      owner_name: 'Мария Орлова',
      reviewer_name: 'Анна Кузнецова',
      submitted_at: '2026-10-31T11:05:00Z',
      review_deadline_at: new Date(
        Date.now() + (18 * 60 + 25) * 60_000,
      ).toISOString(),
      assigned_to_me: false,
      submissions: 1,
      link: `${APP_LINK}app-2`,
    }),
    pendingRow({
      id: 'app-3',
      short_name: 'Лига',
      name: 'Дунайская Лига',
      owner_name: 'Пётр Громов',
      submitted_at: '2026-10-31T09:40:00Z',
      assigned_to_me: false,
      submissions: 1,
      link: null,
    }),
  ],
  total: 3,
};

const ALL_PAGE = {
  items: [
    ...PENDING_PAGE.items,
    pendingRow({
      id: 'app-4',
      status: 'ACCEPTED',
      reviewer_name: 'Анна Кузнецова',
      assigned_to_me: false,
      auto_accepted: false,
      decided_at: '2026-10-31T13:00:00Z',
      review_deadline_at: null,
    }),
    pendingRow({
      id: 'app-5',
      status: 'ACCEPTED',
      assigned_to_me: true,
      auto_accepted: true,
      decided_at: '2026-10-30T11:20:00Z',
      review_deadline_at: null,
    }),
    pendingRow({
      id: 'app-6',
      status: 'DRAFT',
      draft_reason: 'returned',
      reviewer_name: 'Анна Кузнецова',
      assigned_to_me: false,
      review_deadline_at: null,
    }),
    pendingRow({
      id: 'app-7',
      status: 'DRAFT',
      draft_reason: 'cancelled',
      assigned_to_me: true,
      review_deadline_at: null,
    }),
    pendingRow({
      id: 'app-8',
      status: 'DRAFT',
      draft_reason: null,
      reviewer_name: null,
      assigned_to_me: false,
      submitted_at: null,
      review_deadline_at: null,
    }),
    pendingRow({
      id: 'app-9',
      review_deadline_at: new Date(Date.now() - 60_000).toISOString(),
      assigned_to_me: false,
      reviewer_name: 'Анна Кузнецова',
    }),
  ],
  total: 9,
};

const ATTENTION = {
  total: 2,
  items: [
    { key: 'applications_pending', label: 'Анкеты на рассмотрении', count: 2 },
  ],
};

interface Counters {
  attention: number;
  statuses: string[];
}

function allowSection(
  { attention = ATTENTION }: { attention?: typeof ATTENTION | { total: number; items: never[] } } = {},
): Counters {
  const counters: Counters = { attention: 0, statuses: [] };
  server.use(
    http.get('*/api/v1/game-clock', () => HttpResponse.json(CLOCK_DTO)),
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true, reset_allowed: false }),
    ),
    http.get('*/api/v1/admin/attention', () => {
      counters.attention += 1;
      return HttpResponse.json(attention);
    }),
    http.get('*/api/v1/admin/applications', ({ request }) => {
      const status =
        new URL(request.url).searchParams.get('status') ?? 'PENDING';
      counters.statuses.push(status);
      return HttpResponse.json(status === 'ALL' ? ALL_PAGE : PENDING_PAGE);
    }),
    http.get('*/api/v1/admin/nations', () =>
      HttpResponse.json({ items: [], total: 0 }),
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

async function enterNations() {
  // The stored-session entry (like panelFrame tests): a live session
  // in sessionStorage + the section hash — the boot proves it via
  // GET /admin/me and lands straight on «Государства».
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ token: 'panel-session-jwt-xyz', exp: Date.now() + 3_600_000 }),
  );
  window.location.hash = '#/nations';
  renderPanel();
  // The section's own marker — the switcher renders before the rows.
  return screen.findByTestId('tab-applications');
}

beforeEach(() => {
  window.sessionStorage.clear();
  clearSession();
  window.history.replaceState(null, '', '/admin.html');
});

it('both views wrap the switcher in a content-width div; the «Анкеты» breadcrumb is gone (13a)', async () => {
  allowSection();
  await enterNations();

  // «Государства» list: the h1 leads, then the switcher in its own
  // display:flex wrapper — the pill never stretches to a full row.
  let h1 = screen.getByRole('heading', { name: 'Государства' });
  expect(h1.previousElementSibling).toBeNull();
  let wrap = screen.getByTestId('nations-apps-switch');
  expect(wrap).toHaveStyle('display: flex');
  expect(within(wrap).getByTestId('tab-nations')).toBeInTheDocument();
  expect(h1.nextElementSibling).toBe(wrap);

  fireEvent.click(screen.getByTestId('tab-applications'));
  await screen.findByTestId('applications-table');

  // «Анкеты»: no «Государства / Анкеты» breadcrumb — the h1 leads
  // here too, and the switcher shares its row with the status filter.
  h1 = screen.getByRole('heading', { name: 'Государства' });
  expect(h1.previousElementSibling).toBeNull();
  wrap = screen.getByTestId('nations-apps-switch');
  expect(wrap).toHaveStyle('display: flex');
  expect(within(wrap).getByTestId('tab-applications')).toBeInTheDocument();
  expect(wrap.parentElement).toContainElement(
    screen.getByTestId('app-filter-pending'),
  );
});

it('the «Анкеты» tab lists the review queue of mockup 22', async () => {
  const counters = allowSection();
  await enterNations();

  // The badge rides the «Государства» menu item and the switcher tab.
  await waitFor(() =>
    expect(screen.getByTestId('nav-badge-nations')).toHaveTextContent('2'),
  );
  expect(screen.getByTestId('tab-applications')).toHaveTextContent('2');

  fireEvent.click(screen.getByTestId('tab-applications'));

  const table = await screen.findByTestId('applications-table');
  expect(counters.statuses).toEqual(['PENDING']);
  // The badge recounts after the list loads (mount + post-load).
  await waitFor(() => expect(counters.attention).toBeGreaterThanOrEqual(2));

  const row1 = screen.getByTestId('application-row-app-1');
  expect(row1).toHaveTextContent('Северный Синдикат');
  expect(row1).toHaveTextContent('Синдикат · 5 провинций');
  expect(row1).toHaveTextContent('Иван Петров');
  expect(row1).toHaveTextContent('отправка №2');
  expect(row1).toHaveTextContent(/21 ч \d{2} мин/);
  expect(row1).toHaveTextContent('до автоприёма');
  expect(row1).toHaveTextContent('вам');
  expect(
    screen.getByTestId('application-link-app-1'),
  ).toHaveAttribute('href', `${APP_LINK}app-1`);
  const open = screen.getByTestId('application-open-app-1');
  expect(open).toHaveAttribute('target', '_blank');
  expect(open.getAttribute('rel')).toContain('noopener');

  const row2 = screen.getByTestId('application-row-app-2');
  expect(row2).toHaveTextContent(/18 ч \d{2} мин/);
  expect(row2).toHaveTextContent('Анна Кузнецова');
  expect(row2).not.toHaveTextContent('отправка №');

  expect(screen.getByTestId('application-row-app-3')).toHaveTextContent(
    'нет рецензента',
  );
  expect(table).toHaveTextContent('Решение');
});

it('a null link keeps the name plain and «Открыть» disabled with the hint', async () => {
  allowSection();
  await enterNations();
  fireEvent.click(screen.getByTestId('tab-applications'));
  await screen.findByTestId('applications-table');

  const row3 = screen.getByTestId('application-row-app-3');
  expect(
    row3.querySelector('[data-testid="application-link-app-3"]'),
  ).toBeNull();
  const open = screen.getByTestId('application-open-app-3');
  expect(open.tagName).not.toBe('A');
  expect(open).toHaveAttribute('title', 'не задан VK_APP_ID');
  expect(open).toHaveAttribute('aria-disabled', 'true');
});

it('the «Все» filter switches to status=ALL and shows every outcome', async () => {
  const counters = allowSection();
  await enterNations();
  fireEvent.click(screen.getByTestId('tab-applications'));
  await screen.findByTestId('applications-table');

  fireEvent.click(screen.getByTestId('app-filter-all'));
  await waitFor(() => expect(counters.statuses).toContain('ALL'));
  await screen.findByTestId('application-row-app-8');

  expect(screen.getByTestId('application-row-app-4')).toHaveTextContent(
    'Принята',
  );
  expect(screen.getByTestId('application-row-app-5')).toHaveTextContent(
    'Принята автоматически',
  );
  expect(screen.getByTestId('application-row-app-6')).toHaveTextContent(
    'Возвращена',
  );
  expect(screen.getByTestId('application-row-app-7')).toHaveTextContent(
    'Отозвана игроком',
  );
  expect(screen.getByTestId('application-row-app-8')).toHaveTextContent(
    'Черновик',
  );
  // Decided rows mark the reviewer as «вы», none as «—».
  expect(screen.getByTestId('application-row-app-5')).toHaveTextContent('вы');
  expect(screen.getByTestId('application-row-app-8')).toHaveTextContent('—');
  // A PENDING row past its deadline reads «срок вышел».
  expect(screen.getByTestId('application-row-app-9')).toHaveTextContent(
    'срок вышел',
  );
});

it('no badge when applications_pending is 0', async () => {
  allowSection({ attention: { total: 0, items: [] } });
  await enterNations();

  await waitFor(() =>
    expect(screen.queryByTestId('nav-badge-nations')).toBeNull(),
  );
  expect(screen.getByTestId('tab-applications')).not.toHaveTextContent('0');
});

it('a 401 from the list ends the session through the frame', async () => {
  allowSection();
  server.use(
    http.get('*/api/v1/admin/applications', () =>
      HttpResponse.json(
        { detail: 'Unauthorized', code: 'UNAUTHORIZED' },
        { status: 401 },
      ),
    ),
  );
  await enterNations();
  fireEvent.click(screen.getByTestId('tab-applications'));

  await screen.findByText('Сеанс закончился');
  expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
});
