/**
 * buildBorderPaths (map2_4): pair classification — same owner or both
 * free → internal; different owners or owned-vs-free → state; every
 * coast → coast, owned or not — and the rebuild when ownership moves.
 */

import { buildBorderPaths } from '../lib/borders';
import { MINI_BORDERS } from '../fixtures/miniMap';
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

const ALL_COAST = Object.values(MINI_BORDERS.coasts).join(' ');

function ownersOf(entries: [number, MapNationDTO][]) {
  return new Map<number, MapNationDTO>(entries);
}

describe('buildBorderPaths', () => {
  it('both-free pairs are internal; every coast is coast', () => {
    const paths = buildBorderPaths(MINI_BORDERS, ownersOf([]));

    expect(paths.state).toBe('');
    expect(paths.internal).toBe(
      Object.values(MINI_BORDERS.pairs).join(' '),
    );
    expect(paths.coast).toBe(ALL_COAST);
  });

  it('same-owner → internal, different owners and owned-vs-free → state', () => {
    const paths = buildBorderPaths(
      MINI_BORDERS,
      ownersOf([
        [1001, NATION_A],
        [1002, NATION_A], // same nation → internal
        [1003, NATION_B], // different nation → state
        // 1004 free → owned-vs-free is a state border
      ]),
    );

    expect(paths.internal).toBe(MINI_BORDERS.pairs['1001-1002']);
    expect(paths.state).toBe(
      [MINI_BORDERS.pairs['1002-1003'], MINI_BORDERS.pairs['1003-1004']].join(
        ' ',
      ),
    );
    // Coasts never split by ownership — all eight nodes, owned or free.
    expect(paths.coast).toBe(ALL_COAST);
  });

  it('a pair flips between internal and state when ownership changes', () => {
    const before = buildBorderPaths(
      MINI_BORDERS,
      ownersOf([
        [1003, NATION_A],
        [1004, NATION_B],
      ]),
    );
    expect(before.state).toContain(MINI_BORDERS.pairs['1003-1004']);
    expect(before.internal).not.toContain(MINI_BORDERS.pairs['1003-1004']);

    // Nation A takes 1004 — the same payload re-classifies.
    const after = buildBorderPaths(
      MINI_BORDERS,
      ownersOf([
        [1003, NATION_A],
        [1004, NATION_A],
      ]),
    );
    expect(after.internal).toContain(MINI_BORDERS.pairs['1003-1004']);
    expect(after.state).not.toContain(MINI_BORDERS.pairs['1003-1004']);
    expect(after.coast).toBe(ALL_COAST);
  });
});
