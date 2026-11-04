/**
 * ApplicationsList — the «Анкеты» sub-view of the «Государства»
 * section (0.13.0 unit 9b; Spec applications §10; mockups
 * docs/06_DESIGN/0.13.0 screens 22/22b): the breadcrumb back to
 * «Государства», the «Государства | Анкеты [N]» switcher (local
 * state — never a hash), the «В рассмотрении | Все» filter
 * (status=PENDING|ALL) and the table — Анкета (flag stub, the name
 * as a ↗ link, «short · N провинций»), Игрок, Отправлена (with
 * «отправка №N» above one), Решение (the remaining time to
 * auto-accept while PENDING, the outcome pill otherwise), Рецензент
 * («вам» pill / «вы» / name / «нет рецензента» / «—») and «Открыть»
 * — the row's Mini-App `link` in a new tab; a null link keeps name
 * and button plain with the «не задан VK_APP_ID» hint. The note
 * plate under the table explains that the decision happens in the
 * Mini App. A 401 ends the session through the frame, like every
 * section.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type { AdminApplicationListItemDTO } from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { FlagMark } from '../../../shared/ui/FlagMark';
import { LoadingState } from '../../../shared/ui/LoadingState';
import {
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';
import {
  NationsAppsSwitch,
  PAGE_SIZE,
  PanelButton,
  Pill,
  SegButton,
  SegGroup,
} from './shared';

const LINK_HINT = 'не задан VK_APP_ID';
const NOTE_TEXT =
  'Анкета открывается в приложении ВКонтакте: решение принимается там. ' +
  'Если решения не будет до срока, анкета примется автоматически.';
/** The countdown's own refresh — the loaded rows age on screen. */
const REMAINING_TICK_MS = 60_000;

type StatusFilter = 'PENDING' | 'ALL';
type ListStatus = 'loading' | 'ready' | 'error';

/** Russian plural: pluralRu(5, 'провинция', 'провинции', 'провинций'). */
function pluralRu(n: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(n) % 100;
  const mod10 = mod100 % 10;
  if (mod100 > 10 && mod100 < 20) {
    return many;
  }
  if (mod10 > 1 && mod10 < 5) {
    return few;
  }
  if (mod10 === 1) {
    return one;
  }
  return many;
}

const MONTHS_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'мая',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
];
const submittedFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Europe/Moscow',
});

/** «31 окт, 14:20» — the tick timezone, like every admin answer. */
function formatSubmitted(iso: string): string {
  const parts = submittedFmt.formatToParts(new Date(iso));
  const part = (type: string) =>
    parts.find((p) => p.type === type)?.value ?? '';
  const month = MONTHS_SHORT[Number(part('month')) - 1] ?? part('month');
  return `${part('day')} ${month}, ${part('hour')}:${part('minute')}`;
}

/** «21 ч 40 мин» (minutes padded like the mockup); «срок вышел» once past. */
function remainingText(deadlineIso: string, nowMs: number): string {
  const left = new Date(deadlineIso).getTime() - nowMs;
  if (left <= 0) {
    return 'срок вышел';
  }
  const totalMin = Math.floor(left / 60_000);
  const days = Math.floor(totalMin / 1440);
  const hours = Math.floor((totalMin % 1440) / 60);
  const mins = totalMin % 60;
  if (days > 0) {
    return `${days} д ${hours} ч`;
  }
  if (hours > 0) {
    return `${hours} ч ${String(mins).padStart(2, '0')} мин`;
  }
  return `${mins} мин`;
}

/** The outcome pill of a decided row (mockup 22b). */
function decisionPill(row: AdminApplicationListItemDTO): {
  text: string;
  tone: 'plain' | 'ok' | 'bad';
} {
  if (row.status === 'ACCEPTED') {
    return row.auto_accepted === true
      ? { text: 'Принята автоматически', tone: 'ok' }
      : { text: 'Принята', tone: 'ok' };
  }
  if (row.draft_reason === 'cancelled') {
    return { text: 'Отозвана игроком', tone: 'plain' };
  }
  if (row.draft_reason === 'returned' || row.draft_reason === 'failed') {
    return { text: 'Возвращена', tone: 'bad' };
  }
  return { text: 'Черновик', tone: 'plain' };
}

