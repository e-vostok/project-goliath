/**
 * Colour assignment: owner colour → neutral land → sea; plus the
 * owners-table decoding of MapStateDTO.
 */

import { buildOwnerMap, nodeFill } from '../lib/colors';
import type { MapNodeDTO, MapStateDTO } from '../types';

const COLORS = {
  neutral_province: '#8C8C8C',
  sea: '#1E3547',
  outside: '#2A2A2A',
  inland_water: '#3E6B84',
  province_border: '#3A3A3A',
  hover: '#FFFFFF',
  selected: '#FFD24A',
};

const land: MapNodeDTO = {
  id: 1,
  key: 'land',
  kind: 'LAND',
  name: 'Land',
  name_ru: null,
  anchor: [0, 0],
  bbox: [0, 0, 1, 1],
  area: 1,
};
const sea: MapNodeDTO = { ...land, id: 2, key: 'sea_x', kind: 'SEA' };

const NATION = { id: 'n1', name: 'Тестия', color_hex: '#e64545' };

describe('nodeFill', () => {
  it('paints an owned province in the owner colour', () => {
    expect(nodeFill(land, NATION, COLORS)).toBe('#e64545');
  });
  it('paints a free province neutral', () => {
    expect(nodeFill(land, undefined, COLORS)).toBe(COLORS.neutral_province);
  });
  it('paints a sea zone in the sea colour even if an owner leaks in', () => {
    expect(nodeFill(sea, undefined, COLORS)).toBe(COLORS.sea);
    expect(nodeFill(sea, NATION, COLORS)).toBe(COLORS.sea);
  });
});

describe('buildOwnerMap', () => {
  const state: MapStateDTO = {
    geometry_version: 'v1',
    turn: 3,
    nations: [NATION, { id: 'n2', name: 'Другия', color_hex: '#00ff00' }],
    owners: [
      [1, 0],
      [5, 1],
      [6, 0],
    ],
  };

  it('maps province ids to nation DTOs by index', () => {
    const owners = buildOwnerMap(state);
    expect(owners.get(1)?.name).toBe('Тестия');
    expect(owners.get(5)?.color_hex).toBe('#00ff00');
    expect(owners.get(6)?.name).toBe('Тестия');
    expect(owners.size).toBe(3);
  });

  it('is empty for null state and skips dangling indexes', () => {
    expect(buildOwnerMap(null).size).toBe(0);
    const broken: MapStateDTO = { ...state, owners: [[9, 99]] };
    expect(buildOwnerMap(broken).size).toBe(0);
  });

  it('drops owner entries for ids outside the manifest (retired nodes)', () => {
    // Spec 1.9: a state payload can still mention a withdrawn node id;
    // the valid-id set keeps it out of the painted map.
    const validIds = new Set([1, 6]);
    const owners = buildOwnerMap(state, validIds);
    expect(owners.size).toBe(2);
    expect(owners.has(5)).toBe(false);
    expect(owners.get(1)?.name).toBe('Тестия');
  });

  it('accepts an id-keyed Map as the valid-id source', () => {
    const nodesById = new Map<number, MapNodeDTO>([
      [1, land],
      [5, { ...land, id: 5, key: 'land5' }],
    ]);
    const owners = buildOwnerMap(state, nodesById);
    expect(owners.size).toBe(2);
    expect(owners.has(6)).toBe(false);
  });
});
