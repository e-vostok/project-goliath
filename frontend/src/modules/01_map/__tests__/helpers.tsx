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

import type {
  NationRulesDTO,
  PlayerDTO,
} from '../../../shared/types';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import {
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../fixtures/miniMap';
import { CONNECTING_EDGE_TYPES } from '../lib/selection';
import { clearMapSessionCache } from '../lib/sessionCache';
import type {
  MapManifestDTO,
  StartingGroupCheckDTO,
} from '../types';

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
  /**
   * POST /map/starting-group/check override — receives the requested
   * ids; default computes real connectivity over land/strait edges.
   */
  onCheck?: (ids: number[]) => Response | void;
  /** GET /nations/rules body — needed when a 00_core form is mounted. */
  nationRules?: NationRulesDTO;
}

export interface MapStub {
  calls: {
    manifest: number;
    geometry: number;
    state: number;
    check: number;
  };
  manifestIfNoneMatch: (string | null)[];
  /** province_ids of every starting-group check request. */
  checkRequests: number[][];
}

/**
 * Backend-faithful answer for POST /map/starting-group/check over the
 * stubbed manifest: unknown ids -> 404 PROVINCE_NOT_FOUND, sea -> 422
 * PROVINCE_NOT_LAND, else real connectivity over land/strait edges.
 */
function defaultCheckAnswer(
  ids: number[],
  manifest: MapManifestDTO,
): Response {
  const byId = new Map(manifest.nodes.map((n) => [n.id, n]));
  const missing = ids.filter((id) => !byId.has(id));
  if (missing.length > 0) {
    return json(
      {
        detail: `Province not found: ${missing.join(', ')}`,
        code: 'PROVINCE_NOT_FOUND',
      },
      { status: 404 },
    );
  }
  const sea = ids.filter((id) => byId.get(id)!.kind === 'SEA');
  if (sea.length > 0) {
    return json(
      {
        detail: `Province is not land: ${sea.join(', ')}`,
        code: 'PROVINCE_NOT_LAND',
      },
      { status: 422 },
    );
  }
  const adjacency = new Map<number, number[]>();
  for (const edge of manifest.edges) {
    if (!CONNECTING_EDGE_TYPES.has(edge.type)) {
      continue;
    }
    let list = adjacency.get(edge.a);
    if (!list) {
      list = [];
      adjacency.set(edge.a, list);
    }
    list.push(edge.b);
    list = adjacency.get(edge.b);
    if (!list) {
      list = [];
      adjacency.set(edge.b, list);
    }
    list.push(edge.a);
  }
  const wanted = new Set(ids);
  const seen = new Set<number>();
  let count = 0;
  for (const start of ids) {
    if (seen.has(start)) {
      continue;
    }
    count += 1;
    const queue = [start];
    seen.add(start);
    while (queue.length > 0) {
      for (const next of adjacency.get(queue.pop() as number) ?? []) {
        if (wanted.has(next) && !seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }
  const answer: StartingGroupCheckDTO = {
    connected: count === 1,
    component_count: count,
  };
  return json(answer);
}

/**
 * Stubs window.fetch with plain functions covering the /api/v1/map/*
 * endpoints. Returns call counters for assertions.
 */
export function stubMapFetch(options: MapStubOptions = {}): MapStub {
  // Session caches are module-level — reset them so every test starts
  // cold and can count requests reliably.
  clearMapSessionCache();

  const manifest = options.manifest ?? MINI_MANIFEST;
  const geometry = options.geometry ?? MINI_GEOMETRY;
  const state = options.state ?? MINI_STATE;
  const etag = options.manifestEtag ?? '"mini-etag-1"';
  const stub: MapStub = {
    calls: { manifest: 0, geometry: 0, state: 0, check: 0 },
    manifestIfNoneMatch: [],
    checkRequests: [],
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
    if (path === '/api/v1/map/starting-group/check') {
      stub.calls.check += 1;
      const ids = (
        (JSON.parse(String(init?.body ?? '[]')) as {
          province_ids?: number[];
        }).province_ids ?? []
      ).slice();
      stub.checkRequests.push(ids);
      const override = options.onCheck?.(ids);
      if (override) {
        return override;
      }
      return defaultCheckAnswer(ids, manifest);
    }
    if (path === '/api/v1/nations/rules') {
      return json(
        options.nationRules ?? {
          detail: 'not stubbed',
          code: 'NOT_STUBBED',
        },
        options.nationRules ? {} : { status: 500 },
      );
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
