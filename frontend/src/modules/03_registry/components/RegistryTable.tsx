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

import { NATIONS_TABLE_ID } from '../hooks/useNationOptions';
import { isFilterActive, type TableView } from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import {
  isNationCell,
  type RegistryCell,
  type RegistryColumnDTO,
  type RegistryRowDTO,
  type RegistryTableDTO,
} from '../types';
import { Tooltip } from '../../../shared/ui';
import { ActionTextCell } from './cells/ActionTextCell';
import { DateCell } from './cells/DateCell';
import { DatetimeCell } from './cells/DatetimeCell';
import { FlagCell } from './cells/FlagCell';
import { GaugeCell } from './cells/GaugeCell';
import { IntegerCell } from './cells/IntegerCell';
import { NationCell, NationOpenLink, NationTip } from './cells/NationCell';
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

function Cell({
  table,
  column,
  row,
  value,
  onOpenNation,
}: {
  table: RegistryTableDTO;
  column: RegistryColumnDTO;
  row: RegistryRowDTO;
  value: RegistryCell;
  onOpenNation?: (nationId: string) => void;
}) {
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
      // The whole row's cells feed the player tip (unit 11).
      return <PersonCell value={value} cells={row.cells} />;
    case 'nation':
      return <NationCell value={value} onOpen={onOpenNation} />;
    case 'flag':
      return <FlagCell value={value} />;
    default:
      // Unit 6a/6b: the nations table's «name» may arrive as a
      // `nation` cell instead of a plain string — the cell itself
      // links and carries the tip, so the string special case below
      // does NOT apply to it. The same holds under any column type.
      if (isNationCell(value)) {
        return <NationCell value={value} onOpen={onOpenNation} />;
      }
      // The nations table's «name» is a plain text cell; its row key
      // IS the nation id (sources.py) — the name opens the subscreen
      // by that key (unit 14c) and carries the same «Подсказка»
      // (unit 11).
      if (
        column.type === 'text' &&
        table.id === NATIONS_TABLE_ID &&
        column.id === 'name' &&
        typeof value === 'string' &&
        value !== ''
      ) {
        return (
          <Tooltip
            content={() => <NationTip nationId={row.key} name={value} />}
          >
            <NationOpenLink onOpen={() => onOpenNation?.(row.key)}>
              {value}
            </NationOpenLink>
          </Tooltip>
        );
      }
      return <TextCell value={value} />;
  }
}

export function RegistryTable({
  table,
  rows,
  view,
  onSortClick,
  onOpenNation,
}: {
  table: RegistryTableDTO;
  rows: RegistryRowDTO[];
  view: TableView;
  onSortClick: (columnId: string) => void;
  /**
   * Opens the nation subscreen (unit 14c): `nation` cells with a
   * non-null id and the nations table's «name» cell (by row key).
   */
  onOpenNation?: (nationId: string) => void;
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
                <Cell
                  table={table}
                  column={col}
                  row={row}
                  value={row.cells[col.id] ?? null}
                  onOpenNation={onOpenNation}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
