/**
 * lib/entryRequest.ts — the «open the Registry on X» handoff
 * (Spec 04_orders 5.5, Spec 03_registry 5.5 «Вход с предустановкой»).
 *
 * `normalizeEntryHash` (AppShell) runs before the router exists, so a
 * recognized `#registry/order-<1-9 digits>` hash is stored here as a
 * pending request; AppShell passes it to PanelRegistry, which selects
 * the requested tab if it exists and runs the action once its rows
 * are loaded — the same call a cell click makes.
 *
 * In-app callers (the «Штаб» badges) skip the hash: they call
 * `setRegistryEntryRequest` with a `preset` — the filters the tab
 * opens with — and navigate. PanelRegistry takes the stored request
 * the next time the panel becomes active and hears sets made while
 * it is mounted through `onRegistryEntryRequest`.
 */

/** Filters a tab opens with (Spec 5.5). Applied once, on top of the
 * view state the visit already has — a preset never overrides a
 * filter the player changed themselves. */
export interface RegistryEntryPreset {
  /** Display name to select in the nation dropdown (matched like a
   * hand-picked value — normalized `name`, Spec 3.7). */
  nation?: string;
  /** Switch the registered `assigned_to_me` table filter extension
   * (lib/tableFilterExtensions.ts) to «Да». */
  assignedToMe?: true;
}

export interface RegistryEntryRequest {
  /** Table id to select (e.g. 'orders'). */
  tab: string;
  /** Cell action to run once the tab's rows are loaded. */
  action?: string;
  /** Filters the tab opens with. */
  preset?: RegistryEntryPreset;
}

const ORDER_HASH_RE = /^#registry\/order-(\d{1,9})$/;

/**
 * `#registry/order-N` → `{tab: 'orders', action: 'order:N'}`.
 * 1–9 digits; anything else (more digits, non-digits, other suffixes)
 * returns null and is ignored by the caller.
 */
export function parseRegistryOrderHash(
  hash: string,
): RegistryEntryRequest | null {
  const match = ORDER_HASH_RE.exec(hash);
  return match ? { tab: 'orders', action: `order:${match[1]}` } : null;
}

let pending: RegistryEntryRequest | null = null;

const listeners = new Set<(request: RegistryEntryRequest) => void>();

/** Store the request that PanelRegistry will receive on open; mounted
 * panels listening via `onRegistryEntryRequest` hear it immediately. */
export function setRegistryEntryRequest(
  request: RegistryEntryRequest | null,
): void {
  pending = request;
  if (request !== null) {
    for (const listener of listeners) {
      listener(request);
    }
  }
}

/** Read the pending request once — a read consumes it. */
export function takeRegistryEntryRequest(): RegistryEntryRequest | null {
  const request = pending;
  pending = null;
  return request;
}

/**
 * Subscribe a mounted panel to later `setRegistryEntryRequest` calls.
 * Returns the unsubscribe; the panel must still take the stored
 * request itself — sets made before the subscribe reach only
 * `takeRegistryEntryRequest`.
 */
export function onRegistryEntryRequest(
  listener: (request: RegistryEntryRequest) => void,
): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
