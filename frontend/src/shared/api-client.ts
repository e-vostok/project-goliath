/**
 * The ONE gateway for every HTTP call to the backend.
 *
 * Components and hooks must never call `fetch` directly — they go through
 * `apiFetch` (or the endpoint helpers below). The client attaches the
 * `Authorization: Bearer` header and translates non-2xx bodies into
 * `ApiError`, preserving the spec's `ErrorResponse { detail, code }`.
 */

import type {
  AdminMeDTO,
  AdminResetResultDTO,
  AdminStateDTO,
  AdminTickLogEntryDTO,
  AdminTickRunResultDTO,
  AuthResponseDTO,
  GameClockDTO,
  NationCreateRequest,
  NationDTO,
  NationUpdateRequest,
  ProvinceDTO,
  VkAuthRequest,
} from './types';

const DEFAULT_BASE_URL = '/api/v1';

const baseUrl: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? DEFAULT_BASE_URL;

/**
 * Node's fetch (used under jsdom in tests) requires absolute URLs; a leading
 * '/' is resolved against the current origin — identical to browser behavior.
 */
function resolveUrl(path: string): string {
  const url = `${baseUrl}${path}`;
  if (url.startsWith('/') && typeof window !== 'undefined') {
    return `${window.location.origin}${url}`;
  }
  return url;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export interface ApiFetchOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  /** JSON-serialized request body. */
  body?: unknown;
  /** Short-lived Bearer JWT for the current session (never persisted). */
  token?: string;
  signal?: AbortSignal;
}

/**
 * Cancellation is implemented as a race rather than via RequestInit.signal:
 * under jsdom, jsdom's AbortSignal fails undici's brand check, and our small
 * JSON requests gain nothing from socket-level abort anyway.
 */
function withAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) {
    return promise;
  }
  if (signal.aborted) {
    return Promise.reject(new DOMException('Aborted', 'AbortError'));
  }
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener('abort', onAbort);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (options.token) {
    headers['Authorization'] = `Bearer ${options.token}`;
  }

  const response = await withAbort(
    fetch(resolveUrl(path), {
      method: options.method ?? 'GET',
      headers,
      body:
        options.body !== undefined ? JSON.stringify(options.body) : undefined,
    }),
    options.signal,
  );

  if (!response.ok) {
    let code = 'UNKNOWN_ERROR';
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const payload: unknown = await response.json();
      if (payload && typeof payload === 'object') {
        const record = payload as Record<string, unknown>;
        if (typeof record.code === 'string') {
          code = record.code;
        }
        if (typeof record.detail === 'string') {
          detail = record.detail;
        } else if (record.detail !== undefined) {
          // FastAPI 422 bodies carry detail as a list of violations.
          detail = JSON.stringify(record.detail);
        }
      }
    } catch {
      // Non-JSON error body — keep statusText fallback.
    }
    throw new ApiError(response.status, code, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Endpoint helpers for module 00_core (Spec Part 5). */
export const api = {
  /** POST /auth/vk — the entry point; exchanges launch params for a JWT. */
  authVk(launchParams: string, signal?: AbortSignal) {
    const body: VkAuthRequest = { launch_params: launchParams };
    return apiFetch<AuthResponseDTO>('/auth/vk', {
      method: 'POST',
      body,
      signal,
    });
  },

  /** GET /nations/me — 404/NATION_NOT_FOUND when the player has no nation. */
  getMyNation(token: string, signal?: AbortSignal) {
    return apiFetch<NationDTO>('/nations/me', { token, signal });
  },

  /** POST /nations — 201 + NationDTO, or 409 with a field-level code. */
  createNation(token: string, body: NationCreateRequest, signal?: AbortSignal) {
    return apiFetch<NationDTO>('/nations', {
      method: 'POST',
      body,
      token,
      signal,
    });
  },

  /** PATCH /nations/me — rename/recolor. */
  updateNation(token: string, body: NationUpdateRequest, signal?: AbortSignal) {
    return apiFetch<NationDTO>('/nations/me', {
      method: 'PATCH',
      body,
      token,
      signal,
    });
  },

  /** DELETE /nations/me — requires { confirm: true }; frees provinces. */
  deleteNation(token: string, signal?: AbortSignal) {
    return apiFetch<void>('/nations/me', {
      method: 'DELETE',
      body: { confirm: true },
      token,
      signal,
    });
  },

  /** GET /provinces — optional id filter and/or free-only flag. */
  getProvinces(
    token: string,
    filter: { ids?: number[]; freeOnly?: boolean } = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams();
    for (const id of filter.ids ?? []) {
      params.append('ids', String(id));
    }
    if (filter.freeOnly) {
      params.set('free_only', 'true');
    }
    const query = params.toString();
    return apiFetch<ProvinceDTO[]>(`/provinces${query ? `?${query}` : ''}`, {
      token,
      signal,
    });
  },

  /** GET /game-clock — current turn, derived game date, next tick time. */
  getGameClock(token: string, signal?: AbortSignal) {
    return apiFetch<GameClockDTO>('/game-clock', { token, signal });
  },

  /* Admin endpoints (core/admin router) — require an allowlisted admin's
     Bearer JWT; non-admins get 403 ADMIN_REQUIRED. */

  /** GET /admin/me — 200 {is_admin: true} for admins, 403 otherwise. */
  adminMe(token: string, signal?: AbortSignal) {
    return apiFetch<AdminMeDTO>('/admin/me', { token, signal });
  },

  /** GET /admin/state — aggregated per-module state views. */
  adminState(token: string, signal?: AbortSignal) {
    return apiFetch<AdminStateDTO>('/admin/state', { token, signal });
  },

  /** GET /admin/tick-log — newest tick_log rows first (default limit 20). */
  adminTickLog(token: string, limit?: number, signal?: AbortSignal) {
    const query = limit !== undefined ? `?limit=${limit}` : '';
    return apiFetch<AdminTickLogEntryDTO[]>(`/admin/tick-log${query}`, {
      token,
      signal,
    });
  },

  /** POST /admin/tick/run — fire one game tick immediately. */
  adminRunTick(token: string, signal?: AbortSignal) {
    return apiFetch<AdminTickRunResultDTO>('/admin/tick/run', {
      method: 'POST',
      token,
      signal,
    });
  },

  /** POST /admin/state/reset — destructive; sends { confirm: true }. */
  adminResetState(token: string, signal?: AbortSignal) {
    return apiFetch<AdminResetResultDTO>('/admin/state/reset', {
      method: 'POST',
      body: { confirm: true },
      token,
      signal,
    });
  },
};
