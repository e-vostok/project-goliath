/**
 * DTO types for module 03_registry (Spec 5.1, 5.2).
 * Mirrors backend/src/modules/_03_registry/schemas.py — the `source`
 * fields of the config never reach the client; cells are addressed by
 * column id.
 */

export interface RegistryLayoutDTO {
  tabs_position: 'top' | 'right';
}

export type RegistryColumnType =
  | 'index'
  | 'integer'
  | 'gauge'
  | 'text'
  | 'date'
  | 'datetime'
  | 'action_text'
  | 'person'
  | 'nation'
  | 'flag';

export type RegistryFilterKind =
  | 'text'
  | 'number_range'
  | 'date_range'
  | 'presence'
  | 'select_or_contains';

/** `header_icon` values the schema allows — the three order stages. */
export type RegistryHeaderIcon =
  | 'stage_submitted'
  | 'stage_distributed'
  | 'stage_verdict';

export interface RegistryColumnDTO {
  id: string;
  title: string;
  type: RegistryColumnType | string;
  width_px: number;
  sortable: boolean;
  filters: RegistryFilterKind[] | string[];
  filter_label: string | null;
  header_icon: RegistryHeaderIcon | string | null;
  searchable: boolean;
  stub: boolean;
  scale_min: number | null;
  scale_max: number | null;
}

export interface RegistryDefaultSortDTO {
  column: string;
  direction: 'asc' | 'desc';
}

export interface RegistryTableDTO {
  id: string;
  title: string;
  icon: string;
  empty_text: string;
  default_sort: RegistryDefaultSortDTO;
  columns: RegistryColumnDTO[];
}

export interface RegistryTablesDTO {
  layout: RegistryLayoutDTO;
  tables: RegistryTableDTO[];
}

/* Cell shapes — Spec 3.6 (Spec 1.2 adds datetime / action_text). */

export interface RegistryDateCell {
  text: string;
  key: number;
}

/**
 * `datetime` cell: display lines `date`/`time`, sort key `key` (Unix
 * seconds), `day` for the `date_range` filter; an empty cell has all
 * four null and may still carry `mark` ("overdue").
 */
export interface RegistryDatetimeCell {
  date: string | null;
  time: string | null;
  key: number | null;
  day: number | null;
  mark: 'overdue' | string | null;
}

export interface RegistryActionTextCell {
  text: string;
  action: string;
}

export interface RegistryPersonCell {
  name: string;
  avatar_url: string | null;
  is_fallback: boolean;
}

export interface RegistryFlagCell {
  color: string;
  image_url: string | null;
}

export interface RegistryNationCell {
  id: string | null;
  name: string;
  color: string;
  flag_url: string | null;
}

export type RegistryCell =
  | number
  | string
  | RegistryDateCell
  | RegistryDatetimeCell
  | RegistryActionTextCell
  | RegistryPersonCell
  | RegistryFlagCell
  | RegistryNationCell
  | null;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

export function isDateCell(v: RegistryCell): v is RegistryDateCell {
  return isRecord(v) && typeof v.text === 'string' && typeof v.key === 'number';
}

export function isDatetimeCell(v: RegistryCell): v is RegistryDatetimeCell {
  return isRecord(v) && 'key' in v && 'day' in v && 'mark' in v;
}

export function isActionTextCell(
  v: RegistryCell,
): v is RegistryActionTextCell {
  return (
    isRecord(v) && typeof v.text === 'string' && typeof v.action === 'string'
  );
}

export function isPersonCell(v: RegistryCell): v is RegistryPersonCell {
  return isRecord(v) && typeof v.name === 'string';
}

export function isFlagCell(v: RegistryCell): v is RegistryFlagCell {
  return isRecord(v) && typeof v.color === 'string' && 'image_url' in v;
}

export function isNationCell(v: RegistryCell): v is RegistryNationCell {
  return (
    isRecord(v) &&
    'id' in v &&
    (v.id === null || typeof v.id === 'string') &&
    typeof v.name === 'string' &&
    typeof v.color === 'string' &&
    'flag_url' in v
  );
}

export interface RegistryRowDTO {
  key: string;
  cells: Record<string, RegistryCell>;
}

export interface RegistryRowsDTO {
  table_id: string;
  total: number;
  truncated: boolean;
  generated_at: string;
  rows: RegistryRowDTO[];
}
