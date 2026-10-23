/**
 * useAdminProbe — one silent GET /admin/me per session token.
 *
 * Any failure (403 ADMIN_REQUIRED, 401, network) resolves to isAdmin=false
 * with no banner and no UI flash: the admin block simply never renders for
 * regular players.
 *
 * The probe's answer is cached in sessionStorage under a short hash of
 * the token's `sub` (load-speed unit 10): a stored «not an admin»
 * skips the request on re-entry within the same browser session — a VK
 * Mini App relaunch in the same tab shares the storage area, and the
 * sub survives the fresh JWT each launch brings. A stored «admin»
 * still revalidates silently (rights can be revoked). Storage can
 * throw or come back empty inside VK — every access is wrapped.
 */

import { useEffect, useState } from 'react';

import { api, ApiError } from '../shared/api-client';
import { useSession } from '../modules/00_core/hooks/useAuth';

const STORAGE_PREFIX = 'pax.admin.';

/**
 * Short, token-free fingerprint of the session token's subject. The JWT
 * is re-issued every launch, but `sub` names the same player — hashing
 * it keeps the cache key stable across launches while never persisting
 * the token itself. A non-JWT token falls back to hashing the whole
 * token (the cache simply never hits across launches then).
 */
function tokenFingerprint(token: string): string {
  let source = token;
  try {
    const payload = token.split('.')[1];
    if (payload) {
      const claims = JSON.parse(
        atob(payload.replace(/-/g, '+').replace(/_/g, '/')),
      ) as { sub?: unknown };
      if (typeof claims.sub === 'string' && claims.sub.length > 0) {
        source = claims.sub;
      }
    }
  } catch {
    // Malformed token — fall back to hashing it whole.
  }
  // FNV-1a (32-bit): short, stable, not reversible into the token.
  let hash = 0x811c9dc5;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16);
}

function readCached(key: string): boolean | null {
  try {
    const value = window.sessionStorage.getItem(key);
    return value === '1' ? true : value === '0' ? false : null;
  } catch {
    return null;
  }
}

function writeCached(key: string, value: boolean): void {
  try {
    window.sessionStorage.setItem(key, value ? '1' : '0');
  } catch {
    // Storage unavailable — the probe just runs again next time.
  }
}

export function useAdminProbe(): boolean {
  const { token } = useSession();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const key = STORAGE_PREFIX + tokenFingerprint(token);
    // A cached «not an admin» skips the call for the rest of this
    // browser session; «admin» is never trusted — it revalidates.
    if (readCached(key) === false) {
      return;
    }
    const controller = new AbortController();
    api
      .adminMe(token, controller.signal)
      .then((response) => {
        const admin = response.is_admin === true;
        writeCached(key, admin);
        if (!controller.signal.aborted) {
          setIsAdmin(admin);
        }
      })
      .catch((error: unknown) => {
        // A definitive refusal is worth remembering; a network failure
        // is not — the next entry probes again as before.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          writeCached(key, false);
        }
      });
    return () => controller.abort();
  }, [token]);

  return isAdmin;
}
