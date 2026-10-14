/**
 * RegistryTable — the config-driven table of the «Реестр» (Spec 5.5).
 * Header cells offer tri-state sort (sortable columns) and the filter
 * dropdown (filterable columns). The table is `table-layout: fixed` at
 * `width: 100%`; a <colgroup> gives each column its `width_px` share of
 * the row as a percentage, so the table stretches or shrinks to the
 * block width and never scrolls sideways (910 px window rule).
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

/** Column titles wrap onto a second line instead of widening the column
 * (910 px window rule, Spec 5.5). */
const HEADER_TITLE_STYLE: React.CSSProperties = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  whiteSpace: 'normal',
  overflowWrap: 'break-word',
};

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
  const totalWidth = table.columns.reduce((sum, col) => sum + col.width_px, 0);
  return (
    <table
      data-testid="registry-table"
      style={{
        borderCollapse: 'collapse',
        tableLayout: 'fixed',
        width: '100%',
      }}
    >
      <colgroup>
        {table.columns.map((col) => (
          <col
            key={col.id}
            style={{ width: `${(col.width_px / totalWidth) * 100}%` }}
          />
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
                  verticalAlign: 'bottom',
                  overflow: 'hidden',
                  background: 'var(--vkui--color_background_content)',
                  borderBottom:
                    '1px solid var(--vkui--color_separator_primary)',
                }}
              >
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    minWidth: 0,
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
                        minWidth: 0,
                        border: 0,
                        background: 'transparent',
                        padding: 0,
                        font: 'inherit',
                        fontWeight: 'inherit',
                        color: 'inherit',
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      <span style={HEADER_TITLE_STYLE}>{col.title}</span>
                      {sorted &&
                        (view.sort!.direction === 'asc' ? (
                          <Icon16SortArrowUp />
                        ) : (
                          <Icon16SortArrowDown />
                        ))}
                    </button>
                  ) : (
                    <span style={HEADER_TITLE_STYLE}>{col.title}</span>
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
                  overflow: 'hidden',
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
