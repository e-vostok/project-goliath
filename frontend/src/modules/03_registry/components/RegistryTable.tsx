/**
 * RegistryTable — the config-driven table of the «Реестр» (Spec 5.5).
 * Header cells hold only the column title and the 14 px sort arrow
 * (sortable columns); a column with an active filter is marked by a
 * small accent dot — filters live in the panel above the table, never
 * in the header. The table is `table-layout: fixed` at `width: 100%`;
 * a <colgroup> gives each column its `width_px` share of the row as a
 * percentage, so the table stretches or shrinks to the block width and
 * never scrolls sideways (910 px window rule).
 * Rows arrive already filtered+sorted by lib/tableView.applyView.
 */

import {
  Icon16SortArrowDown,
  Icon16SortArrowUp,
  Icon16SortOutline,
} from '@vkontakte/icons';

import { isFilterActive, type TableView } from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import type {
  RegistryCell,
  RegistryColumnDTO,
  RegistryRowDTO,
  RegistryTableDTO,
} from '../types';
import { ActionTextCell } from './cells/ActionTextCell';
import { DateCell } from './cells/DateCell';
import { DatetimeCell } from './cells/DatetimeCell';
import { FlagCell } from './cells/FlagCell';
import { GaugeCell } from './cells/GaugeCell';
import { IntegerCell } from './cells/IntegerCell';
import { NationCell } from './cells/NationCell';
import { PersonCell } from './cells/PersonCell';
import { TextCell } from './cells/TextCell';
import { HeaderIcon } from './HeaderIcon';

/** A column title never breaks inside a word and wraps only at spaces,
 * at most two lines (Spec 5.5). */
const HEADER_TITLE_STYLE: React.CSSProperties = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  whiteSpace: 'normal',
  wordBreak: 'keep-all',
  overflowWrap: 'normal',
  hyphens: 'none',
  minWidth: 0,
};

const NUMERIC_TYPES = new Set(['index', 'integer', 'gauge']);

const SORT_ICON_PROPS = { width: 14, height: 14 } as const;

function SortIcon({
  column,
  view,
}: {
  column: RegistryColumnDTO;
  view: TableView;
}) {
  const sorted = view.sort?.columnId === column.id;
  if (!sorted) {
    return (
      <Icon16SortOutline
        {...SORT_ICON_PROPS}
        fill="var(--vkui--color_icon_secondary)"
      />
    );
  }
  return view.sort!.direction === 'asc' ? (
    <Icon16SortArrowUp
      {...SORT_ICON_PROPS}
      fill="var(--vkui--color_icon_accent)"
    />
  ) : (
    <Icon16SortArrowDown
      {...SORT_ICON_PROPS}
      fill="var(--vkui--color_icon_accent)"
    />
  );
}

function Cell({ column, value }: { column: RegistryColumnDTO; value: RegistryCell }) {
  switch (column.type) {
    case 'index':
      return <IntegerCell value={value} />;
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
    case 'datetime':
      return <DatetimeCell value={value} />;
    case 'action_text':
      return <ActionTextCell value={value} />;
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
}: {
  table: RegistryTableDTO;
  rows: RegistryRowDTO[];
  view: TableView;
  onSortClick: (columnId: string) => void;
}) {
  const totalWidth = table.columns.reduce((sum, col) => sum + col.width_px, 0);
  return (
    <table
      data-testid="registry-table"
      style={{
        borderCollapse: 'collapse',
        tableLayout: 'fixed',
        width: '100%',
        fontSize: 13,
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
            const hasActiveFilter = (view.filters[col.id] ?? []).some(
              isFilterActive,
            );
            return (
              <th
                key={col.id}
                scope="col"
                style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 5,
                  height: 40,
                  fontSize: 12,
                  fontWeight: 600,
                  textAlign: 'left',
                  padding: '0 8px',
                  verticalAlign: 'middle',
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
                      title={col.header_icon ? col.title : undefined}
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
                      {col.header_icon ? (
                        <HeaderIcon
                          name={col.header_icon}
                          title={col.title}
                        />
                      ) : (
                        <span style={HEADER_TITLE_STYLE}>{col.title}</span>
                      )}
                      <SortIcon column={col} view={view} />
                    </button>
                  ) : col.header_icon ? (
                    <HeaderIcon name={col.header_icon} title={col.title} />
                  ) : (
                    <span style={HEADER_TITLE_STYLE}>{col.title}</span>
                  )}
                  {hasActiveFilter && (
                    <span
                      data-testid={`filter-dot-${col.id}`}
                      aria-hidden
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        flexShrink: 0,
                        background: 'var(--vkui--color_icon_accent)',
                      }}
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
                  height: 34,
                  padding: '0 8px',
                  borderBottom:
                    '1px solid var(--vkui--color_separator_primary)',
                  verticalAlign: 'middle',
                  overflow: 'hidden',
                  fontVariantNumeric: NUMERIC_TYPES.has(col.type)
                    ? 'tabular-nums'
                    : undefined,
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
