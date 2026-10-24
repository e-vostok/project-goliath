/**
 * TurnSection — «Ход и мир» (0.11.0 unit 6a), approved mockup
 * docs/06_DESIGN/0.11.0 screen 02.
 *
 * Four cards: «Состояние мира» — the tiles GET /admin/overview merges
 * from every module's overview hook (values arrive formatted — no
 * JSON); «Запуск хода» — the manual tick behind an S-size
 * confirmation popup, the result goes to the shared Notice, a failed
 * tick shows the server's message; «Журнал ходов» — the last five
 * tick_log rows; «Сброс мира» — stays disabled while /admin/me says
 * reset_allowed=false, and even then asks to retype «СБРОС».
 *
 * A 401 from any call ends the session through the frame's
 * reportUnauthorized — the same rule every panel section follows.
 */

import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminOverviewTileDTO,
  AdminTickLogEntryDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { TextField } from '../../../shared/ui/fields';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { useNotice } from '../../../shared/ui/Notice';
import { Popup } from '../../../shared/ui/Popup';
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

const TICK_LOG_LIMIT = 5;
const RESET_WORD = 'СБРОС';
const UPDATED_LABEL_TICK_MS = 30_000;

const RESET_CONSEQUENCE =
  'Удаляет все государства, запланированные действия и журнал ходов, ' +
  'освобождает провинции, возвращает мир к январю 2040. Игроки ' +
  'остаются. Отменить нельзя.';
const TICK_CONSEQUENCE =
  'Мир немедленно сделает один ход: все расчёты суточного тика ' +
  'выполнятся сейчас, а не по расписанию в 00:00.';

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup 02: .card, .tile, .btn).      */
/* ---------------------------------------------------------------- */