/** The mockup's ↗ (arrow leaves the box), `link` colour. */
function ExternalLinkIcon({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('link')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'inline-block', verticalAlign: 'baseline' }}
    >
      <path d="M9 2.5h4.5V7M13.5 2.5L7 9M11 9.5v3.5H3V5h3.5" />
    </svg>
  );
}

function Dash() {
  return (
    <span style={{ ...TEXT_STYLES['caption'], color: tokenVar('ink-muted') }}>
      —
    </span>
  );
}

/** «Решение»: the auto-accept countdown while PENDING, else the pill. */
function DecisionCell({
  row,
  nowMs,
}: {
  row: AdminApplicationListItemDTO;
  nowMs: number;
}) {
  if (row.status === 'PENDING') {
    if (row.review_deadline_at === null) {
      return <Dash />;
    }
    const text = remainingText(row.review_deadline_at, nowMs);
    return (
      <>
        <span style={TEXT_STYLES['figure']}>{text}</span>
        {text !== 'срок вышел' && (
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            до автоприёма
          </div>
        )}
      </>
    );
  }
  const pill = decisionPill(row);
  return (
    <Pill tone={pill.tone} testId={`decision-${row.id}`}>
      {pill.text}
    </Pill>
  );
}

/** «Рецензент»: «вам» pill while PENDING, «вы» once decided. */
function ReviewerCell({ row }: { row: AdminApplicationListItemDTO }) {
  if (row.status === 'PENDING') {
    if (row.assigned_to_me) {
      return <Pill tone="signal">вам</Pill>;
    }
    return <>{row.reviewer_name ?? 'нет рецензента'}</>;
  }
  if (row.assigned_to_me) {
    return <>вы</>;
  }
  return row.reviewer_name !== null ? <>{row.reviewer_name}</> : <Dash />;
}

