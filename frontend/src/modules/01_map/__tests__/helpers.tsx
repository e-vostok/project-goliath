/**
 * Shared helpers for 01_map tests: a plain-function fetch stub (network
 * stubbed ONLY at the fetch boundary) plus provider wrappers.
 */

import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import type { PlayerDTO } from '../../../shared/types';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import {
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../fixtures/miniMap';
import type { MapManifestDTO } from '../types';

export const SESSION = {
  token: 'jwt-token-abc',
  player: {
    id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
    vk_user_id: 123456,
    created_at: '2026-09-01T12:00:00Z',
  } satisfies PlayerDTO,
};

// jsdom's AbortSignal fails undici's brand check inside `new Request`
// (the same reason api-client races aborts instead of passing them).
// vk-mini-apps-router constructs such Requests on every navigation —
// strip foreign signals so router-driven tests don't leak unhandled
// rejections.
const UndiciRequest = Request;
vi.stubGlobal(
  'Request',
  class extends UndiciRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      // No Request in the test suite needs a signal.
      const { signal: _dropped, ...rest } = init ?? {};
      super(input, init === undefined ? undefined : rest);
    }
  },
);

export function renderWithSession(ui: ReactElement) {
  return render(
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <SessionProvider session={SESSION}>{ui}</SessionProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>,
  );
}

interface JsonBody {
  [k: string]: unknown;
}

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

export interface MapStubOptions {
  manifest?: MapManifestDTO;
  manifestEtag?: string;
  /** Called per manifest request — tracks If-None-Match and count. */
  onManifest?: (ifNoneMatch: string | null) => Response | void;
  geometry?: typeof MINI_GEOMETRY;
  /** Per-geometry-version overrides: status or a body. */
  onGeometry?: (version: string) => Response | void;
  state?: typeof MINI_STATE;
  /** Called per state request; may return a Response to override. */
  onState?: () => Response | void;
}

export interface MapStub {
  calls: { manifest: number; geometry: number; state: number };
  manifestIfNoneMatch: (string | null)[];
}

/**
 * Stubs window.fetch with plain functions covering the /api/v1/map/*
 * endpoints. Returns call counters for assertions.
 */
export function stubMapFetch(options: MapStubOptions = {}): MapStub {
  const manifest = options.manifest ?? MINI_MANIFEST;
  const geometry = options.geometry ?? MINI_GEOMETRY;
  const state = options.state ?? MINI_STATE;
  const etag = options.manifestEtag ?? '"mini-etag-1"';
  const stub: MapStub = {
    calls: { manifest: 0, geometry: 0, state: 0 },
    manifestIfNoneMatch: [],
  };

  const impl = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url = typeof input === 'string' ? input : input.toString();
    const path = new URL(url).pathname;

    if (path === '/api/v1/map/manifest') {
      stub.calls.manifest += 1;
      const inm =
        (init?.headers as Record<string, string> | undefined)?.[
          'If-None-Match'
        ] ?? null;
      stub.manifestIfNoneMatch.push(inm);
      const override = options.onManifest?.(inm);
      if (override) {
        return override;
      }
      if (inm === etag) {
        return new Response(null, { status: 304, headers: { ETag: etag } });
      }
      return json(manifest, { headers: { ETag: etag } });
    }
    if (path.startsWith('/api/v1/map/geometry/')) {
      stub.calls.geometry += 1;
      const version = path.split('/').pop() ?? '';
      const override = options.onGeometry?.(version);
      if (override) {
        return override;
      }
      return json(geometry);
    }
    if (path === '/api/v1/map/state') {
      stub.calls.state += 1;
      const override = options.onState?.();
      if (override) {
        return override;
      }
      return json(state);
    }
    return json({ detail: 'not stubbed', code: 'NOT_STUBBED' }, { status: 500 });
  };

  vi.stubGlobal(
    'fetch',
    vi.fn(impl) as unknown as typeof fetch,
  );
  return stub;
}

/** A 404 MAP_VERSION_UNKNOWN error body like the real backend sends. */
export function versionUnknown(version: string): Response {
  return json(
    {
      detail: `Unknown geometry version: ${version}`,
      code: 'MAP_VERSION_UNKNOWN',
    },
    { status: 404 },
  );
}

export function errorResponse(status: number, code = 'BROKEN'): Response {
  return json({ detail: code, code }, { status });
}

export type { JsonBody };
