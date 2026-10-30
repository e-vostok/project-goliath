/**
 * OrdersSection — «Приказы» (0.11.0 unit 10b), approved mockup
 * docs/06_DESIGN/0.11.0 screen 05.
 *
 * The card «Приказы» (caption «Судью видят только администраторы»)
 * lists one page of GET /admin/orders: № / Название / Автор (flag stub +
 * short name) / Судья (name or «—») / Статус (badge «Нет судьи» /
 * «Ждёт вердикта», a red «Просрочен» on top of it when `overdue`,
 * green «Вердикт вынесен») / action («Переназначить…» on an assigned
 * order, accent «Назначить…» on a judgeless one, «—» on a decided).
 * Above the card — the «Все / Без судьи / Ждут вердикта / С вердиктом»
 * segment, the «Номер или название» search (debounced) and «Показано
 * N»; «Показать ещё» pages further while total exceeds what is shown.
 *
 * Under it sits the state-view card the unit-6a state view used to
 * carry (Spec 5.7, GET /admin/state's 04_orders slice): the
 * distribution worker's mode and last pass plus the stage, unassigned
 * and overdue counters — kept because the new list does not show it.
 *
 * «Назначить…»/«Переназначить…» opens the screen-05 M-size Popup
 * («Назначить судью» / «Переназначить судью»): the grey card with
 * «Приказ № N», title, author nation and the current judge (or
 * «судьи пока нет»), the «Новый судья» field suggesting from
 * GET /admin/players?search=&limit=8 (the admins-section pattern),
 * the «Назначить себя» link (self vk id from GET /admin/admins'
 * `is_self` row, the name through the players search) and the warning
 * card re-fetched from GET /admin/orders/{n}/judge-preview on every
 * judge change — the fixed lead «Бот ничего не напишет.», every
 * `warnings[].text` verbatim, the fixed closing sentence; a `blocker`
 * code shows its Russian line instead and keeps the action disabled,
 * as does an empty field. Stale preview answers are dropped by a
 * sequence counter. «Назначить судью» POSTs /admin/orders/{n}/judge;
 * success closes the popup, fires the Notice and reloads the list
 * keeping filter and search; a refusal shows its line inside.
 *
 * A 401 from any call ends the session through the frame's
 * reportUnauthorized — the same rule every panel section follows.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { ERRORS_RU, fallbackErrorRu } from '../../../shared/texts/errors.ru';
import type {
  AdminOrderDTO,
  AdminOrderJudgePreviewDTO,
  AdminOrdersStateViewDTO,
  AdminPlayerDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { FlagMark } from '../../../shared/ui/FlagMark';
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

const PAGE_SIZE = 50;
/** The search fires on a pause, not on every keystroke. */
const SEARCH_DEBOUNCE_MS = 350;
/** The judge suggestion list's page size (GET /admin/players?limit=8). */
const SUGGEST_LIMIT = 8;

const SEARCH_PLACEHOLDER = 'Номер или название';
const JUDGE_FIELD_LABEL = 'Новый судья (поиск по имени или VK ID)';
const WARNING_LEAD = 'Бот ничего не напишет.';
const WARNING_CLOSING =
  'Порог рейтинга и предел вердиктов на одного судью к администратору ' +
  'не применяются. Для игроков судья по-прежнему анонимен.';

type StatusFilter = 'all' | 'waiting' | 'assigned' | 'decided';

const STATUS_SEGMENTS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'waiting', label: 'Без судьи' },
  { value: 'assigned', label: 'Ждут вердикта' },
  { value: 'decided', label: 'С вердиктом' },
];

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup 05: .card, .btn, .seg, .warn).*/
/* ---------------------------------------------------------------- */

function PanelCard({
  title,
  aside,
  children,
}: {
  title: string;
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
            color: tokenVar('ink'),
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

/** One segment of the status switch (mockup .seg). */
function SegmentButton({
  on,
  onClick,
  testId,
  children,
}: {
  on: boolean;
  onClick: () => void;
  testId: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        height: SIZES['button-h-small'],
        padding: '0 12px',
        border: 'none',
        borderRadius: 6,
        whiteSpace: 'nowrap',
        cursor: 'pointer',
        background: on ? tokenVar('surface') : 'transparent',
        color: tokenVar(on ? 'ink' : 'ink-muted'),
        ...TEXT_STYLES['body'],
      }}
    >
      {children}
    </button>
  );
}

