/**
 * useProvinceNames on GET /map/province-names (load-speed unit 11):
 * the non-map screens download the light names payload instead of the
 * ~20× heavier manifest. The stored { etag, body } pair gives a
 * conditional relaunch (304 reuse), a warm copy renders instantly
 * while revalidating, and a failed request resolves to empty names —
 * the callers' «Провинция» fallback, unchanged from the manifest era.
 */

import type { ReactElement, ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';

import { SessionProvider } from '../../00_core/hooks/useAuth';
import { MINI_NAMES } from '../fixtures/miniMap';
import { useProvinceNames } from '../hooks/useProvinceNames';
import {
  clearMapSessionCache,
  NAMES_STORAGE_KEY,
  readNamesCache,
} from '../lib/sessionCache';
import { errorResponse, SESSION, stubMapFetch } from './helpers';

function seedNames(etag: string | null, body: unknown = MINI_NAMES) {
  window.localStorage.setItem(
    NAMES_STORAGE_KEY,
    JSON.stringify({ v: 1, etag, body }),
  );
}

function namesWrapper({ children }: { children?: ReactNode }) {
  return (
    <SessionProvider session={SESSION}>
      {children as ReactElement}
    </SessionProvider>
  );
}

describe('useProvinceNames — light names payload', () => {
  beforeEach(() => {
    clearMapSessionCache();
    window.localStorage.clear();
  });
  afterEach(() => {
    clearMapSessionCache();
    window.localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fetches /map/province-names, not the manifest', async () => {
    const stub = stubMapFetch();

    const { result } = renderHook(() => useProvinceNames(), {
      wrapper: namesWrapper,
    });

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(stub.calls.names).toBe(1);
    expect(stub.calls.manifest).toBe(0);
    expect(result.current.names.get(1001)).toBe('Альфа');
    expect(result.current.names.get(2001)).toBe('Северное мини-море');
    expect(result.current.names.size).toBe(
      Object.keys(MINI_NAMES.names).length,
    );
  });

  it('a cold start sends the stored names ETag; a 304 reuses the body', async () => {
    const stub = stubMapFetch({ namesEtag: '"stored-names-etag"' });
    seedNames('"stored-names-etag"');

    const { result } = renderHook(() => useProvinceNames(), {
      wrapper: namesWrapper,
    });

    // The warm copy renders instantly — loading never flashes.
    expect(result.current.loading).toBe(false);
    expect(result.current.names.get(1001)).toBe('Альфа');
    await waitFor(() => expect(stub.calls.names).toBe(1));
    expect(stub.namesIfNoneMatch[0]).toBe('"stored-names-etag"');
    expect(result.current.names.get(1002)).toBe('Бета');
  });

  it('a 200 replaces both the session copy and the stored one', async () => {
    const fresh: typeof MINI_NAMES = {
      map_version: MINI_NAMES.map_version,
      names: { ...MINI_NAMES.names, 1001: 'Альфа-Новая' },
    };
    const stub = stubMapFetch({
      names: fresh,
      namesEtag: '"new-names-etag"',
    });
    seedNames('"stale-names-etag"', {
      ...MINI_NAMES,
      names: { ...MINI_NAMES.names, 1001: 'Альфа-Старая' },
    });

    const { result } = renderHook(() => useProvinceNames(), {
      wrapper: namesWrapper,
    });

    await waitFor(() =>
      expect(result.current.names.get(1001)).toBe('Альфа-Новая'),
    );
    expect(stub.namesIfNoneMatch[0]).toBe('"stale-names-etag"');
    expect(readNamesCache()).toEqual({
      etag: '"new-names-etag"',
      body: fresh,
    });
    const stored = JSON.parse(
      window.localStorage.getItem(NAMES_STORAGE_KEY) ?? 'null',
    ) as { etag?: string };
    expect(stored.etag).toBe('"new-names-etag"');
  });

  it('a failed request resolves to empty names — the «Провинция» fallback', async () => {
    const stub = stubMapFetch({
      onNames: () => errorResponse(500, 'BROKEN'),
    });

    const { result } = renderHook(() => useProvinceNames(), {
      wrapper: namesWrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.names.size).toBe(0);
    expect(stub.calls.names).toBe(1);
    // Nothing was cached — a retry on the next mount is possible.
    expect(readNamesCache()).toBeNull();
  });
});
