/**
 * tableView — Spec 3.7 semantics: tri-state sort (empties last in both
 * directions, Russian collation, stable), the four filter kinds, and
 * the shared search ANDed with column filters. Pure functions.
 */

import {
  applyView,
  daysFromCivil,
  EMPTY_VIEW,
  matchText,
  nextSort,
  parseDateBound,
  type TableView,
} from '../lib/tableView';
import type { RegistryTableDTO } from '../types';
import {
  NATIONS_ROWS,
  PLAYERS_ROWS,
  TABLES,
} from './helpers';

const playersTable = TABLES.tables.find(
  (t): t is RegistryTableDTO => t.id === 'players',
)!;
const nationsTable = TABLES.tables.find(
  (t): t is RegistryTableDTO => t.id === 'nations',
)!;

const keys = (view: TableView, table = playersTable) =>
  applyView(
    table,
    table === playersTable ? PLAYERS_ROWS.rows : NATIONS_ROWS.rows,
    view,
  ).map((r) => r.key);

describe('tableView — sort', () => {
  it('cycles asc → desc → default and keeps nulls last in both directions', () => {
    // person names: Борис Иванов(p1) Анна Смирнова(p2) Игрок №3(p3)
    let sort = nextSort(null, 'player');
    expect(sort).toEqual({ columnId: 'player', direction: 'asc' });
    expect(keys({ ...EMPTY_VIEW, sort })).toEqual(['p2', 'p1', 'p3']);

    sort = nextSort(sort, 'player');
    expect(sort?.direction).toBe('desc');
    expect(keys({ ...EMPTY_VIEW, sort })).toEqual(['p3', 'p1', 'p2']);

    sort = nextSort(sort, 'player');
    expect(sort).toBeNull();
    expect(keys({ ...EMPTY_VIEW, sort })).toEqual(['p1', 'p2', 'p3']);

    // nation names: Новгород(p1) null(p2) Рязань(p3) — null last both ways
    expect(
      keys({
        ...EMPTY_VIEW,
        sort: { columnId: 'nation', direction: 'asc' },
      }),
    ).toEqual(['p1', 'p3', 'p2']);
    expect(
      keys({
        ...EMPTY_VIEW,
        sort: { columnId: 'nation', direction: 'desc' },
      }),
    ).toEqual(['p3', 'p1', 'p2']);
  });

  it('sorts strings with the Russian collation (ё ≈ е), stable on ties', () => {
    const table: RegistryTableDTO = {
      ...nationsTable,
      columns: nationsTable.columns.map((c) =>
        c.id === 'name' ? c : { ...c, sortable: false },
      ),
    };
    const rows = [
      { key: 'a', cells: { name: 'Ясен' } },
      { key: 'b', cells: { name: 'Ёлка' } },
      { key: 'c', cells: { name: 'Азов' } },
      { key: 'd', cells: { name: 'ёлка' } }, // ties with 'Ёлка' → keeps order
    ];
    const out = applyView(table, rows, {
      ...EMPTY_VIEW,
      sort: { columnId: 'name', direction: 'asc' },
    });
    expect(out.map((r) => r.key)).toEqual(['c', 'b', 'd', 'a']);
  });
});

describe('tableView — filters', () => {
  it('text filter: contains, case-insensitive, ё=е, trims, empty passes', () => {
    expect(matchText('Ёлкино', 'елк')).toBe(true);
    expect(matchText('Иван Петров', '  ИВАН  ')).toBe(true);
    expect(matchText('Иван Петров', 'сидор')).toBe(false);
    expect(matchText(null, 'x')).toBe(false);
    expect(matchText(null, '  ')).toBe(true); // empty condition does not filter

    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { player: [{ kind: 'text', value: 'смир' }] },
      }),
    ).toEqual(['p2']);
  });

  it('number_range: inclusive bounds, empty bound does not limit, uses date.key on date columns', () => {
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { level: [{ kind: 'number_range', from: '2', to: '' }] },
      }),
    ).toEqual(['p2']);
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { level: [{ kind: 'number_range', from: '', to: '1' }] },
      }),
    ).toEqual(['p1', 'p3']);
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { level: [{ kind: 'number_range', from: '', to: '' }] },
      }),
    ).toEqual(['p1', 'p2', 'p3']);

    // number_range on the `formed` date column compares with date.key
    expect(
      keys(
        {
          ...EMPTY_VIEW,
          filters: { formed: [{ kind: 'number_range', from: '20', to: '' }] },
        },
        nationsTable,
      ),
    ).toEqual(['n2']);
  });

  it('date_range: calendar bounds become days since epoch (no Date), compared with date.key', () => {
    // days-from-civil: epoch itself and leap-year boundary
    expect(daysFromCivil(1970, 1, 1)).toBe(0);
    expect(daysFromCivil(2000, 2, 29)).toBe(11016);
    expect(parseDateBound('2026-09-05')).toBe(20701);
    expect(parseDateBound('not a date')).toBeNull();

    expect(
      keys({
        ...EMPTY_VIEW,
        filters: {
          joined: [
            { kind: 'date_range', from: '2026-09-04', to: '2026-09-06' },
          ],
        },
      }),
    ).toEqual(['p2']);
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: {
          joined: [{ kind: 'date_range', from: '', to: '2026-09-02' }],
        },
      }),
    ).toEqual(['p1']);
  });

  it('presence: «есть» keeps non-null cells, «нет» keeps nulls', () => {
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { nation: [{ kind: 'presence', value: 'has' }] },
      }),
    ).toEqual(['p1', 'p3']);
    expect(
      keys({
        ...EMPTY_VIEW,
        filters: { nation: [{ kind: 'presence', value: 'none' }] },
      }),
    ).toEqual(['p2']);
  });
});

describe('tableView — search', () => {
  it('matches any searchable column (person/nation name) and ANDs with filters', () => {
    // 'ива' hits Борис Иванов (player name); nation of p3 is Рязань.
    expect(keys({ ...EMPTY_VIEW, search: 'иван' })).toEqual(['p1']);
    expect(keys({ ...EMPTY_VIEW, search: 'рязань' })).toEqual(['p3']);

    // AND: search hit on p1 but level filter excludes it
    expect(
      keys({
        ...EMPTY_VIEW,
        search: 'иван',
        filters: { level: [{ kind: 'number_range', from: '5', to: '' }] },
      }),
    ).toEqual([]);
  });
});
