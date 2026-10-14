/**
 * lib/tableView.ts — client-side sort, filters and search for the
 * «Реестр» tables (Spec 03_registry, section 3.7). Pure functions:
 * no React, no DOM, no Date objects (game dates arrive as text).
 */

import type {
  RegistryCell,
  RegistryColumnDTO,
  RegistryRowDTO,
  RegistryTableDTO,
} from '../types';

/* ------------------------------------------------------------- state */

export type SortDirection = 'asc' | 'desc';

export interface SortState {
  columnId: string;
  direction: SortDirection;
}

export interface TextFilter {
  kind: 'text';
  value: string;
}

/** Bounds kept as raw input; empty/unparsable bound does not limit. */
export interface NumberRangeFilter {
  kind: 'number_range';
  from: string;
  to: string;
}

/** Calendar bounds 'YYYY-MM-DD' — parsed by days-from-civil, never Date. */
export interface DateRangeFilter {
  kind: 'date_range';
  from: string;
  to: string;
}

export interface PresenceFilter {
  kind: 'presence';
  value: 'has' | 'none';
}

export type ColumnFilterValue =
  | TextFilter
  | NumberRangeFilter
  | DateRangeFilter
  | PresenceFilter;

/** View state of one tab: sort, per-column filters, the shared search
 * and whether the filter panel is open. */
export interface TableView {
  sort: SortState | null;
  filters: Record<string, ColumnFilterValue[]>;
  search: string;
  filtersOpen: boolean;
}

export const EMPTY_VIEW: TableView = {
  sort: null,
  filters: {},
  search: '',
  filtersOpen: false,
};

const ruCollator = new Intl.Collator('ru', { sensitivity: 'base' });

/* ---------------------------------------------------------- sort key */

function cellProp(cell: RegistryCell | undefined, prop: string): unknown {
  return typeof cell === 'object' && cell !== null
    ? (cell as unknown as Record<string, unknown>)[prop]
    : undefined;
}

/** Spec 3.7: the comparison key of a cell; null when the cell is empty. */
export function cellSortKey(
  column: Pick<RegistryColumnDTO, 'type'>,
  cell: RegistryCell | undefined,
): number | string | null {
  if (cell == null) {
    return null;
  }
  switch (column.type) {
    case 'index':
    case 'integer':
    case 'gauge':
      return typeof cell === 'number' ? cell : null;
    case 'text':
      return typeof cell === 'string' ? cell : null;
    case 'date': {
      const key = cellProp(cell, 'key');
      return typeof key === 'number' ? key : null;
    }
    case 'person':
    case 'nation': {
      const name = cellProp(cell, 'name');
      return typeof name === 'string' ? name : null;
    }
    default:
      return null;
  }
}

/** Text used by the `text` filter and by the shared search. */
function cellText(
  column: Pick<RegistryColumnDTO, 'type'>,
  cell: RegistryCell | undefined,
): string | null {
  if (cell == null) {
    return null;
  }
  if (column.type === 'person' || column.type === 'nation') {
    const name = cellProp(cell, 'name');
    return typeof name === 'string' ? name : null;
  }
  if (column.type === 'date') {
    const text = cellProp(cell, 'text');
    return typeof text === 'string' ? text : null;
  }
  return typeof cell === 'string' ? cell : null;
}

/* --------------------------------------------------- days from civil */

/**
 * Days since 1970-01-01 from Y-M-D components (Howard Hinnant's
 * days_from_civil). Pure arithmetic — never `new Date(string)`, never
 * time zones.
 */
