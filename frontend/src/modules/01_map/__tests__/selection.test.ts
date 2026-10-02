/**
 * Selection logic for `MapView mode="select"` / ProvincePicker — pure,
 * table-driven (Spec Part 5 + 3.3: connectivity over land/strait edges).
 *
 * Mini-map layout: land chain 1001-1002-1003-1004, strait-linked
 * 1005-1006-1007, coast-only 1008 (no land/strait edge — isolated),
 * sea 2001/2002. Owners mark 1001/1002 as taken.
 */

import {
  components,
  describeConnectivity,
  fitBBoxOfSelection,
  isSelectable,
  isSelectionValid,
  refusalHint,
  selectTooltipStatus,
  toggle,
  type SelectionContext,
} from '../lib/selection';
import {
  MINI_MANIFEST,
  MINI_STATE,
  MINI_STATE_EMPTY,
} from '../fixtures/miniMap';
import { buildOwnerMap } from '../lib/colors';
import type { MapNodeDTO } from '../types';

const EDGES = MINI_MANIFEST.edges;
const RULES_CONNECTED = { require_connected_start: true };
const RULES_FREE = { require_connected_start: false };
const LIMITS = { min: 2, max: 3 };

const nodeById = (id: number): MapNodeDTO => {
  const node = MINI_MANIFEST.nodes.find((n) => n.id === id);
  if (!node) {
    throw new Error(`fixture node ${id} missing`);
  }
  return node;
};

const ctx = (
  overrides: Partial<SelectionContext> = {},
): SelectionContext => ({
  nodes: new Map(MINI_MANIFEST.nodes.map((n) => [n.id, n])),
  owners: buildOwnerMap(MINI_STATE), // 1001 + 1002 owned by «Тестия»
  max: LIMITS.max,
  ...overrides,
});

const freeCtx = (overrides: Partial<SelectionContext> = {}): SelectionContext =>
  ctx({ owners: buildOwnerMap(MINI_STATE_EMPTY), ...overrides });

describe('isSelectable', () => {
  it.each([
    ['a free land province', 1003, MINI_STATE, 'OK'],
    ['an occupied land province', 1001, MINI_STATE, 'OCCUPIED'],
    ['a sea zone', 2001, MINI_STATE, 'SEA'],
  ] as const)('%s → %s', (_label, id, state, expected) => {
    expect(isSelectable(nodeById(id), { owners: buildOwnerMap(state) })).toBe(
      expected,
    );
  });

  it('an occupied-then-freed province becomes selectable again', () => {
    expect(
      isSelectable(nodeById(1001), {
        owners: buildOwnerMap(MINI_STATE_EMPTY),
      }),
    ).toBe('OK');
  });
});

describe('toggle', () => {
  it.each([
    // label, selection, click id, context, expected result
    [
      'adds a free land id at the end (click order kept)',
      [] as number[],
      1003,
      ctx(),
      { ok: true, selection: [1003] },
    ],
    [
      'toggles a selected id off',
      [1003, 1004],
      1003,
      ctx(),
      { ok: true, selection: [1004] },
    ],
    [
      'toggling twice returns to the start (select → deselect → select)',
      [] as number[],
      1003,
      ctx(),
      { ok: true, selection: [1003] },
    ],
    [
      'refuses a sea zone',
      [],
      2001,
      ctx(),
      { ok: false, reason: 'SEA' },
    ],
    [
      'refuses an occupied province',
      [],
      1001,
      ctx(),
      { ok: false, reason: 'OCCUPIED' },
    ],
    [
      'refuses an unknown id',
      [],
      9999,
      ctx(),
      { ok: false, reason: 'NOT_FOUND' },
    ],
    [
      'refuses beyond the maximum',
      [1003, 1004, 1005],
      1006,
      ctx(),
      { ok: false, reason: 'MAX_REACHED' },
    ],
    [
      'the maximum is not enforced while rules are unknown (max=null)',
      [1003, 1004, 1005, 1006, 1007],
      1008,
      freeCtx({ max: null }),
      { ok: true, selection: [1003, 1004, 1005, 1006, 1007, 1008] },
    ],
  ])('%s', (_label, selection, id, context, expected) => {
    expect(toggle(selection, id, context)).toEqual(expected);
  });

  it('toggle on then off then on keeps the click order', () => {
    let selection: number[] = [];
    const step = (id: number) => {
      const result = toggle(selection, id, ctx());
      if (result.ok) {
        selection = result.selection;
      }
    };
    step(1003);
    step(1004);
    step(1003); // off
    step(1005);
    expect(selection).toEqual([1004, 1005]);
  });
});

