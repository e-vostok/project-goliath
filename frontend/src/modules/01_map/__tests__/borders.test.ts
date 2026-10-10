/**
 * Border layer (map2_4, map2_14): pair classification — same owner or
 * both free → internal; different owners or owned-vs-free → state;
 * every coast → coast, owned or not — spatial chunking (every piece in
 * exactly one cell, the union of cells is the full set) and the
 * incremental rebuild when ownership moves.
 */

import {
  buildBorderLayer,
  reclassifyBorderLayer,
  type BorderClass,
  type BorderLayer,
} from '../lib/borders';
import { MINI_BORDERS, MINI_MANIFEST } from '../fixtures/miniMap';
import type { MapNationDTO } from '../types';

const NATION_A: MapNationDTO = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Тестия',
  color_hex: '#e64545',
};
const NATION_B: MapNationDTO = {
  id: 'b2c3d4e5-1111-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Другия',
  color_hex: '#00ff00',
};

const BOUNDS = MINI_MANIFEST.view_box;

function ownersOf(entries: [number, MapNationDTO][]) {
  return new Map<number, MapNationDTO>(entries);
}

/** Every full-geometry `d` of one class, joined across all cells —
 *  cell order, not payload order: membership is what matters. */
function classGeometry(layer: BorderLayer, cls: BorderClass): string {
  return layer.chunks.high[cls].filter((d) => d !== null).join(' ');
}

/** `d` occurs exactly once in `joined`. */
function occursOnce(joined: string, d: string) {
  expect(joined.split(d)).toHaveLength(2);
}

describe('buildBorderLayer — classification', () => {
  it('both-free pairs are internal; every coast is coast', () => {
    const layer = buildBorderLayer(MINI_BORDERS, ownersOf([]), BOUNDS);

    expect(classGeometry(layer, 'state')).toBe('');
    const internal = classGeometry(layer, 'internal');
    for (const d of Object.values(MINI_BORDERS.pairs)) {
      occursOnce(internal, d);
    }
    for (const d of Object.values(MINI_BORDERS.coasts)) {
      occursOnce(classGeometry(layer, 'coast'), d);
    }
  });

  it('same-owner → internal, different owners and owned-vs-free → state', () => {
    const layer = buildBorderLayer(
      MINI_BORDERS,
      ownersOf([
        [1001, NATION_A],
        [1002, NATION_A], // same nation → internal
        [1003, NATION_B], // different nation → state
        // 1004 free → owned-vs-free is a state border
      ]),
      BOUNDS,
    );

    const internal = classGeometry(layer, 'internal');
    const state = classGeometry(layer, 'state');
    occursOnce(internal, MINI_BORDERS.pairs['1001-1002']);
    occursOnce(state, MINI_BORDERS.pairs['1002-1003']);
    occursOnce(state, MINI_BORDERS.pairs['1003-1004']);
    // Coasts never split by ownership — all eight nodes, owned or free.
    for (const d of Object.values(MINI_BORDERS.coasts)) {
      occursOnce(classGeometry(layer, 'coast'), d);
    }
  });
});

describe('buildBorderLayer — chunks and rebuilds (map2_14)', () => {
  it('every piece lands in exactly one cell and the union is the full set', () => {
    const layer = buildBorderLayer(
      MINI_BORDERS,
      ownersOf([[1003, NATION_A]]),
      BOUNDS,
      4,
    );

    // Each pair's original `d` appears exactly once across internal +
    // state cells; each coast `d` exactly once across coast cells.
    const internal = classGeometry(layer, 'internal');
    const state = classGeometry(layer, 'state');
    for (const d of Object.values(MINI_BORDERS.pairs)) {
      const hits =
        internal.split(d).length + state.split(d).length - 2;
      expect(hits).toBe(1);
    }
    for (const d of Object.values(MINI_BORDERS.coasts)) {
      occursOnce(classGeometry(layer, 'coast'), d);
    }
  });

  it('an ownership change rebuilds only the cells whose pairs flipped', () => {
    const grid = 4;
    const before = buildBorderLayer(
      MINI_BORDERS,
      ownersOf([
        [1003, NATION_A],
        [1004, NATION_B],
      ]),
      BOUNDS,
      grid,
    );

    // Nation A takes 1004 — the 1003-1004 pair flips state → internal.
    const after = reclassifyBorderLayer(
      before,
      ownersOf([
        [1003, NATION_A],
        [1004, NATION_A],
      ]),
    );

    const flippedCell = before.chunks.high.state.findIndex((d) =>
      d?.includes(MINI_BORDERS.pairs['1003-1004']),
    );
    expect(flippedCell).toBeGreaterThanOrEqual(0);

    for (let cell = 0; cell < grid * grid; cell += 1) {
      for (const lod of ['low', 'mid', 'high'] as const) {
        for (const cls of ['internal', 'state'] as const) {
          if (cell === flippedCell) {
            expect(after.chunks[lod][cls][cell]).not.toBe(
              before.chunks[lod][cls][cell],
            );
          } else {
            // Untouched cells keep their string reference — React
            // writes no `d` attribute for them.
            expect(after.chunks[lod][cls][cell]).toBe(
              before.chunks[lod][cls][cell],
            );
          }
        }
      }
    }
    expect(classGeometry(after, 'internal')).toContain(
      MINI_BORDERS.pairs['1003-1004'],
    );
    expect(classGeometry(after, 'state')).not.toContain(
      MINI_BORDERS.pairs['1003-1004'],
    );

    // No ownership change → the same layer object, zero rebuilds.
    expect(reclassifyBorderLayer(after, ownersOf([
      [1003, NATION_A],
      [1004, NATION_A],
    ]))).toBe(after);
  });
});
