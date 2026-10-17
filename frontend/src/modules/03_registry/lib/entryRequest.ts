/**
 * lib/entryRequest.ts — the «open the Registry on X» handoff
 * (Spec 04_orders 5.5).
 *
 * `normalizeEntryHash` (AppShell) runs before the router exists, so a
 * recognized `#registry/order-<1-9 digits>` hash is stored here as a
 * pending request; AppShell passes it to PanelRegistry, which selects
 * the requested tab if it exists and runs the action once its rows
 * are loaded — the same call a cell click makes.
 */

export interface RegistryEntryRequest {
  /** Table id to select (e.g. 'orders'). */
  tab: string;
  /** Cell action to run once the tab's rows are loaded. */
  action: string;
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

/** Store the request that PanelRegistry will receive on open. */
export function setRegistryEntryRequest(
  request: RegistryEntryRequest | null,
): void {
  pending = request;
}

/** Read the pending request once — a read consumes it. */
export function takeRegistryEntryRequest(): RegistryEntryRequest | null {
  const request = pending;
  pending = null;
  return request;
}
