/**
 * The lit shield (0.13.0 unit 9b; mockups docs/06_DESIGN/0.13.0
 * screens 23/23b): `useAdminAttention` polls GET /admin/attention
 * only while the probe says admin AND the home tab is active —
 * `total > 0` lights the square with the signal dot and the
 * «Требует внимания» tooltip; `0` or any failure keeps the quiet
 * look with no error. msw stands at the HTTP boundary.
 */

import { useRef } from 'react';
import type { ReactElement } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { SessionProvider } from '../../modules/00_core/hooks/useAuth';
import { NoticeHost } from '../../shared/ui';
import { AdminPanelButton } from '../AdminPanelButton';

const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 424242,
    created_at: '2026-09-01T12:00:00Z',
  },
};

const BUTTON_NAME = 'Панель администратора';

function Harness({ active }: { active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref} data-testid="app-root">
      <NoticeHost container={ref}>
        <AdminPanelButton active={active} />
      </NoticeHost>
    </div>
  );
}

function renderButton(active = true) {
  const ui: ReactElement = <Harness active={active} />;
  return render(<SessionProvider session={SESSION}>{ui}</SessionProvider>);
}

function allowAdmin() {
  server.use(
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true }),
    ),
  );
}

function countAttention(answer: () => Response) {
  const calls = { n: 0 };
  server.use(
    http.get('*/api/v1/admin/attention', () => {
      calls.n += 1;
      return answer();
    }),
  );
  return calls;
}

const LIT = {
  total: 3,
  items: [
    { key: 'applications_pending', label: 'Анкеты на рассмотрении', count: 2 },
    { key: 'orders_no_judge', label: 'Приказы без судьи', count: 1 },
  ],
};

beforeEach(() => {
  window.sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it('total > 0 lights the shield and the tooltip lists the items', async () => {
  allowAdmin();
  const calls = countAttention(() => HttpResponse.json(LIT));
  renderButton();

  await screen.findByRole('link', { name: BUTTON_NAME });
  await waitFor(() => expect(calls.n).toBe(1));
  // The lit state wraps the link in the Tooltip trigger — re-query.
  const link = await waitFor(() => {
    const el = screen.getByRole('link', { name: BUTTON_NAME });
    expect(el).toHaveAttribute('data-attention', 'lit');
    return el;
  });
  expect(screen.getByTestId('admin-attention-dot')).toBeInTheDocument();

  vi.useFakeTimers();
  fireEvent.pointerEnter(link);
  act(() => {
    vi.advanceTimersByTime(600);
  });
  vi.useRealTimers();
  const tip = await screen.findByRole('tooltip');
  expect(tip).toHaveTextContent('Требует внимания');
  expect(tip).toHaveTextContent('Анкеты на рассмотрении');
  expect(tip).toHaveTextContent('2');
  expect(tip).toHaveTextContent('Приказы без судьи');
  expect(tip).toHaveTextContent(
    'Нажмите, чтобы открыть панель администратора.',
  );
});

it('total = 0 keeps the quiet look', async () => {
  allowAdmin();
  countAttention(() => HttpResponse.json({ total: 0, items: [] }));
  renderButton();

  const link = await screen.findByRole('link', { name: BUTTON_NAME });
  await waitFor(() =>
    expect(link).not.toHaveAttribute('data-attention'),
  );
  expect(
    screen.queryByTestId('admin-attention-dot'),
  ).not.toBeInTheDocument();
});

it('a failed poll keeps the quiet look and shows no error', async () => {
  allowAdmin();
  countAttention(() => HttpResponse.error());
  renderButton();

  const link = await screen.findByRole('link', { name: BUTTON_NAME });
  await waitFor(() =>
    expect(link).not.toHaveAttribute('data-attention'),
  );
  expect(
    screen.queryByTestId('admin-attention-dot'),
  ).not.toBeInTheDocument();
});

it('no polling outside the home tab (active=false)', async () => {
  allowAdmin();
  const calls = countAttention(() => HttpResponse.json(LIT));
  renderButton(false);

  await screen.findByRole('link', { name: BUTTON_NAME });
  // Give a misbehaving poll time to fire — it must not.
  await new Promise((r) => setTimeout(r, 40));
  expect(calls.n).toBe(0);
});
