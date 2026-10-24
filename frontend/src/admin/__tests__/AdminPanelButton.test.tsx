/**
 * AdminPanelButton — the «Штаб» shield (0.11.0 unit 5b, mockup
 * docs/06_DESIGN/0.11.0 screen 01).
 *
 * Gate: no element at all for non-admins. Open: a real
 * <a target="_blank"> whose href is armed by POST /admin/panel-link
 * on pointer-enter (variant А+В of the entry research); a click with
 * no fresh token preventDefaults, fetches and window.opens. msw sits
 * on the HTTP boundary — every failure is a real answer or a real
 * network error.
 */

import { useRef } from 'react';
import type { ReactElement } from 'react';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

const LINK = { token: 'tok-abc', expires_in_seconds: 60 };
const BUTTON_NAME = 'Панель администратора';

/** NoticeHost needs the app-root container it portals into. */
function Harness() {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref}>
      <NoticeHost container={ref}>
        <AdminPanelButton />
      </NoticeHost>
    </div>
  );
}

function renderButton() {
  const ui: ReactElement = <Harness />;
  return render(<SessionProvider session={SESSION}>{ui}</SessionProvider>);
}

function allowAdmin() {
  server.use(
    http.get('*/api/v1/admin/me', () =>
      HttpResponse.json({ is_admin: true }),
    ),
  );
}

function countPanelLinks(
  answer: () => Response = () => HttpResponse.json(LINK),
) {
  const calls = { n: 0 };
  server.use(
    http.post('*/api/v1/admin/panel-link', () => {
      calls.n += 1;
      return answer();
    }),
  );
  return calls;
}

describe('AdminPanelButton', () => {
  beforeEach(() => {
    // The probe caches its answer in sessionStorage — start cold.
    window.sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders no element at all when /admin/me answers 403', async () => {
    let probed = 0;
    server.use(
      http.get('*/api/v1/admin/me', () => {
        probed += 1;
        return HttpResponse.json(
          { detail: 'Admin privileges required', code: 'ADMIN_REQUIRED' },
          { status: 403 },
        );
      }),
    );

    renderButton();

    await waitFor(() => expect(probed).toBe(1));
    expect(
      screen.queryByRole('link', { name: BUTTON_NAME }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('admin-panel-button'),
    ).not.toBeInTheDocument();
  });

  it('renders the muted shield link with its tooltip for an admin', async () => {
    allowAdmin();
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    expect(link).toHaveAttribute('title', BUTTON_NAME);
    expect(link).toHaveAttribute('aria-label', BUTTON_NAME);
  });

  it('pointer-enter issues exactly one panel-link and arms the href', async () => {
    allowAdmin();
    const calls = countPanelLinks();
    const user = userEvent.setup();
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    await user.hover(link);

    await waitFor(() => expect(calls.n).toBe(1));
    await waitFor(() =>
      expect(link).toHaveAttribute(
        'href',
        `${window.location.origin}/admin.html#t=tok-abc`,
      ),
    );
    expect(link).toHaveAttribute('target', '_blank');
    const rel = link.getAttribute('rel') ?? '';
    expect(rel).toContain('noopener');
    expect(rel).toContain('noreferrer');
  });

  it('a second pointer-enter inside the token lifetime sends no new request', async () => {
    allowAdmin();
    const calls = countPanelLinks();
    const user = userEvent.setup();
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    await user.hover(link);
    await waitFor(() => expect(calls.n).toBe(1));

    await user.unhover(link);
    await user.hover(link);
    // Give a misbehaving second request time to fire — it must not.
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.n).toBe(1);
  });

  it('renews the link once the held token is no longer fresh', async () => {
    allowAdmin();
    const calls = { n: 0 };
    server.use(
      http.post('*/api/v1/admin/panel-link', () => {
        calls.n += 1;
        return HttpResponse.json({
          token: `tok-${calls.n}`,
          expires_in_seconds: 60,
        });
      }),
    );
    const user = userEvent.setup();
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    await user.hover(link);
    await waitFor(() => expect(calls.n).toBe(1));
    await waitFor(() =>
      expect(link).toHaveAttribute(
        'href',
        `${window.location.origin}/admin.html#t=tok-1`,
      ),
    );

    // Move the clock past the token's freshness window.
    const staleNow = Date.now() + 60_000;
    vi.spyOn(Date, 'now').mockImplementation(() => staleNow);

    await user.unhover(link);
    await user.hover(link);

    await waitFor(() => expect(calls.n).toBe(2));
    await waitFor(() =>
      expect(link).toHaveAttribute(
        'href',
        `${window.location.origin}/admin.html#t=tok-2`,
      ),
    );
  });

  it('a click with no ready token fetches one and window.opens it', async () => {
    allowAdmin();
    const calls = countPanelLinks();
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    // fireEvent, not user.click: the click arrives without a prior
    // hover (keyboard activation) — the fallback path.
    fireEvent.click(link);

    await waitFor(() => expect(calls.n).toBe(1));
    await waitFor(() =>
      expect(openSpy).toHaveBeenCalledWith(
        `${window.location.origin}/admin.html#t=tok-abc`,
        '_blank',
        'noopener,noreferrer',
      ),
    );
  });

  it('shows the Notice and opens nothing when the request fails', async () => {
    allowAdmin();
    countPanelLinks(() => HttpResponse.error());
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderButton();

    const link = await screen.findByRole('link', { name: BUTTON_NAME });
    fireEvent.click(link);

    await screen.findByText(
      'Не удалось открыть панель. Попробуйте ещё раз.',
    );
    expect(openSpy).not.toHaveBeenCalled();
  });
});
