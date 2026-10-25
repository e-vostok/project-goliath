/**
 * LogSection — «Журнал» (0.11.0 unit 7), approved mockup
 * docs/06_DESIGN/0.11.0 screen 08.
 *
 * The permanent admin journal: a filter row (Администратор, Действие,
 * С даты, По дату — the two dropdowns fed by
 * GET /admin/audit-log/filters — and «Сбросить»), then the table card
 * (Время (МСК), Кто, Действие, Над чем, Кратко), the caption
 * «Показано N · записи не удаляются и не правятся» and «Показать
 * ещё» driven by the answer's next_before_id cursor. «Над чем» is
 * built from target type and id in plain words, «—» when the action
 * has no target.
 *
 * Loading, empty and error states use the shared components; a 401
 * from any call ends the session through the frame's
 * reportUnauthorized — the same rule every panel section follows.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type {
  AdminAuditFiltersDTO,
  AdminAuditItemDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { useTheme } from '../../../shared/ui/theme';
import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';

const PAGE_SIZE = 50;

/** The «Над чем» word for each target_type the journal knows. */
const TARGET_WORDS: Record<string, string> = {
  player: 'Игрок',
  nation: 'Государство',
  province: 'Провинция',
  order: 'Приказ',
  turn: 'Ход',
  tick: 'Ход',
};

interface LogFilters {
  actor_vk_user_id: string;
  action: string;
  date_from: string;
  date_to: string;
}

const EMPTY_FILTERS: LogFilters = {
  actor_vk_user_id: '',
  action: '',
  date_from: '',
  date_to: '',
};

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup 08: .card, .btn, .in).        */
/* ---------------------------------------------------------------- */

function PanelButton({
  kind = 'plain',
  small = false,
  disabled = false,
  onClick,
  children,
  testId,
}: {
  kind?: 'plain' | 'primary' | 'danger' | 'danger-outline';
  /** The 32 px variant (.btn.sm) for table cells and title rows. */
  small?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const { resolved } = useTheme();
  // Text on the coloured buttons: near-black in the dark theme,
  // white in the light one (mockup .btn.p / .btn.d).
  const onAction = tokenVar(resolved === 'dark' ? 'ground' : 'surface');
  const skin =
    kind === 'primary'
      ? { background: tokenVar('action'), color: onAction, border: 'none' }
      : kind === 'danger'
        ? { background: tokenVar('danger'), color: onAction, border: 'none' }
        : kind === 'danger-outline'
          ? {
              background: 'transparent',
              color: tokenVar('danger'),
              border: `1px solid ${tokenVar('danger')}`,
            }
          : {
              background: tokenVar('surface-inset'),
              color: tokenVar('ink'),
              border: 'none',
            };
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        height: small ? SIZES['button-h-small'] : SIZES['button-h'],
        boxSizing: 'border-box',
        padding: small ? '0 12px' : '0 16px',
        borderRadius: RADII['radius-md'],
        whiteSpace: 'nowrap',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        ...TEXT_STYLES['body'],
        ...skin,
      }}
    >
      {children}
    </button>
  );
}