/** The row's status badge (.badge / .badge.ok). */
function StatusBadge({ order }: { order: AdminOrderDTO }) {
  const badge: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '2px 8px',
    borderRadius: 999,
    ...TEXT_STYLES['caption'],
    whiteSpace: 'nowrap',
  };
  const base =
    order.status === 'DECIDED' ? (
      <span
        data-testid={`status-${order.number}`}
        style={{
          ...badge,
          background: tokenVar('warning-bg'),
          color: tokenVar('positive'),
        }}
      >
        Вердикт вынесен
      </span>
    ) : (
      <span
        data-testid={`status-${order.number}`}
        style={{
          ...badge,
          background: tokenVar('surface-inset'),
          color: tokenVar('ink'),
        }}
      >
        {order.status === 'AWAITING_VERDICT' ? 'Ждёт вердикта' : 'Нет судьи'}
      </span>
    );
  if (!order.overdue) {
    return base;
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      {base}
      <span
        data-testid={`overdue-${order.number}`}
        style={{
          ...badge,
          background: tokenVar('surface-inset'),
          color: tokenVar('danger'),
        }}
      >
        Просрочен
      </span>
    </span>
  );
}

/** The 22×14 author-nation flag of an order row — thumb or stub. */
function FlagCell({ url }: { url: string | null }) {
  return (
    <FlagMark url={url} width={22} height={14} stubVariant="cell" />
  );
}

