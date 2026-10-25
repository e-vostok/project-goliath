/**
 * The ONE gateway for every HTTP call to the backend.
 *
 * Components and hooks must never call `fetch` directly — they go through
 * `apiFetch` (or the endpoint helpers below). The client attaches the
 * `Authorization: Bearer` header and translates non-2xx bodies into
 * `ApiError`, preserving the spec's `ErrorResponse { detail, code }`.
 */

import type {
  AdminAuditFiltersDTO,
  AdminAuditLogDTO,
  AdminEntryDTO,
  AdminMeDTO,
  AdminNationColorCheckRequest,
  AdminNationCreateRequest,
  AdminNationDeletePreviewDTO,
  AdminNationDetailDTO,
  AdminNationDTO,
  AdminNationsDTO,
  AdminNationUpdateRequest,
  AdminOverviewTileDTO,
  AdminPanelLinkDTO,
  AdminPlayerDeleteResultDTO,
  AdminPlayersDTO,
  AdminProvincesDTO,
  AdminResetResultDTO,
  AdminSessionDTO,
  AdminSessionRequest,
  AdminTickLogEntryDTO,
  AdminTickRunResultDTO,
  AuthResponseDTO,
  ColorCheckDTO,
  ColorCheckRequest,
  GameClockDTO,
  NationCreateRequest,
  NationDTO,
  NationPublicDTO,
  NationRulesDTO,
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
  /** Extra request headers (e.g. If-None-Match for conditional GETs). */
  extraHeaders?: Record<string, string>;
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

async function request(
  path: string,
  options: ApiFetchOptions,
): Promise<Response> {
  const headers: Record<string, string> = { ...options.extraHeaders };
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (options.token) {
    headers['Authorization'] = `Bearer ${options.token}`;
  }

  return withAbort(
    fetch(resolveUrl(path), {
      method: options.method ?? 'GET',
      headers,
      body:
        options.body !== undefined ? JSON.stringify(options.body) : undefined,
    }),
    options.signal,
  );
}

async function parseError(response: Response): Promise<ApiError> {
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
  return new ApiError(response.status, code, detail);
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const response = await request(path, options);

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export interface ConditionalResult<T> {
  /** 200 with a fresh body, or 304 (body stays null — reuse the cache). */
  status: number;
  /** The ETag the server sent, when present. */
  etag: string | null;
  body: T | null;
}

/**
 * GET with `If-None-Match` support: a 304 answer is NOT an error — it is
 * reported as `{ status: 304, body: null }` so the caller can reuse its
 * cached copy (01_map manifest revalidation).
 */
export async function apiFetchConditional<T>(
  path: string,
  options: ApiFetchOptions & { ifNoneMatch?: string } = {},
): Promise<ConditionalResult<T>> {
  const { ifNoneMatch, ...rest } = options;
  const response = await request(path, {
    ...rest,
    extraHeaders: {
      ...rest.extraHeaders,
      ...(ifNoneMatch ? { 'If-None-Match': ifNoneMatch } : {}),
    },
  });

  if (response.status === 304) {
    return { status: 304, etag: response.headers.get('ETag'), body: null };
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  return {
    status: response.status,
    etag: response.headers.get('ETag'),
    body: (await response.json()) as T,
  };
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

  /** GET /nations/rules — creation/update limits for UI hints and gating. */
  getNationRules(token: string, signal?: AbortSignal) {
    return apiFetch<NationRulesDTO>('/nations/rules', { token, signal });
  },

  /**
   * GET /nations/{id} — the public view of another player's nation
   * (Bible §7); 404/NATION_NOT_FOUND for an unknown id.
   */
  getNation(token: string, nationId: string, signal?: AbortSignal) {
    return apiFetch<NationPublicDTO>(
      `/nations/${encodeURIComponent(nationId)}`,
      { token, signal },
    );
  },

  /**
   * POST /nations/color-check — the unlocked color preview for the input
   * hint; an OK here does not guarantee creation succeeds (Spec Part 5).
   */
  checkNationColor(token: string, colorHex: string, signal?: AbortSignal) {
    const body: ColorCheckRequest = { color_hex: colorHex };
    return apiFetch<ColorCheckDTO>('/nations/color-check', {
      method: 'POST',
      body,
      token,
      signal,
    });
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

  /**
   * POST /admin/panel-link — issue the one-time link token that opens
   * the panel page (`/admin.html#t=<token>`) in a new tab.
   */
  adminPanelLink(token: string, signal?: AbortSignal) {
    return apiFetch<AdminPanelLinkDTO>('/admin/panel-link', {
      method: 'POST',
      token,
      signal,
    });
  },

  /**
   * POST /admin/session — exchange the one-time link token (from the
   * panel page's `#t=` fragment) for a short panel Bearer session.
   * NO Bearer is sent: the link token itself is the credential.
   * 401 PANEL_LINK_INVALID for an unknown/expired/spent link, 403
   * ADMIN_REQUIRED when the player no longer holds admin rights.
   */
  adminExchangeSession(linkToken: string, signal?: AbortSignal) {
    const body: AdminSessionRequest = { token: linkToken };
    return apiFetch<AdminSessionDTO>('/admin/session', {
      method: 'POST',
      body,
      signal,
    });
  },

  /**
   * GET /admin/players — one page of the «Игроки» table as
   * `{items, total}`; `search` is an exact VK id, a nation name
   * substring or a module hook's name match.
   */
  adminPlayers(
    token: string,
    query: { search?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams();
    if (query.search) {
      params.set('search', query.search);
    }
    if (query.limit !== undefined) {
      params.set('limit', String(query.limit));
    }
    if (query.offset !== undefined) {
      params.set('offset', String(query.offset));
    }
    const suffix = params.toString();
    return apiFetch<AdminPlayersDTO>(
      `/admin/players${suffix ? `?${suffix}` : ''}`,
      { token, signal },
    );
  },

  /**
   * GET /admin/provinces — one page of the LAND-province picker
   * (0.11.0 unit 8a) as `{items, total}`; `search` goes through the
   * modules' province-name hooks, `free_only` keeps unowned rows.
   */
  adminProvinces(
    token: string,
    query: {
      search?: string;
      free_only?: boolean;
      limit?: number;
      offset?: number;
    } = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams();
    if (query.search) {
      params.set('search', query.search);
    }
    if (query.free_only) {
      params.set('free_only', 'true');
    }
    if (query.limit !== undefined) {
      params.set('limit', String(query.limit));
    }
    if (query.offset !== undefined) {
      params.set('offset', String(query.offset));
    }
    const suffix = params.toString();
    return apiFetch<AdminProvincesDTO>(
      `/admin/provinces${suffix ? `?${suffix}` : ''}`,
      { token, signal },
    );
  },

  /**
   * GET /admin/nations — one page of the «Государства» table as
   * `{items, total}`; `search` is a short/full-name substring.
   */
  adminNations(
    token: string,
    query: { search?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams();
    if (query.search) {
      params.set('search', query.search);
    }
    if (query.limit !== undefined) {
      params.set('limit', String(query.limit));
    }
    if (query.offset !== undefined) {
      params.set('offset', String(query.offset));
    }
    const suffix = params.toString();
    return apiFetch<AdminNationsDTO>(
      `/admin/nations${suffix ? `?${suffix}` : ''}`,
      { token, signal },
    );
  },

  /**
   * POST /admin/nations — create a nation for the chosen player through
   * the unchanged NationService path; answers the list-item shape.
   */
  adminNationCreate(
    token: string,
    body: AdminNationCreateRequest,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminNationDTO>('/admin/nations', {
      method: 'POST',
      body,
      token,
      signal,
    });
  },

  /**
   * GET /admin/nations/{id} — the edit page's data: the twelve
   * editable fields plus owner, capital province and provinces count.
   */
  adminNation(token: string, nationId: string, signal?: AbortSignal) {
    return apiFetch<AdminNationDetailDTO>(
      `/admin/nations/${encodeURIComponent(nationId)}`,
      { token, signal },
    );
  },

  /**
   * PATCH /admin/nations/{id} — send only the changed fields; answers
   * the same detail shape. An empty body is the server's 400
   * NOTHING_TO_CHANGE.
   */
  adminNationUpdate(
    token: string,
    nationId: string,
    body: AdminNationUpdateRequest,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminNationDetailDTO>(
      `/admin/nations/${encodeURIComponent(nationId)}`,
      { method: 'PATCH', body, token, signal },
    );
  },

  /**
   * POST /admin/nations/color-check — the panel's own colour probe
   * (`nation_id` excludes the edited nation on the edit page).
   */
  adminNationColorCheck(
    token: string,
    body: AdminNationColorCheckRequest,
    signal?: AbortSignal,
  ) {
    return apiFetch<ColorCheckDTO>('/admin/nations/color-check', {
      method: 'POST',
      body,
      token,
      signal,
    });
  },

  /**
   * GET /admin/nations/{id}/delete-preview (0.11.0 unit 8c) — what
   * deleting the nation would do: the provinces it frees plus every
   * module's consequence lines.
   */
  adminNationDeletePreview(
    token: string,
    nationId: string,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminNationDeletePreviewDTO>(
      `/admin/nations/${encodeURIComponent(nationId)}/delete-preview`,
      { token, signal },
    );
  },

  /**
   * POST /admin/nations/{id}/delete — irreversible; the owner stays
   * a player. The body carries the retyped short name; the backend
   * answers 422 CONFIRMATION_MISMATCH when it differs, and returns
   * the preview that was true at the moment of deletion.
   */
  adminNationDelete(
    token: string,
    nationId: string,
    confirmShortName: string,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminNationDeletePreviewDTO>(
      `/admin/nations/${encodeURIComponent(nationId)}/delete`,
      {
        method: 'POST',
        body: { confirm_short_name: confirmShortName },
        token,
        signal,
      },
    );
  },

  /**
   * GET /admin/overview — the «Состояние мира» tiles merged from every
   * module's overview hook, sorted by `sort`.
   */
  adminOverview(token: string, signal?: AbortSignal) {
    return apiFetch<AdminOverviewTileDTO[]>('/admin/overview', {
      token,
      signal,
    });
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

  /**
   * GET /admin/players/{vk_user_id}/delete-preview — the counts of what
   * an irreversible player deletion would remove (test-player cleanup).
   */
  adminPlayerDeletePreview(
    token: string,
    vkUserId: string,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminPlayerDeleteResultDTO>(
      `/admin/players/${encodeURIComponent(vkUserId)}/delete-preview`,
      { token, signal },
    );
  },

  /**
   * POST /admin/players/{vk_user_id}/delete — irreversible. The body
   * carries the retyped id; the backend answers 422 CONFIRMATION_MISMATCH
   * when it differs from the path id.
   */
  adminPlayerDelete(
    token: string,
    vkUserId: string,
    confirmVkUserId: string,
    signal?: AbortSignal,
  ) {
    return apiFetch<AdminPlayerDeleteResultDTO>(
      `/admin/players/${encodeURIComponent(vkUserId)}/delete`,
      {
        method: 'POST',
        body: { confirm_vk_user_id: confirmVkUserId },
        token,
        signal,
      },
    );
  },

  /**
   * GET /admin/audit-log — one journal page {items, next_before_id}.
   * `before_id` is the «Показать ещё» cursor; dates are 'YYYY-MM-DD'
   * in the tick timezone.
   */
  adminAuditLog(
    token: string,
    query: {
      actor_vk_user_id?: number;
      action?: string;
      date_from?: string;
      date_to?: string;
      limit?: number;
      before_id?: number;
    } = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams();
    if (query.actor_vk_user_id !== undefined) {
      params.set('actor_vk_user_id', String(query.actor_vk_user_id));
    }
    if (query.action) {
      params.set('action', query.action);
    }
    if (query.date_from) {
      params.set('date_from', query.date_from);
    }
    if (query.date_to) {
      params.set('date_to', query.date_to);
    }
    if (query.limit !== undefined) {
      params.set('limit', String(query.limit));
    }
    if (query.before_id !== undefined) {
      params.set('before_id', String(query.before_id));
    }
    const suffix = params.toString();
    return apiFetch<AdminAuditLogDTO>(
      `/admin/audit-log${suffix ? `?${suffix}` : ''}`,
      { token, signal },
    );
  },

  /** GET /admin/audit-log/filters — the journal filters' dropdowns. */
  adminAuditLogFilters(token: string, signal?: AbortSignal) {
    return apiFetch<AdminAuditFiltersDTO>('/admin/audit-log/filters', {
      token,
      signal,
    });
  },

  /** GET /admin/admins — env admins first, then the granted ones. */
  adminAdmins(token: string, signal?: AbortSignal) {
    return apiFetch<AdminEntryDTO[]>('/admin/admins', { token, signal });
  },

  /** POST /admin/admins — grant admin rights to an existing player. */
  adminGrantAdmin(token: string, vkUserId: number, signal?: AbortSignal) {
    return apiFetch<{ granted: number }>('/admin/admins', {
      method: 'POST',
      body: { vk_user_id: vkUserId },
      token,
      signal,
    });
  },

  /** POST /admin/admins/{vk_user_id}/revoke — revoke admin rights. */
  adminRevokeAdmin(token: string, vkUserId: number, signal?: AbortSignal) {
    return apiFetch<{ revoked: number }>(
      `/admin/admins/${encodeURIComponent(String(vkUserId))}/revoke`,
      { method: 'POST', token, signal },
    );
  },
};
