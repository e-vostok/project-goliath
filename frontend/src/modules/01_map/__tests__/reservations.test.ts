/**
 * buildReservationMap (0.13.0 unit 8, Spec applications §11): the wire
 * `reservations` group lists become province_id → group index, limited
 * to the manifest node set — anonymous by construction (APP-6).
 */

import { buildReservationMap } from '../lib/reservations';
import { MINI_MANIFEST, MINI_STATE } from '../fixtures/miniMap';
import type { MapStateDTO } from '../types';

const VALID = new Set(MINI_MANIFEST.nodes.map((n) => n.id));

describe('buildReservationMap', () => {
  it('maps every group member to its index, in wire order', () => {
    const state: MapStateDTO = {
      ...MINI_STATE,
      reservations: [
        [1005, 1006],
        [1008],
      ],
    };
    const map = buildReservationMap(state, VALID);
    expect([...map.entries()]).toEqual([
      [1005, 0],
      [1006, 0],
      [1008, 1],
    ]);
  });

  it('drops ids outside the manifest; a group can shrink to nothing', () => {
    const state: MapStateDTO = {
      ...MINI_STATE,
      reservations: [
        [1003, 9999],
        [9998],
      ],
    };
    const map = buildReservationMap(state, VALID);
    expect([...map.entries()]).toEqual([[1003, 0]]);
  });

  it('null state and an empty payload both yield an empty map', () => {
    expect(buildReservationMap(null, VALID).size).toBe(0);
    expect(buildReservationMap(MINI_STATE, VALID).size).toBe(0);
  });
});