/** The .warn caution block of the judge popup. */
function WarnBlock({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="judge-warning"
      style={{
        background: tokenVar('warning-bg'),
        borderRadius: RADII['radius-md'],
        padding: SPACING['space-3'],
        display: 'flex',
        gap: 12,
        color: tokenVar('ink'),
        ...TEXT_STYLES['body'],
      }}
    >
      <svg
        width={18}
        height={18}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        style={{ flexShrink: 0, marginTop: 2 }}
      >
        <path d="M8 1.8 15 13.8H1z" />
        <path d="M8 6.4v3.2M8 11.8h.01" />
      </svg>
      <span>{children}</span>
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Display helpers.                                                  */
/* ---------------------------------------------------------------- */

/** The name line of a player — the display name or the VK id. */
function nameOf(vkUserId: number | null, displayName: string | null): string {
  return displayName ?? (vkUserId !== null ? `VK ${vkUserId}` : '—');
}

/** The popup's blocker code → its Russian line from the dictionary. */
function blockerText(code: string): string {
  const entry = ERRORS_RU[code];
  return typeof entry === 'string' ? entry : fallbackErrorRu(code);
}

/**
 * The `04_orders` slice of GET /admin/state — guarded: a failing hook
 * lands as {"error": "..."} instead of the view's keys.
 */
function ordersStateView(
  stateModules: Record<string, unknown>,
): AdminOrdersStateViewDTO | null {
  const slice = stateModules['04_orders'];
  if (
    slice === null ||
    typeof slice !== 'object' ||
    !('worker_mode' in slice)
  ) {
    return null;
  }
  return slice as AdminOrdersStateViewDTO;
}

/** "2026-10-25 00:00:03" → "25.10.2026 00:00"; NULL → "—". */
function passAtText(value: string | null): string {
  if (value === null) {
    return '—';
  }
  const [datePart, timePart = ''] = value.split(' ');
  const [year, month, day] = datePart.split('-');
  return `${day}.${month}.${year} ${timePart.slice(0, 5)}`;
}

/* ---------------------------------------------------------------- */
/* The judge popup (mockup 05's .pop at 640 px → the M size).        */
/* ---------------------------------------------------------------- */

function JudgePopup({
  order,
  onClose,
  onAssigned,
}: {
  order: AdminOrderDTO;
  onClose: () => void;
  onAssigned: (item: AdminOrderDTO) => void;
}) {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();
  const reassign = order.judge_vk_user_id !== null;

  const [search, setSearch] = useState('');
  const [suggestions, setSuggestions] = useState<AdminPlayerDTO[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [chosen, setChosen] = useState<AdminPlayerDTO | null>(null);

  const [preview, setPreview] = useState<AdminOrderJudgePreviewDTO | null>(
    null,
  );
  const [previewFailed, setPreviewFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  // Guards: only the latest suggest/preview answer writes.
  const suggestSeq = useRef(0);
  const previewSeq = useRef(0);

  // The suggestion fetch fires on a pause, not on every keystroke.
  useEffect(() => {
    const text = search.trim();
    if (chosen !== null || text === '') {
      setSuggestions([]);
      return;
    }
    const id = setTimeout(() => {
      const seq = ++suggestSeq.current;
      api
        .adminPlayers(token, { search: text, limit: SUGGEST_LIMIT })
        .then((page) => {
          if (seq === suggestSeq.current) {
            setSuggestions(page.items);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            reportUnauthorized();
            return;
          }
          if (seq === suggestSeq.current) {
            setSuggestions([]);
          }
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [search, chosen, token, reportUnauthorized]);

  // The warning card follows the chosen judge — re-fetched on every
  // change, stale answers dropped by the sequence counter.
  useEffect(() => {
    if (chosen === null) {
      setPreview(null);
      setPreviewFailed(false);
      return;
    }
    const judge = chosen;
    const seq = ++previewSeq.current;
    setPreview(null);
    setPreviewFailed(false);
    api
      .adminOrderJudgePreview(token, order.number, judge.vk_user_id)
      .then((answer) => {
        if (seq === previewSeq.current) {
          setPreview(answer);
        }
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq === previewSeq.current) {
          setPreviewFailed(true);
        }
      });
  }, [chosen, order.number, token, reportUnauthorized]);

  const pickPlayer = (player: AdminPlayerDTO) => {
    setChosen(player);
    setSearch(nameOf(player.vk_user_id, player.display_name));
    setSuggestions([]);
    setSuggestOpen(false);
    setAssignError(null);
  };

  const onSearchChange = (value: string) => {
    setChosen(null);
    setSearch(value);
    setSuggestOpen(true);
  };

  // «Назначить себя»: the frame's session names the current
  // administrator through the admins list's `is_self` row; the players
  // search resolves the display name for the field.
  const assignSelf = async () => {
    try {
      const admins = await api.adminAdmins(token);
      const me = admins.find((entry) => entry.is_self);
      if (me === undefined) {
        return;
      }
      const page = await api.adminPlayers(token, {
        search: String(me.vk_user_id),
        limit: SUGGEST_LIMIT,
      });
      const myself =
        page.items.find((p) => p.vk_user_id === me.vk_user_id) ?? null;
      if (myself !== null) {
        pickPlayer(myself);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
      }
    }
  };

  const runAssign = async () => {
    if (chosen === null || preview?.blocker) {
      return;
    }
    setBusy(true);
    setAssignError(null);
    try {
      const item = await api.adminOrderAssignJudge(
        token,
        order.number,
        chosen.vk_user_id,
      );
      notify(
        reassign
          ? `Судья приказа № ${order.number} заменён.`
          : `Приказу № ${order.number} назначен судья.`,
      );
      onClose();
      onAssigned(item);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setAssignError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Popup
      size="M"
      title={reassign ? 'Переназначить судью' : 'Назначить судью'}
      testId="judge-popup"
      dirty={chosen !== null}
      onClose={onClose}
      footer={
        <>
          <PanelButton disabled={busy} onClick={onClose}>
            Отмена
          </PanelButton>
          <PanelButton
            kind="primary"
            disabled={busy || chosen === null || preview?.blocker != null}
            testId="judge-assign"
            onClick={() => void runAssign()}
          >
            Назначить судью
          </PanelButton>
        </>
      }
    >
      {/* The grey .info card: order number, title, author nation and
          the sitting judge. */}
      <div
        data-testid="judge-order-card"
        style={{
          background: tokenVar('surface-inset'),
          borderRadius: RADII['radius-md'],
          padding: SPACING['space-3'],
          color: tokenVar('ink'),
          ...TEXT_STYLES['body'],
        }}
      >
        <span
          style={{ ...TEXT_STYLES['caption'], color: tokenVar('ink-muted') }}
        >
          Приказ № {order.number}
        </span>
        <br />
        {order.title}
        {' · '}
        {order.author_nation_short_name ?? '—'}
        {' · '}
        {reassign
          ? `судья сейчас: ${nameOf(
              order.judge_vk_user_id,
              order.judge_name,
            )}`
          : 'судьи пока нет'}
      </div>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          minWidth: 0,
        }}
      >
        <label
          htmlFor="judge-search"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {JUDGE_FIELD_LABEL}
        </label>
        <div style={{ position: 'relative' }}>
          <input
            id="judge-search"
            data-testid="judge-search"
            value={search}
            autoComplete="off"
            onChange={(event) => onSearchChange(event.currentTarget.value)}
            onFocus={() => setSuggestOpen(true)}
            onBlur={() => setSuggestOpen(false)}
            onKeyDown={(event) => {
              // Enter never submits anything anywhere in the app.
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              height: SIZES['button-h'],
              padding: '0 12px',
              borderRadius: RADII['radius-md'],
              background: tokenVar('surface-inset'),
              border: `1px solid ${tokenVar('ink-faint')}`,
              color: tokenVar('ink'),
              ...TEXT_STYLES['body'],
            }}
          />
          {suggestOpen && chosen === null && suggestions.length > 0 && (
            <div
              data-testid="judge-suggestions"
              style={{
                position: 'absolute',
                top: SIZES['button-h'] + 4,
                left: 0,
                right: 0,
                background: tokenVar('surface-raised'),
                border: `1px solid ${tokenVar('line')}`,
                borderRadius: RADII['radius-md'],
                overflow: 'hidden',
                zIndex: 10,
              }}
            >
              {suggestions.map((player) => (
                <button
                  key={player.vk_user_id}
                  type="button"
                  data-testid={`judge-suggest-${player.vk_user_id}`}
                  // mousedown runs before the input's blur hides the list.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    pickPlayer(player);
                  }}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '8px 12px',
                    border: 'none',
                    background: 'transparent',
                    color: tokenVar('ink'),
                    cursor: 'pointer',
                    ...TEXT_STYLES['body'],
                  }}
                >
                  {nameOf(player.vk_user_id, player.display_name)}
                  {player.display_name !== null && (
                    <span
                      style={{
                        ...TEXT_STYLES['caption'],
                        color: tokenVar('ink-muted'),
                      }}
                    >
                      {' '}
                      · VK {player.vk_user_id}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <span
        style={{ ...TEXT_STYLES['caption'], color: tokenVar('ink-muted') }}
      >
        <button
          type="button"
          data-testid="judge-assign-self"
          onClick={() => void assignSelf()}
          style={{
            border: 'none',
            background: 'transparent',
            padding: 0,
            color: tokenVar('action'),
            cursor: 'pointer',
            ...TEXT_STYLES['body'],
          }}
        >
          Назначить себя
        </button>
      </span>

      {chosen !== null &&
        (preview !== null ? (
          preview.blocker !== null ? (
            <WarnBlock>
              <span data-testid="judge-blocker">
                {blockerText(preview.blocker)}
              </span>
            </WarnBlock>
          ) : (
            <WarnBlock>
              <b style={{ fontWeight: 500 }}>{WARNING_LEAD}</b>{' '}
              {preview.warnings.map((warning) => warning.text).join(' ')}{' '}
              {WARNING_CLOSING}
            </WarnBlock>
          )
        ) : previewFailed ? (
          <WarnBlock>
            <span data-testid="judge-preview-failed">
              Не удалось проверить назначение — попробуйте ещё раз.
            </span>
          </WarnBlock>
        ) : (
          <LoadingState height={52} />
        ))}

      {assignError !== null && (
        <span
          data-testid="judge-assign-error"
          style={{ ...TEXT_STYLES['caption'], color: tokenVar('danger') }}
        >
          {assignError}
        </span>
      )}
    </Popup>
  );
}

/* ---------------------------------------------------------------- */
/* The section.                                                      */
/* ---------------------------------------------------------------- */

type ListStatus = 'loading' | 'ready' | 'error';
type StateStatus = 'loading' | 'ready' | 'error';

export function OrdersSection() {
  const { token, reportUnauthorized } = useAdminSession();

  const [items, setItems] = useState<AdminOrderDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [filter, setFilter] = useState<StatusFilter>('all');

  // The kept unit-6a state view: the worker's mode and counters.
  const [stateView, setStateView] = useState<AdminOrdersStateViewDTO | null>(
    null,
  );
  const [stateStatus, setStateStatus] = useState<StateStatus>('loading');

  const [target, setTarget] = useState<AdminOrderDTO | null>(null);

  // Guards: only the latest load writes, so a stale answer can never
  // land after a newer search or filter.
  const loadSeq = useRef(0);

  const load = useCallback(
    async (
      statusFilter: StatusFilter,
      searchText: string,
      offset: number,
      append: boolean,
    ) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminOrders(token, {
          status: statusFilter,
          search: searchText,
          limit: PAGE_SIZE,
          offset,
        });
        if (seq !== loadSeq.current) {
          return;
        }
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
        setTotal(page.total);
        setStatus('ready');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq !== loadSeq.current) {
          return;
        }
        if (append) {
          // «Показать ещё» failures keep the loaded rows.
          setLoadingMore(false);
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

  const loadState = useCallback(async () => {
    try {
      const state = await api.adminState(token);
      setStateView(ordersStateView(state.modules));
      setStateStatus('ready');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      setStateStatus('error');
    }
  }, [token, reportUnauthorized]);

  // The search debounce → applied query → fresh first page.
  useEffect(() => {
    const id = setTimeout(
      () => setAppliedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    setStatus('loading');
    void load(filter, appliedSearch, 0, false);
  }, [filter, appliedSearch, load]);

  useEffect(() => {
    void loadState();
  }, [loadState]);

  const loadMore = () => {
    setLoadingMore(true);
    void load(filter, appliedSearch, items.length, true);
  };

  const cellStyle = (last: boolean) => ({
    height: 44,
    padding: '4px 12px',
    borderBottom: last ? 'none' : `1px solid ${tokenVar('line')}`,
    verticalAlign: 'middle' as const,
    ...TEXT_STYLES['body'],
  });

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
        <PanelIcon name="document" accent size={20} />
        Приказы
      </h1>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
          flexWrap: 'wrap',
        }}
      >
        <div
          role="group"
          aria-label="Фильтр по статусу"
          style={{
            display: 'inline-flex',
            gap: 4,
            background: tokenVar('surface-inset'),
            borderRadius: RADII['radius-md'],
            padding: 2,
          }}
        >
          {STATUS_SEGMENTS.map((segment) => (
            <SegmentButton
              key={segment.value}
              on={filter === segment.value}
              testId={`filter-${segment.value}`}
              onClick={() => setFilter(segment.value)}
            >
              {segment.label}
            </SegmentButton>
          ))}
        </div>
        <div style={{ width: 280 }}>
          <label
            htmlFor="orders-search"
            style={{
              position: 'absolute',
              left: -9999,
              ...TEXT_STYLES['caption'],
            }}
          >
            Поиск
          </label>
          <input
            id="orders-search"
            data-testid="orders-search"
            value={search}
            placeholder={SEARCH_PLACEHOLDER}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              height: SIZES['button-h'],
              padding: '0 12px',
              borderRadius: RADII['radius-md'],
              background: tokenVar('surface-inset'),
              border: `1px solid ${tokenVar('ink-faint')}`,
              color: tokenVar('ink'),
              ...TEXT_STYLES['body'],
            }}
          />
        </div>
        <span
          data-testid="orders-shown"
          style={{
            flexGrow: 1,
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {status === 'ready' && `Показано ${items.length}`}
        </span>
      </div>

      <PanelCard
        title="Приказы"
        aside={
          <span
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
              whiteSpace: 'nowrap',
            }}
          >
            Судью видят только администраторы
          </span>
        }
      >
        {status === 'loading' && <LoadingState height={150} />}
        {status === 'error' && (
          <ErrorState
            onRetry={() => {
              setStatus('loading');
              void load(filter, appliedSearch, 0, false);
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState
            text={
              appliedSearch === '' && filter === 'all'
                ? 'Приказов пока нет.'
                : 'Ничего не нашлось по этому запросу.'
            }
          />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="orders-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['№', 'Название', 'Автор', 'Судья', 'Статус', ''].map(
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
              {items.map((order, index) => (
                <tr key={order.number} data-testid={`order-row-${order.number}`}>
                  <td
                    style={{
                      ...cellStyle(index === items.length - 1),
                      fontFamily: 'monospace',
                    }}
                  >
                    {order.number}
                  </td>
                  <td style={cellStyle(index === items.length - 1)}>
                    {order.title}
                  </td>
                  <td style={cellStyle(index === items.length - 1)}>
                    {order.author_nation_short_name !== null ? (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 10,
                        }}
                      >
                        <FlagCell url={order.flag_thumb_url} />
                        <span>{order.author_nation_short_name}</span>
                      </span>
                    ) : (
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        —
                      </span>
                    )}
                  </td>
                  <td style={cellStyle(index === items.length - 1)}>
                    {order.judge_vk_user_id !== null ? (
                      nameOf(order.judge_vk_user_id, order.judge_name)
                    ) : (
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        —
                      </span>
                    )}
                  </td>
                  <td style={cellStyle(index === items.length - 1)}>
                    <StatusBadge order={order} />
                  </td>
                  <td
                    style={{
                      ...cellStyle(index === items.length - 1),
                      textAlign: 'right',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {order.status === 'DECIDED' ? (
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        —
                      </span>
                    ) : (
                      <PanelButton
                        kind={
                          order.status === 'AWAITING_VERDICT'
                            ? 'plain'
                            : 'primary'
                        }
                        small
                        testId={`assign-${order.number}`}
                        onClick={() => setTarget(order)}
                      >
                        {order.status === 'AWAITING_VERDICT'
                          ? 'Переназначить…'
                          : 'Назначить…'}
                      </PanelButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </PanelCard>

      {status === 'ready' && items.length < total && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <PanelButton
            testId="orders-load-more"
            disabled={loadingMore}
            onClick={loadMore}
          >
            Показать ещё
          </PanelButton>
        </div>
      )}

      {/* The 6a state view's non-table part, kept: the distribution
          worker's mode and last pass plus the stage counters. */}
      <PanelCard title="Служба распределения">
        {stateStatus === 'loading' && <LoadingState height={60} />}
        {stateStatus === 'error' && (
          <ErrorState onRetry={() => void loadState()} />
        )}
        {stateStatus === 'ready' && stateView === null && (
          <EmptyState text="Сведений о службе нет." />
        )}
        {stateStatus === 'ready' && stateView !== null && (
          <div
            data-testid="orders-state"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '6px 24px',
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            <span>
              Режим:{' '}
              <span style={{ color: tokenVar('ink') }}>
                {stateView.worker_mode === 'RUNNING'
                  ? 'работает'
                  : 'остановлена'}
              </span>
            </span>
            <span>
              Последний проход:{' '}
              <span style={{ color: tokenVar('ink') }}>
                {passAtText(stateView.last_pass_at)}
              </span>
            </span>
            <span>
              Без судьи:{' '}
              <span style={{ color: tokenVar('ink') }}>
                {stateView.unassigned_total}
              </span>
            </span>
            <span>
              Ждут вердикта:{' '}
              <span style={{ color: tokenVar('ink') }}>
                {stateView.stages.DISTRIBUTED}
              </span>
            </span>
            <span>
              Просрочено:{' '}
              <span
                style={{
                  color:
                    stateView.overdue_total > 0
                      ? tokenVar('danger')
                      : tokenVar('ink'),
                }}
              >
                {stateView.overdue_total}
              </span>
            </span>
          </div>
        )}
      </PanelCard>

      {target !== null && (
        <JudgePopup
          order={target}
          onClose={() => setTarget(null)}
          onAssigned={() => {
            setStatus('loading');
            void load(filter, appliedSearch, 0, false);
            void loadState();
          }}
        />
      )}
    </>
  );
}