export function daysFromCivil(y: number, m: number, d: number): number {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400; // [0, 399]
  const mp = m > 2 ? m - 3 : m + 9; // [0, 11]
  const doy = Math.floor((153 * mp + 2) / 5) + d - 1; // [0, 365]
  const doe =
    yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

/** 'YYYY-MM-DD' → days since epoch, or null when the input is not a date. */
export function parseDateBound(text: string): number | null {
  const m = /^(\d{1,6})-(\d{1,2})-(\d{1,2})$/.exec(text.trim());
  if (!m) {
    return null;
  }
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (mo < 1 || mo > 12 || d < 1 || d > 31) {
    return null;
  }
  return daysFromCivil(y, mo, d);
}

/* ------------------------------------------------------- match rules */

function normalizeText(s: string): string {
  return s.trim().toLowerCase().replace(/ё/g, 'е');
}

/**
 * `text` filter / shared search (Spec 3.7): "contains", case-insensitive,
 * ё equals е, edges trimmed; an empty condition does not filter.
 */
export function matchText(cellValue: string | null, condition: string): boolean {
  const needle = normalizeText(condition);
  if (!needle) {
    return true;
  }
  if (cellValue == null) {
    return false;
  }
  return normalizeText(cellValue).includes(needle);
}

function parseNumberBound(s: string): number | null {
  const t = s.trim();
  if (!t) {
    return null;
  }
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/**
 * `number_range` (Spec 3.7): inclusive bounds; an empty bound does not
 * limit. `key` is the cell number or `date.key`; null key never matches
 * a bounded range.
 */
export function matchNumberRange(
  key: number | null,
  from: string,
  to: string,
): boolean {
  const lo = parseNumberBound(from);
  const hi = parseNumberBound(to);
  if (lo === null && hi === null) {
    return true;
  }
  if (key === null) {
    return false;
  }
  return (lo === null || key >= lo) && (hi === null || key <= hi);
}

/**
 * `date_range` (Spec 3.7): calendar bounds converted to days since epoch
 * by days-from-civil and compared with `date.key`.
 */
export function matchDateRange(
  key: number | null,
  from: string,
  to: string,
): boolean {
  const lo = parseDateBound(from);
  const hi = parseDateBound(to);
  if (lo === null && hi === null) {
    return true;
  }
  if (key === null) {
    return false;
  }
  return (lo === null || key >= lo) && (hi === null || key <= hi);
}

export function matchColumnFilter(
  column: RegistryColumnDTO,
  cell: RegistryCell | undefined,
  filter: ColumnFilterValue,
): boolean {
  switch (filter.kind) {
    case 'text':
      return matchText(cellText(column, cell), filter.value);
    case 'number_range': {
      const key = cellSortKey(column, cell);
      return matchNumberRange(
        typeof key === 'number' ? key : null,
        filter.from,
        filter.to,
      );
    }
    case 'date_range': {
      const key = cellSortKey(column, cell);
      return matchDateRange(
        typeof key === 'number' ? key : null,
        filter.from,
        filter.to,
      );
    }
    case 'presence':
      return filter.value === 'has' ? cell != null : cell == null;
    default:
      return true;
  }
}

/** Shared search: OR over `searchable` columns (name for person/nation). */
export function matchSearch(
  table: RegistryTableDTO,
  row: RegistryRowDTO,
  search: string,
): boolean {
  if (!normalizeText(search)) {
    return true;
  }
  return table.columns.some(
    (col) =>
      col.searchable && matchText(cellText(col, row.cells[col.id]), search),
  );
}

/* ------------------------------------------------------- view helper */

/** Tri-state cycle: none → asc → desc → none (back to default order). */
export function nextSort(
  current: SortState | null,
  columnId: string,
): SortState | null {
  if (!current || current.columnId !== columnId) {
    return { columnId, direction: 'asc' };
  }
  if (current.direction === 'asc') {
    return { columnId, direction: 'desc' };
  }
  return null;
}

/** Whether a filter entry actually constrains the table. */
export function isFilterActive(filter: ColumnFilterValue): boolean {
  switch (filter.kind) {
    case 'text':
      return normalizeText(filter.value) !== '';
    case 'number_range':
    case 'date_range':
      return filter.from.trim() !== '' || filter.to.trim() !== '';
    case 'presence':
      return true;
    default:
      return false;
  }
}

/** Anything set that «Сбросить» would clear (search + filters). */
export function hasActiveFilters(view: TableView): boolean {
  return (
    normalizeText(view.search) !== '' ||
    Object.values(view.filters).some((list) => list.some(isFilterActive))
  );
}

/* ---------------------------------------------------------- apply all */

/**
 * Applies the whole view — column filters AND shared search (ANDed), then
 * the column sort — and returns the shown rows.
 *
 * Sort is stable: equal keys keep the default order, and empty values
 * always come last in both directions. `sort: null` returns the rows in
 * the order the server sent (already `default_sort`-ordered).
 */
export function applyView(
  table: RegistryTableDTO,
  rows: RegistryRowDTO[],
  view: TableView,
): RegistryRowDTO[] {
  const filtered = rows.filter(
    (row) =>
      table.columns.every((col) => {
        const list = view.filters[col.id];
        if (!list || list.length === 0) {
          return true;
        }
        return list.every((f) => matchColumnFilter(col, row.cells[col.id], f));
      }) && matchSearch(table, row, view.search),
  );

  if (!view.sort) {
    return filtered;
  }
  const col = table.columns.find((c) => c.id === view.sort?.columnId);
  if (!col || !col.sortable) {
    return filtered;
  }

  const dir = view.sort.direction === 'asc' ? 1 : -1;
  const decorated = filtered.map((row, i) => ({
    row,
    i,
    key: cellSortKey(col, row.cells[col.id]),
  }));
  decorated.sort((a, b) => {
    const [ka, kb] = [a.key, b.key];
    if (ka == null && kb == null) {
      return a.i - b.i;
    }
    if (ka == null) {
      return 1;
    }
    if (kb == null) {
      return -1;
    }
    const cmp =
      typeof ka === 'number' && typeof kb === 'number'
        ? ka - kb
        : ruCollator.compare(String(ka), String(kb));
    return cmp === 0 ? a.i - b.i : cmp * dir;
  });
  return decorated.map((d) => d.row);
}