/** One labelled filter control (label above, control below). */
function FilterField({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label
        htmlFor={id}
        style={{
          ...TEXT_STYLES['caption'],
          color: tokenVar('ink-muted'),
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

const controlStyle: React.CSSProperties = {
  height: SIZES['button-h'],
  boxSizing: 'border-box',
  padding: '0 12px',
  borderRadius: RADII['radius-md'],
  background: tokenVar('surface-inset'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
};

/* ---------------------------------------------------------------- */
/* Display helpers.                                                  */
/* ---------------------------------------------------------------- */

/** "2026-10-24 15:44:12" → "24.10 15:44" — the mockup's time column. */
function logTime(value: string): string {
  const [datePart, timePart = ''] = value.split(' ');
  const [, month, day] = datePart.split('-');
  return `${day}.${month} ${timePart.slice(0, 5)}`;
}

/** «Над чем» — target type and id in plain words, «—» when empty. */
function targetText(item: AdminAuditItemDTO): string {
  if (item.target_type === null || item.target_type === '') {
    return '—';
  }
  const word = TARGET_WORDS[item.target_type] ?? item.target_type;
  return item.target_id !== null ? `${word} ${item.target_id}` : word;
}

/* ---------------------------------------------------------------- */
/* The section.                                                      */
/* ---------------------------------------------------------------- */

type ListStatus = 'loading' | 'ready' | 'error';

export function LogSection() {
  const { token, reportUnauthorized } = useAdminSession();

  const [filtersMeta, setFiltersMeta] = useState<AdminAuditFiltersDTO | null>(
    null,
  );
  const [filters, setFilters] = useState<LogFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<LogFilters>(EMPTY_FILTERS);

  const [items, setItems] = useState<AdminAuditItemDTO[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);

  // Guards: only the latest load writes, so a stale answer can never
  // land after a newer filter set.
  const loadSeq = useRef(0);

  const load = useCallback(
    async (appliedFilters: LogFilters, beforeId: number | null) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminAuditLog(token, {
          actor_vk_user_id:
            appliedFilters.actor_vk_user_id === ''
              ? undefined
              : Number(appliedFilters.actor_vk_user_id),
          action: appliedFilters.action || undefined,
          date_from: appliedFilters.date_from || undefined,
          date_to: appliedFilters.date_to || undefined,
          limit: PAGE_SIZE,
          before_id: beforeId ?? undefined,
        });
        if (seq !== loadSeq.current) {
          return;
        }
        setItems((prev) =>
          beforeId === null ? page.items : [...prev, ...page.items],
        );
        setNextBeforeId(page.next_before_id);
        setStatus('ready');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq !== loadSeq.current) {
          return;
        }
        setStatus('error');
      } finally {
        if (seq === loadSeq.current) {
          setLoadingMore(false);
        }
      }
    },
    [token, reportUnauthorized],
  );

  // The dropdown values arrive once; a failure only empties the lists —
  // the journal itself still reads fine.
  useEffect(() => {
    api
      .adminAuditLogFilters(token)
      .then(setFiltersMeta)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        setFiltersMeta({ actors: [], actions: [] });
      });
  }, [token, reportUnauthorized]);

  useEffect(() => {
    setStatus('loading');
    void load(applied, null);
  }, [applied, load]);

  const applyFilters = (next: LogFilters) => {
    setFilters(next);
    setApplied(next);
  };

  const loadMore = () => {
    if (nextBeforeId === null) {
      return;
    }
    setLoadingMore(true);
    void load(applied, nextBeforeId);
  };

  return (
    <>
      <h1
        style={{
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          ...TEXT_STYLES['title-uppercase'],
          fontSize: 24,
          lineHeight: '28px',
        }}
      >
        <PanelIcon name="list" accent size={20} />
        Журнал действий
      </h1>

      {/* The screen-08 filter row: two dropdowns, two dates, «Сбросить» —
          wraps to a second line rather than overflowing a narrow window. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          gap: SPACING['space-3'],
        }}
      >
        <FilterField id="log-filter-actor" label="Администратор">
          <select
            id="log-filter-actor"
            data-testid="log-filter-actor"
            value={filters.actor_vk_user_id}
            onChange={(event) =>
              applyFilters({
                ...filters,
                actor_vk_user_id: event.currentTarget.value,
              })
            }
            style={{ ...controlStyle, width: 200 }}
          >
            <option value="">Все</option>
            {(filtersMeta?.actors ?? []).map((actor) => (
              <option key={actor.vk_user_id} value={actor.vk_user_id}>
                {actor.display_name ?? `VK ${actor.vk_user_id}`}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField id="log-filter-action" label="Действие">
          <select
            id="log-filter-action"
            data-testid="log-filter-action"
            value={filters.action}
            onChange={(event) =>
              applyFilters({ ...filters, action: event.currentTarget.value })
            }
            style={{ ...controlStyle, width: 200 }}
          >
            <option value="">Все</option>
            {(filtersMeta?.actions ?? []).map((entry) => (
              <option key={entry.action} value={entry.action}>
                {entry.action_label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField id="log-filter-from" label="С даты">
          <input
            id="log-filter-from"
            data-testid="log-filter-from"
            type="date"
            value={filters.date_from}
            onChange={(event) =>
              applyFilters({ ...filters, date_from: event.currentTarget.value })
            }
            style={{ ...controlStyle, width: 150 }}
          />
        </FilterField>
        <FilterField id="log-filter-to" label="По дату">
          <input
            id="log-filter-to"
            data-testid="log-filter-to"
            type="date"
            value={filters.date_to}
            onChange={(event) =>
              applyFilters({ ...filters, date_to: event.currentTarget.value })
            }
            style={{ ...controlStyle, width: 150 }}
          />
        </FilterField>
        <span style={{ flexGrow: 1, minWidth: 0 }} />
        <PanelButton
          disabled={
            filters.actor_vk_user_id === '' &&
            filters.action === '' &&
            filters.date_from === '' &&
            filters.date_to === ''
          }
          testId="log-reset"
          onClick={() => applyFilters(EMPTY_FILTERS)}
        >
          Сбросить
        </PanelButton>
      </div>

      <section
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: SPACING['space-4'],
          display: 'flex',
          flexDirection: 'column',
          gap: SPACING['space-3'],
        }}
      >
        {status === 'loading' && <LoadingState height={150} />}
        {status === 'error' && (
          <ErrorState
            onRetry={() => {
              setStatus('loading');
              void load(applied, null);
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState text="Записей по этим фильтрам нет." />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="log-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {[
                  'Время (МСК)',
                  'Кто',
                  'Действие',
                  'Над чем',
                  'Кратко',
                ].map((head) => (
                  <th
                    key={head}
                    style={{
                      textAlign: 'left',
                      padding: '8px 12px',
                      borderBottom: `1px solid ${tokenVar('line')}`,
                      ...TEXT_STYLES['label'],
                      color: tokenVar('ink-muted'),
                    }}
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((row, index) => (
                <tr key={row.id} data-testid="log-row">
                  <td
                    style={{
                      height: 44,
                      padding: '4px 12px',
                      borderBottom:
                        index === items.length - 1
                          ? 'none'
                          : `1px solid ${tokenVar('line')}`,
                      verticalAlign: 'middle',
                      ...TEXT_STYLES['body'],
                      fontFamily: 'monospace',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {logTime(row.created_at)}
                  </td>
                  {[
                    row.actor_name ?? `VK ${row.actor_vk_user_id}`,
                    row.action_label,
                    targetText(row),
                    row.summary,
                  ].map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      style={{
                        height: 44,
                        padding: '4px 12px',
                        borderBottom:
                          index === items.length - 1
                            ? 'none'
                            : `1px solid ${tokenVar('line')}`,
                        verticalAlign: 'middle',
                        ...TEXT_STYLES['body'],
                      }}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {status === 'ready' && items.length > 0 && (
          <span
            data-testid="log-shown"
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            Показано {items.length} · записи не удаляются и не правятся
          </span>
        )}
        {status === 'ready' && nextBeforeId !== null && (
          <div>
            <PanelButton
              disabled={loadingMore}
              testId="log-show-more"
              onClick={loadMore}
            >
              {loadingMore ? 'Загрузка…' : 'Показать ещё'}
            </PanelButton>
          </div>
        )}
      </section>
    </>
  );
}
