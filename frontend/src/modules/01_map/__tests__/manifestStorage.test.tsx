/**
 * Manifest persistence between launches (load-speed unit 10,
 * proposal 7): the session cache's { etag, body } pair is mirrored to
 * localStorage under a key carrying the app version. A cold start sends
 * the stored ETag — a 304 reuses the stored body (~103 KB saved), a
 * 200 replaces both memory and storage. Corrupt, oversized or
 * foreign-version entries are ignored; storage that throws changes
 * nothing.
 */

import type { ReactElement, ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';

import { SessionProvider } from '../../00_core/hooks/useAuth';
import { MINI_MANIFEST } from '../fixtures/miniMap';
import { useMapManifest } from '../hooks/useMapManifest';
import {
  clearMapSessionCache,
  MANIFEST_STORAGE_KEY,
  readManifestCache,
} from '../lib/sessionCache';
import { SESSION, stubMapFetch } from './helpers';

function seed(etag: string | null, body: unknown = MINI_MANIFEST) {
  window.localStorage.setItem(
    MANIFEST_STORAGE_KEY,
    JSON.stringify({ v: 1, etag, body }),
  );
}

function manifestWrapper({ children }: { children?: ReactNode }) {
  return (
    <SessionProvider session={SESSION}>
      {children as ReactElement}
    </SessionProvider>
  );
}

describe('map manifest — localStorage copy between launches', () => {
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

  it('the first read seeds the session cache from storage', () => {
    seed('"stored-etag"');

    expect(readManifestCache()).toEqual({
      etag: '"stored-etag"',
      body: MINI_MANIFEST,
    });
  });

  it('a cold start sends the stored ETag and a 304 reuses the body', async () => {
    const stub = stubMapFetch({ manifestEtag: '"stored-etag"' });
    seed('"stored-etag"');

    const { result } = renderHook(() => useMapManifest(), {
      wrapper: manifestWrapper,
    });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(stub.calls.manifest).toBe(1);
    expect(stub.manifestIfNoneMatch[0]).toBe('"stored-etag"');
    expect(result.current.manifest).toEqual(MINI_MANIFEST);
  });

  it('a 200 replaces both the session copy and the stored one', async () => {
    const fresh = { ...MINI_MANIFEST, attribution: 'fresh attribution' };
    const stub = stubMapFetch({
      manifest: fresh,
      manifestEtag: '"new-etag"',
    });
    seed('"stale-etag"', { ...MINI_MANIFEST, attribution: 'stale' });
    // A foreign build's copy must be dropped on the next write.
    window.localStorage.setItem(
      'pax.map.manifest:0.0.0-ancient',
      JSON.stringify({ v: 1, etag: '"x"', body: {} }),
    );

    const { result } = renderHook(() => useMapManifest(), {
      wrapper: manifestWrapper,
    });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(stub.calls.manifest).toBe(1);
    expect(stub.manifestIfNoneMatch[0]).toBe('"stale-etag"');
    expect(result.current.manifest).toEqual(fresh);
    expect(readManifestCache()).toEqual({
      etag: '"new-etag"',
      body: fresh,
    });
    const stored = JSON.parse(
      window.localStorage.getItem(MANIFEST_STORAGE_KEY) ?? 'null',
    ) as { etag?: string; body?: { attribution?: string } };
    expect(stored.etag).toBe('"new-etag"');
    expect(stored.body?.attribution).toBe('fresh attribution');
    expect(
      window.localStorage.getItem('pax.map.manifest:0.0.0-ancient'),
    ).toBeNull();
  });

  it('corrupt or foreign-version entries are ignored silently', () => {
    window.localStorage.setItem(MANIFEST_STORAGE_KEY, 'not json {{{');
    expect(readManifestCache()).toBeNull();

    clearMapSessionCache();
    window.localStorage.setItem(
      MANIFEST_STORAGE_KEY,
      JSON.stringify({ v: 999, etag: '"e"', body: MINI_MANIFEST }),
    );
    expect(readManifestCache()).toBeNull();

    clearMapSessionCache();
    window.localStorage.setItem(
      'pax.map.manifest:0.0.0-ancient',
      JSON.stringify({ v: 1, etag: '"e"', body: MINI_MANIFEST }),
    );
    expect(readManifestCache()).toBeNull();
  });

  it('an oversized stored entry is ignored', () => {
    window.localStorage.setItem(
      MANIFEST_STORAGE_KEY,
      'x'.repeat(4_000_001),
    );
    expect(readManifestCache()).toBeNull();
  });

  it('storage that throws leaves the cold-start flow intact', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    const stub = stubMapFetch({ manifestEtag: '"etag"' });

    const { result } = renderHook(() => useMapManifest(), {
      wrapper: manifestWrapper,
    });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(stub.calls.manifest).toBe(1);
    expect(stub.manifestIfNoneMatch[0]).toBeNull();
    expect(result.current.manifest).toEqual(MINI_MANIFEST);
  });
});
