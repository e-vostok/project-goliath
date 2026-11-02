/**
 * Application reservations (0.13.0 unit 8, Spec 00_core_applications
 * §11): province groups held by PENDING nation applications. The wire
 * payload is deliberately anonymous — group lists of bare ids, no
 * applicant id, name or colour (APP-6).
 */

import type { MapStateDTO } from '../types';

/** Hover-hint sentence for a reserved province (Spec §11). */
export const RESERVED_TOOLTIP =
  'Территория зарезервирована игроком, подавшим анкету';

/** Title line of the reserved-province tooltip (design 24_karta_rezerv). */
export const RESERVED_TITLE = 'Зарезервировано';

/**
 * province_id → reservation group index, from a state payload.
 * `validIds` (the manifest node-id set) drops ids outside the active
 * manifest — the same guard `buildOwnerMap` applies to owners (Spec
 * 1.9): a stale payload can never light up a node that is not there.
 */
export function buildReservationMap(
  state: MapStateDTO | null,
  validIds?: { has(id: number): boolean },
): Map<number, number> {
  const reserved = new Map<number, number>();
  if (!state) {
    return reserved;
  }
  state.reservations.forEach((group, index) => {
    for (const id of group) {
      if (validIds && !validIds.has(id)) {
        continue;
      }
      reserved.set(id, index);
    }
  });
  return reserved;
}