function PanelCard({
  title,
  danger = false,
  aside,
  children,
}: {
  title: string;
  /** The destructive card heading («Сброс мира») is red. */
  danger?: boolean;
  /** Right end of the title row — captions and small buttons. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
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
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2
          style={{
            margin: 0,
            ...TEXT_STYLES['heading'],
            color: tokenVar(danger ? 'danger' : 'ink'),
          }}
        >
          {title}
        </h2>
        <span style={{ flexGrow: 1, minWidth: 0 }} />
        {aside}
      </div>
      {children}
    </section>
  );
}

type PanelButtonKind = 'plain' | 'primary' | 'danger' | 'danger-outline';

function PanelButton({
  kind = 'plain',
  small = false,
  disabled = false,
  onClick,
  children,
  testId,
}: {
  kind?: PanelButtonKind;
  /** The 32 px variant (.btn.sm) for card title rows. */
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

/* ---------------------------------------------------------------- */
/* Display helpers.                                                  */
/* ---------------------------------------------------------------- */

/** "2026-10-25 00:00:03" → "25.10 00:00:03"; NULL → "—". */
function shortGameTime(value: string | null): string {
  if (value === null) {
    return '—';
  }
  const [datePart, timePart = ''] = value.split(' ');
  const [, month, day] = datePart.split('-');
  return `${day}.${month} ${timePart}`;
}

/** The «Последний запуск: …» caption of the tick card. */
function lastRunCaption(row: AdminTickLogEntryDTO | undefined): string {
  if (row === undefined) {
    return 'Запусков ещё не было.';
  }
  const when =
    row.finished_at !== null
      ? `завершён ${shortGameTime(row.finished_at).replace(' ', ' в ')}`
      : 'ещё выполняется';
  const verdict =
    row.status === 'COMPLETED'
      ? 'успешно'
      : `ошибка${row.error_message ? ` — ${row.error_message}` : ''}`;
  return `Последний запуск: ход ${row.turn_number}, ${when} — ${verdict}.`;
}

function updatedCaption(updatedAt: number | null, now: number): string {
  if (updatedAt === null) {
    return '';
  }
  const minutes = Math.floor((now - updatedAt) / 60_000);
  return minutes < 1
    ? 'Обновлено только что'
    : `Обновлено ${minutes} мин назад`;
}

function TickResultCell({ row }: { row: AdminTickLogEntryDTO }) {
  if (row.status === 'COMPLETED') {
    return <span style={{ color: tokenVar('positive') }}>✓ Успешно</span>;
  }
  if (row.status === 'RUNNING') {
    return <span style={{ color: tokenVar('ink-muted') }}>Идёт…</span>;
  }
  return (
    <span style={{ color: tokenVar('danger') }}>
      ✕ Ошибка
      {row.error_message && (
        <span style={{ color: tokenVar('ink-muted') }}>
          {' '}
          — {row.error_message}
        </span>
      )}
    </span>
  );
}

/* ---------------------------------------------------------------- */
/* The section.                                                      */
/* ---------------------------------------------------------------- */

interface SectionData {
  tiles: AdminOverviewTileDTO[];
  log: AdminTickLogEntryDTO[];
  resetAllowed: boolean;
}

export function TurnSection() {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();

  const [data, setData] = useState<SectionData | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [refreshing, setRefreshing] = useState(false);

  const [popup, setPopup] = useState<'tick' | 'reset' | null>(null);
  const [busy, setBusy] = useState(false);
  const [tickError, setTickError] = useState<string | null>(null);
  const [resetWord, setResetWord] = useState('');
  const [resetError, setResetError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [tiles, log, me] = await Promise.all([
        api.adminOverview(token),
        api.adminTickLog(token, TICK_LOG_LIMIT),
        api.adminMe(token),
      ]);
      setData({ tiles, log, resetAllowed: me.reset_allowed });
      setLoadFailed(false);
      setUpdatedAt(Date.now());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      setLoadFailed(true);
    }
  }, [token, reportUnauthorized]);

  useEffect(() => {
    void load();
  }, [load]);

  // The «Обновлено …» caption ages on its own 30 s tick.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), UPDATED_LABEL_TICK_MS);
    return () => clearInterval(id);
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const runTick = async () => {
    setBusy(true);
    setTickError(null);
    try {
      const result = await api.adminRunTick(token);
      setPopup(null);
      if (result.ok) {
        notify(`Ход ${result.current_turn} выполнен успешно.`);
      } else {
        setTickError(
          `Ход завершился с ошибкой: ` +
            (result.tick_log?.error_message ?? 'сбой без описания.'),
        );
      }
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      setPopup(null);
      setTickError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const runReset = async () => {
    setBusy(true);
    setResetError(null);
    try {
      await api.adminResetState(token);
      setPopup(null);
      setResetWord('');
      notify('Мир сброшен — ход 0, январь 2040.');
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setResetError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const closeResetPopup = () => {
    setPopup(null);
    setResetWord('');
    setResetError(null);
  };

  const lastLogRow = data?.log[0];

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
        <PanelIcon name="clock" accent size={20} />
        Ход и мир
      </h1>

      <PanelCard
        title="Состояние мира"
        aside={
          <>
            <span
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('ink-muted'),
                whiteSpace: 'nowrap',
              }}
            >
              {updatedCaption(updatedAt, now)}
            </span>
            <PanelButton small disabled={refreshing} onClick={() => void refresh()}>
              Обновить
            </PanelButton>
          </>
        }
      >
        {data === null && !loadFailed && <LoadingState height={150} />}
        {loadFailed && data === null && (
          <ErrorState onRetry={() => void refresh()} />
        )}
        {data !== null && (
          <div
            data-testid="overview-tiles"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
              gap: '12px 16px',
            }}
          >
            {data.tiles.map((tile) => (
              <div
                key={tile.key}
                data-testid={`tile-${tile.key}`}
                style={{
                  background: tokenVar('surface-inset'),
                  borderRadius: RADII['radius-md'],
                  padding: SPACING['space-3'],
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                }}
              >
                <span
                  style={{
                    ...TEXT_STYLES['label'],
                    color: tokenVar('ink-muted'),
                  }}
                >
                  {tile.label}
                </span>
                <span
                  style={{
                    ...TEXT_STYLES['figure-lg'],
                    color: tokenVar('ink'),
                  }}
                >
                  {tile.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </PanelCard>

      <PanelCard title="Запуск хода">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ ...TEXT_STYLES['body'], flexGrow: 1 }}>
            Ход запускается так же, как по расписанию в 00:00. Время
            следующего хода не меняется.
          </span>
          <PanelButton
            kind="primary"
            disabled={busy}
            testId="run-tick"
            onClick={() => setPopup('tick')}
          >
            <PanelIcon name="clock" size={16} />
            Запустить ход
          </PanelButton>
        </div>
        <span
          data-testid="last-run"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {lastRunCaption(lastLogRow)}
        </span>
        {tickError !== null && (
          <span
            data-testid="tick-error"
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('danger'),
            }}
          >
            {tickError}
          </span>
        )}
      </PanelCard>

      <PanelCard
        title="Журнал ходов"
        aside={
          <span
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            Последние 5
          </span>
        }
      >
        {data !== null && data.log.length === 0 && (
          <EmptyState text="Запусков ещё не было." />
        )}
        {data !== null && data.log.length > 0 && (
          <table
            style={{ width: '100%', borderCollapse: 'collapse' }}
            data-testid="tick-log-table"
          >
            <thead>
              <tr>
                {['№', 'Ход', 'Начат', 'Закончен', 'Результат'].map(
                  (head) => (
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
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.log.map((row, index) => (
                <tr key={row.id}>
                  {[
                    String(row.id),
                    row.turn_label,
                    shortGameTime(row.started_at),
                    shortGameTime(row.finished_at),
                  ].map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      style={{
                        height: 44,
                        padding: '4px 12px',
                        borderBottom:
                          index === data.log.length - 1
                            ? 'none'
                            : `1px solid ${tokenVar('line')}`,
                        verticalAlign: 'middle',
                        ...TEXT_STYLES['body'],
                      }}
                    >
                      {cell}
                    </td>
                  ))}
                  <td
                    style={{
                      height: 44,
                      padding: '4px 12px',
                      borderBottom:
                        index === data.log.length - 1
                          ? 'none'
                          : `1px solid ${tokenVar('line')}`,
                      verticalAlign: 'middle',
                      ...TEXT_STYLES['body'],
                    }}
                  >
                    <TickResultCell row={row} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </PanelCard>

      <PanelCard title="Сброс мира" danger>
        <span style={TEXT_STYLES['body']}>{RESET_CONSEQUENCE}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <PanelButton
            kind="danger-outline"
            disabled={data === null || !data.resetAllowed}
            testId="open-reset"
            onClick={() => setPopup('reset')}
          >
            Сбросить мир…
          </PanelButton>
          {data !== null && !data.resetAllowed && (
            <span
              data-testid="reset-hint"
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('ink-muted'),
              }}
            >
              Сейчас выключено на этом сервере — кнопка недоступна.
            </span>
          )}
        </div>
      </PanelCard>

      {popup === 'tick' && (
        <Popup
          size="S"
          title="Запустить ход"
          testId="tick-popup"
          onClose={() => setPopup(null)}
          footer={
            <>
              <PanelButton disabled={busy} onClick={() => setPopup(null)}>
                Отмена
              </PanelButton>
              <PanelButton
                kind="primary"
                disabled={busy}
                testId="confirm-tick"
                onClick={() => void runTick()}
              >
                Запустить
              </PanelButton>
            </>
          }
        >
          <span style={TEXT_STYLES['body']}>{TICK_CONSEQUENCE}</span>
        </Popup>
      )}

      {popup === 'reset' && (
        <Popup
          size="S"
          title="Сброс мира"
          testId="reset-popup"
          dirty={resetWord !== ''}
          onClose={closeResetPopup}
          footer={
            <>
              <PanelButton disabled={busy} onClick={closeResetPopup}>
                Отмена
              </PanelButton>
              <PanelButton
                kind="danger"
                disabled={busy || resetWord !== RESET_WORD}
                testId="confirm-reset"
                onClick={() => void runReset()}
              >
                Сбросить мир
              </PanelButton>
            </>
          }
        >
          <span style={TEXT_STYLES['body']}>{RESET_CONSEQUENCE}</span>
          <TextField
            id="reset-confirm-word"
            label="Наберите «СБРОС» для подтверждения"
            value={resetWord}
            onChange={setResetWord}
          />
          {resetError !== null && (
            <span
              data-testid="reset-error"
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('danger'),
              }}
            >
              {resetError}
            </span>
          )}
        </Popup>
      )}
    </>
  );
}
