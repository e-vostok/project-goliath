/**
 * useAdminProbe — the sessionStorage cache (load-speed unit 10).
 *
 * A stored «not an admin» skips GET /admin/me on re-entry within the
 * browser session; a stored «admin» still revalidates silently; a
 * definitive 403/401 writes the cache, a network failure does not;
 * storage that throws changes nothing about today's behavior.
 */

import type { ReactElement, ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { SessionProvider } from '../../modules/00_core/hooks/useAuth';
import { useAdminProbe } from '../useAdminProbe';

/** Minimal JWT-shaped token — the fingerprint reads `sub`. */
function tokenFor(sub: string): string {
  const payload = btoa(JSON.stringify({ sub }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `h.${payload}.s`;
}

function wrapperFor(token: string) {
  return function Wrapper({ children }: { children?: ReactNode }) {
    const ui: ReactElement = children as ReactElement;
    return (
      <SessionProvider
        session={{
          token,
          player: {
            id: 'p',
            vk_user_id: 1,
            created_at: '2026-01-01T00:00:00Z',
          },
        }}
      >
        {ui}
      </SessionProvider>
    );
  };
}

function probeCounter() {
  const calls = { n: 0 };
  return {
    calls,
    deny() {
      server.use(
        http.get('*/api/v1/admin/me', () => {
          calls.n += 1;
          return HttpResponse.json(
            { detail: 'Admin privileges required', code: 'ADMIN_REQUIRED' },
            { status: 403 },
          );
        }),
      );
    },
    fail() {
      server.use(
        http.get('*/api/v1/admin/me', () => {
          calls.n += 1;
          return HttpResponse.error();
        }),
      );
    },
  };
}

const KEY_PREFIX = 'pax.admin.';

describe('useAdminProbe — session cache', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });
  afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('a denied probe is cached and skips the request on re-mount', async () => {
    const counter = probeCounter();
    counter.deny();
    const token = tokenFor('player-non-admin');

    const first = renderHook(() => useAdminProbe(), {
      wrapper: wrapperFor(token),
    });
    await waitFor(() => expect(counter.calls.n).toBe(1));
    first.unmount();

    expect(
      window.sessionStorage.getItem(
        Object.keys(window.sessionStorage).find((k) =>
          k.startsWith(KEY_PREFIX),
        ) ?? '',
      ),
    ).toBe('0');

    renderHook(() => useAdminProbe(), { wrapper: wrapperFor(token) });
    // Give a misbehaving probe time to fire — it must not.
    await new Promise((r) => setTimeout(r, 50));
    expect(counter.calls.n).toBe(1);
  });

  it('a stored «admin» still revalidates silently', async () => {
    const counter = probeCounter();
    counter.deny();
    const token = tokenFor('player-was-admin');
    // Simulate a stored «1» under the same key the hook computes.
    renderHook(() => useAdminProbe(), { wrapper: wrapperFor(token) });
    await waitFor(() => expect(counter.calls.n).toBe(1));
    const key = Object.keys(window.sessionStorage).find((k) =>
      k.startsWith(KEY_PREFIX),
    );
    expect(key).toBeDefined();
    window.sessionStorage.setItem(key!, '1');

    renderHook(() => useAdminProbe(), { wrapper: wrapperFor(token) });
    await waitFor(() => expect(counter.calls.n).toBe(2));
  });

  it('a network failure writes nothing — the next mount probes again', async () => {
    const counter = probeCounter();
    counter.fail();
    const token = tokenFor('player-flaky');

    renderHook(() => useAdminProbe(), { wrapper: wrapperFor(token) });
    await waitFor(() => expect(counter.calls.n).toBe(1));
    expect(
      Object.keys(window.sessionStorage).filter((k) =>
        k.startsWith(KEY_PREFIX),
      ),
    ).toHaveLength(0);

    renderHook(() => useAdminProbe(), { wrapper: wrapperFor(token) });
    await waitFor(() => expect(counter.calls.n).toBe(2));
  });

  it('storage that throws leaves the probe working as before', async () => {
    const counter = probeCounter();
    counter.deny();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });

    const token = tokenFor('player-no-storage');
    const { result } = renderHook(() => useAdminProbe(), {
      wrapper: wrapperFor(token),
    });
    await waitFor(() => expect(counter.calls.n).toBe(1));
    expect(result.current).toBe(false);
  });
});
