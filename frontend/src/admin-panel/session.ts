/**
 * Panel session store (0.11.0 unit 5a).
 *
 * The short Bearer JWT the page got for its one-time link lives in
 * `sessionStorage`: it survives an F5 inside the same tab and dies
 * with the tab. Storage may be unavailable or throw (private modes,
 * locked-down embeds) — every access is wrapped and a module-level
 * copy keeps the page working from memory alone. The raw one-time
 * link token is never stored here; it is spent on the exchange.
 */

export interface AdminSession {
  /** Bearer access_token from POST /admin/session. */
  token: string;
  /** Client-clock expiry (epoch ms) = exchange time + expires_in_seconds. */
  expiresAtMs: number;
}

const STORAGE_KEY = 'pax.admin.panel.session';

/** In-memory copy — also the only store when sessionStorage throws. */
let memorySession: AdminSession | null = null;

function parseStored(raw: string | null): AdminSession | null {
  if (raw === null) {
    return null;
  }
  try {
    const data = JSON.parse(raw) as { token?: unknown; exp?: unknown };
    if (typeof data.token !== 'string' || typeof data.exp !== 'number') {
      return null;
    }
    return { token: data.token, expiresAtMs: data.exp };
  } catch {
    return null;
  }
}

export function readSession(): AdminSession | null {
  try {
    const stored = parseStored(window.sessionStorage.getItem(STORAGE_KEY));
    if (stored !== null) {
      return stored;
    }
  } catch {
    // Storage unavailable — fall through to the memory copy.
  }
  return memorySession;
}

export function saveSession(session: AdminSession): void {
  memorySession = session;
  try {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ token: session.token, exp: session.expiresAtMs }),
    );
  } catch {
    // Storage unavailable — the memory copy carries this page's life.
  }
}

export function clearSession(): void {
  memorySession = null;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable — nothing to remove.
  }
}
