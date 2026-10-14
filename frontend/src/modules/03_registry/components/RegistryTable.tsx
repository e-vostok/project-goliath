/**
 * RegistryTable — the config-driven table of the «Реестр» (Spec 5.5).
 * Header cells offer tri-state sort (sortable columns) and the filter
 * dropdown (filterable columns); column widths come from `width_px`.
 * Rows arrive already filtered+sorted by lib/tableView.applyView.
 */

import {
  Icon16SortArrowDown,
  Icon16SortArrowUp,
} from '@vkontakte/icons';

import type {
  ColumnFilterValue,
  TableView,
} from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import type {
  RegistryCell,
  RegistryColumnDTO,
  RegistryRowDTO,
  RegistryTableDTO,
} from '../types';
import { ColumnFilter } from './ColumnFilter';
import { DateCell } from './cells/DateCell';
import { FlagCell } from './cells/FlagCell';
import { GaugeCell } from './cells/GaugeCell';
import { IndexCell } from './cells/IndexCell';
import { IntegerCell } from './cells/IntegerCell';
import { NationCell } from './cells/NationCell';
import { PersonCell } from './cells/PersonCell';
import { TextCell } from './cells/TextCell';

function Cell({ column, value }: { column: RegistryColumnDTO; value: RegistryCell }) {
  switch (column.type) {
    case 'index':
      return <IndexCell value={value} />;
    case 'integer':
      return <IntegerCell value={value} />;
    case 'gauge':
      return (
        <GaugeCell
          value={value}
          scaleMin={column.scale_min}
          scaleMax={column.scale_max}
        />
      );
    case 'date':
      return <DateCell value={value} />;
    case 'person':
      return <PersonCell value={value} />;
    case 'nation':
      return <NationCell value={value} />;
    case 'flag':
      return <FlagCell value={value} />;
    default:
      return <TextCell value={value} />;
  }
}

export function RegistryTable({
  table,
  rows,
  view,
  onSortClick,
  onFiltersChange,
}: {
  table: RegistryTableDTO;
  rows: RegistryRowDTO[];
  view: TableView;
  onSortClick: (columnId: string) => void;
  onFiltersChange: (columnId: string, filters: ColumnFilterValue[]) => void;
}) {
  return (
    <table
      data-testid="registry-table"
      style={{
        borderCollapse: 'collapse',
        width: 'max-content',
        minWidth: '100%',
      }}
    >
      <colgroup>
        {table.columns.map((col) => (
          <col key={col.id} style={{ width: col.width_px }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {table.columns.map((col) => {
            const sorted = view.sort?.columnId === col.id;
            return (
              <th
                key={col.id}
                scope="col"
                style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 5,
                  textAlign: 'left',
                  padding: '8px 12px',
                  whiteSpace: 'nowrap',
                  background: 'var(--vkui--color_background_content)',
                  borderBottom:
                    '1px solid var(--vkui--color_separator_primary)',
                }}
              >
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      aria-label={REGISTRY_TEXTS.sortAriaLabel(col.title)}
                      data-testid={`sort-btn-${col.id}`}
                      onClick={() => onSortClick(col.id)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        border: 0,
                        background: 'transparent',
                        padding: 0,
                        font: 'inherit',
                        fontWeight: 'inherit',
                        color: 'inherit',
                        cursor: 'pointer',
                      }}
                    >
                      {col.title}
                      {sorted &&
                        (view.sort!.direction === 'asc' ? (
                          <Icon16SortArrowUp />
                        ) : (
                          <Icon16SortArrowDown />
                        ))}
                    </button>
                  ) : (
                    col.title
                  )}
                  {col.filters.length > 0 && (
                    <ColumnFilter
                      column={col}
                      filters={view.filters[col.id] ?? []}
                      onChange={(next) => onFiltersChange(col.id, next)}
                    />
                  )}
                </span>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} data-row-key={row.key}>
            {table.columns.map((col) => (
              <td
                key={col.id}
                style={{
                  padding: '6px 12px',
                  borderBottom:
                    '1px solid var(--vkui--color_separator_primary)',
                  verticalAlign: 'middle',
                }}
              >
                <Cell column={col} value={row.cells[col.id] ?? null} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