export function ApplicationsList({ onBack }: { onBack: () => void }) {
  const { token, reportUnauthorized, applicationsPending, refreshAttention } =
    useAdminSession();

  const [filter, setFilter] = useState<StatusFilter>('PENDING');
  const [items, setItems] = useState<AdminApplicationListItemDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const loadSeq = useRef(0);

  const load = useCallback(
    async (statusFilter: StatusFilter, offset: number, append: boolean) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminApplications(token, {
          status: statusFilter,
          limit: PAGE_SIZE,
          offset,
        });
        if (seq !== loadSeq.current) {
          return;
        }
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
        setTotal(page.total);
        setStatus('ready');
        // The badge recounts after the list loads (unit 9b contract).
        refreshAttention();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq !== loadSeq.current) {
          return;
        }
        if (append) {
          setLoadingMore(false);
        }
        setStatus('error');
      } finally {
        if (seq === loadSeq.current) {
          setLoadingMore(false);
        }
      }
    },
    [token, reportUnauthorized, refreshAttention],
  );

  useEffect(() => {
    setStatus('loading');
    void load(filter, 0, false);
  }, [filter, load]);

  // The «до автоприёма» countdown ages on its own minute tick.
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), REMAINING_TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  const loadMore = () => {
    setLoadingMore(true);
    void load(filter, items.length, true);
  };

  const cellStyle = (last: boolean) => ({
    height: 52,
    padding: '4px 12px',
    borderBottom: last ? 'none' : `1px solid ${tokenVar('line')}`,
    verticalAlign: 'middle' as const,
    ...TEXT_STYLES['body'],
  });

  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          ...TEXT_STYLES['caption'],
          color: tokenVar('ink-muted'),
        }}
      >
        <a
          href="#"
          onClick={(event) => {
            event.preventDefault();
            onBack();
          }}
          style={{ color: tokenVar('link'), textDecoration: 'none' }}
        >
          Государства
        </a>
        <span>/</span>
        <span style={{ color: tokenVar('ink') }}>Анкеты</span>
      </div>

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
        <PanelIcon name="flag" accent size={20} />
        Государства
      </h1>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
          flexWrap: 'wrap',
        }}
      >
        <NationsAppsSwitch
          active="applications"
          pendingCount={applicationsPending}
          onSelect={() => onBack()}
        />
        <span style={{ flexGrow: 1, minWidth: 0 }} />
        <SegGroup ariaLabel="Фильтр анкет по статусу">
          <SegButton
            testId="app-filter-pending"
            on={filter === 'PENDING'}
            onClick={() => setFilter('PENDING')}
          >
            В рассмотрении
          </SegButton>
          <SegButton
            testId="app-filter-all"
            on={filter === 'ALL'}
            onClick={() => setFilter('ALL')}
          >
            Все
          </SegButton>
        </SegGroup>
      </div>

      <section
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: '8px 4px',
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
              void load(filter, 0, false);
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState
            text={
              filter === 'PENDING'
                ? 'Анкет в рассмотрении нет.'
                : 'Анкет пока нет.'
            }
          />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="applications-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['Анкета', 'Игрок', 'Отправлена', 'Решение', 'Рецензент', ''].map(
                  (head, index) => (
                    <th
                      key={index}
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
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((row, index) => {
                const last = index === items.length - 1;
                return (
                  <tr key={row.id} data-testid={`application-row-${row.id}`}>
                    <td style={cellStyle(last)}>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 10,
                        }}
                      >
                        <FlagMark url={null} width={36} height={24} radius={3} />
                        <span>
                          {row.link !== null ? (
                            <a
                              href={row.link}
                              target="_blank"
                              rel="noopener noreferrer"
                              data-testid={`application-link-${row.id}`}
                              style={{
                                color: tokenVar('link'),
                                textDecoration: 'none',
                              }}
                            >
                              {row.name} <ExternalLinkIcon />
                            </a>
                          ) : (
                            <span title={LINK_HINT}>{row.name}</span>
                          )}
                          <div
                            style={{
                              ...TEXT_STYLES['caption'],
                              color: tokenVar('ink-muted'),
                            }}
                          >
                            {row.short_name} · {row.provinces_count}{' '}
                            {pluralRu(
                              row.provinces_count,
                              'провинция',
                              'провинции',
                              'провинций',
                            )}
                          </div>
                        </span>
                      </span>
                    </td>
                    <td style={cellStyle(last)}>
                      {row.owner_name !== null ? row.owner_name : <Dash />}
                    </td>
                    <td style={cellStyle(last)}>
                      {row.submitted_at !== null ? (
                        <>
                          {formatSubmitted(row.submitted_at)}
                          {row.submissions > 1 && (
                            <div
                              style={{
                                ...TEXT_STYLES['caption'],
                                color: tokenVar('ink-muted'),
                              }}
                            >
                              отправка №{row.submissions}
                            </div>
                          )}
                        </>
                      ) : (
                        <Dash />
                      )}
                    </td>
                    <td style={cellStyle(last)}>
                      <DecisionCell row={row} nowMs={nowMs} />
                    </td>
                    <td style={cellStyle(last)}>
                      <ReviewerCell row={row} />
                    </td>
                    <td
                      style={{
                        ...cellStyle(last),
                        textAlign: 'right',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {row.link !== null ? (
                        <a
                          href={row.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid={`application-open-${row.id}`}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: 32,
                            padding: '0 12px',
                            borderRadius: RADII['radius-md'],
                            background: tokenVar('surface-inset'),
                            color: tokenVar('ink'),
                            textDecoration: 'none',
                            whiteSpace: 'nowrap',
                            ...TEXT_STYLES['body'],
                          }}
                        >
                          Открыть
                        </a>
                      ) : (
                        <span
                          data-testid={`application-open-${row.id}`}
                          title={LINK_HINT}
                          aria-disabled="true"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: 32,
                            padding: '0 12px',
                            borderRadius: RADII['radius-md'],
                            background: tokenVar('surface-inset'),
                            color: tokenVar('ink'),
                            whiteSpace: 'nowrap',
                            opacity: 0.45,
                            cursor: 'default',
                            ...TEXT_STYLES['body'],
                          }}
                        >
                          Открыть
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <div
        style={{
          display: 'flex',
          gap: 12,
          borderRadius: RADII['radius-lg'],
          padding: '12px 16px',
          background: tokenVar('surface'),
          border: `1px solid ${tokenVar('line')}`,
        }}
      >
        <span style={{ flexShrink: 0, marginTop: 2 }}>
          <ExternalLinkIcon size={16} />
        </span>
        <span style={{ ...TEXT_STYLES['caption'], color: tokenVar('ink') }}>
          {NOTE_TEXT}
        </span>
      </div>

      {status === 'ready' && items.length < total && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <PanelButton
            testId="applications-load-more"
            disabled={loadingMore}
            onClick={loadMore}
          >
            Показать ещё
          </PanelButton>
        </div>
      )}
    </>
  );
}
