/**
 * lib/nationOptions.ts — the option list of the `select_or_contains`
 * filter (Spec 3.7). The dropdown lists every nation the Registry
 * knows — the name cells of the «nations» table. When that table is
 * missing or failed to load, the fallback is the nation cells of the
 * rows already shown in the current table. Pure functions.
 */

import { isNationCell } from '../types';
import type { RegistryRowsDTO, RegistryTableDTO } from '../types';

const ruCollator = new Intl.Collator('ru', { sensitivity: 'base' });

function uniqueSorted(names: Iterable<string>): string[] {
  const seen = new Set<string>();
  for (const name of names) {
    const trimmed = name.trim();
    if (trimmed !== '') {
      seen.add(trimmed);
    }
  }
  return [...seen].sort(ruCollator.compare);
}

/**
 * Nation names from a table's own name column — the «nations» table.
 * The column may carry a plain string (today's shape) or a `nation`
 * cell (the future 6b shape) — both yield the short `name`. Returns
 * null when the table or a usable name column is not there; the
 * caller then falls back to `nationNamesOfRows`.
 */
export function nationNamesOfTable(
  table: RegistryTableDTO | null,
  rows: RegistryRowsDTO | null,
): string[] | null {
  if (table === null || rows === null || rows.table_id !== table.id) {
    return null;
  }
  const column =
    table.columns.find((c) => c.id === 'name') ??
    table.columns.find((c) => c.type === 'text');
  if (column === undefined) {
    return null;
  }
  return uniqueSorted(
    rows.rows
      .map((row) => row.cells[column.id])
      .map((cell) =>
        typeof cell === 'string'
          ? cell
          : isNationCell(cell)
            ? cell.name
            : null,
      )
      .filter((name): name is string => name !== null),
  );
}

/** Fallback: the nation cells visible in a table's own rows. */
export function nationNamesOfRows(rows: RegistryRowsDTO | null): string[] {
  if (rows === null) {
    return [];
  }
  return uniqueSorted(
    rows.rows.flatMap((row) =>
      Object.values(row.cells)
        .filter(isNationCell)
        .map((cell) => cell.name),
    ),
  );
}
