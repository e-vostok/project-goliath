/**
 * lib/mapEntryRequest.ts — the «open the map on province P» handoff
 * (version 0.9.0, unit 14c). The nation subscreen's «Показать на
 * карте» stores the capital's id here before navigating to `#/map`;
 * PanelMap is always mounted inside the VKUI View, so it takes the
 * request when its panel becomes active and the manifest is loaded —
 * the same select+centre a click on a map node performs.
 */

export interface MapEntryRequest {
  /** Province (map node) id to select and centre on. */
  provinceId: number;
}

let pending: MapEntryRequest | null = null;

/** Store the request PanelMap consumes on activation. */
export function setMapEntryRequest(request: MapEntryRequest | null): void {
  pending = request;
}

/** Read the pending request once — a read consumes it. */
export function takeMapEntryRequest(): MapEntryRequest | null {
  const request = pending;
  pending = null;
  return request;
}