describe('components', () => {
  it.each([
    ['empty selection', [] as number[], 0],
    ['one province is one component', [1003], 1],
    ['two land neighbours', [1003, 1004], 1],
    ['a whole land chain', [1001, 1002, 1003, 1004], 1],
    ['two provinces connected only by a strait', [1005, 1006], 1],
    [
      'a strait chain of three',
      [1005, 1006, 1007],
      1,
    ],
    ['two far provinces give two components', [1003, 1005], 2],
    [
      'a coast-only neighbour does NOT connect (1008 only borders sea)',
      [1008, 1003],
      2,
    ],
    ['three islands give three components', [1003, 1005, 1008], 3],
    ['duplicate ids collapse', [1003, 1003, 1004], 1],
    [
      'edges through unselected nodes do not connect (1003–1005 have no path)',
      [1004, 1005],
      2,
    ],
  ])('%s', (_label, selection, expectedCount) => {
    expect(components(selection, EDGES)).toHaveLength(expectedCount);
  });

  it('returns the members of each component', () => {
    const parts = components([1003, 1005, 1004], EDGES);
    expect(parts.map((p) => p.slice().sort())).toEqual([
      [1003, 1004],
      [1005],
    ]);
  });
});

describe('describeConnectivity', () => {
  it.each([
    [0, null],
    [1, 'Территория связна'],
    [2, 'Не связна: 2 части'],
    [3, 'Не связна: 3 части'],
    [5, 'Не связна: 5 частей'],
    [11, 'Не связна: 11 частей'],
    [21, 'Не связна: 21 часть'],
  ])('%i components → %j', (count, expected) => {
    expect(describeConnectivity(count)).toBe(expected);
  });
});

describe('isSelectionValid', () => {
  it.each([
    // label, selection, rules, limits, expected
    ['empty selection is never valid', [], RULES_CONNECTED, LIMITS, false],
    [
      'below the minimum',
      [1003],
      RULES_CONNECTED,
      LIMITS,
      false,
    ],
    [
      'connected, inside the bounds',
      [1003, 1004],
      RULES_CONNECTED,
      LIMITS,
      true,
    ],
    [
      'connected at the maximum',
      [1005, 1006, 1007],
      RULES_CONNECTED,
      LIMITS,
      true,
    ],
    [
      'disconnected is refused when the rule is on',
      [1003, 1005],
      RULES_CONNECTED,
      LIMITS,
      false,
    ],
    [
      'the same disconnected set is valid with require_connected_start off',
      [1003, 1005],
      RULES_FREE,
      LIMITS,
      true,
    ],
    [
      'unknown bounds do not gate (min/max null)',
      [1003],
      RULES_CONNECTED,
      { min: null, max: null },
      true,
    ],
  ])('%s', (_label, selection, rules, limits, expected) => {
    expect(isSelectionValid(selection, rules, limits, EDGES)).toBe(expected);
  });
});

describe('fitBBoxOfSelection', () => {
  it('unions the selected nodes bboxes', () => {
    // 1003: [20,20,30,30], 1005: [50,40,60,50]
    expect(fitBBoxOfSelection([1003, 1005], ctx().nodes)).toEqual([
      20, 20, 60, 50,
    ]);
  });

  it('skips unknown ids; null when nothing known is selected', () => {
    expect(fitBBoxOfSelection([9999], ctx().nodes)).toBeNull();
    expect(fitBBoxOfSelection([], ctx().nodes)).toBeNull();
    expect(fitBBoxOfSelection([9999, 1003], ctx().nodes)).toEqual([
      20, 20, 30, 30,
    ]);
  });
});

describe('refusalHint / selectTooltipStatus', () => {
  it.each([
    ['SEA', 3, 'Морскую зону выбрать нельзя'],
    ['OCCUPIED', 3, 'Эта провинция уже занята'],
    ['MAX_REACHED', 3, 'Выбрано максимум — 3 провинции'],
    ['MAX_REACHED', 1, 'Выбрано максимум — 1 провинция'],
    ['MAX_REACHED', null, 'Выбрано максимум провинций'],
    ['NOT_FOUND', 3, 'Провинция не найдена на карте'],
  ] as const)('%s (max=%s) → %s', (reason, max, expected) => {
    expect(refusalHint(reason, max)).toBe(expected);
  });

  it.each([
    ['free land', 1003, 'свободна'],
    ['occupied land', 1001, 'занята: Тестия'],
    ['sea', 2001, 'морская зона, выбрать нельзя'],
  ] as const)('tooltip for %s → «… %s»', (_label, id, suffix) => {
    const owner = buildOwnerMap(MINI_STATE).get(id);
    expect(selectTooltipStatus(nodeById(id), owner)).toBe(suffix);
  });
});
