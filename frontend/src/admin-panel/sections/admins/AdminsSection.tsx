/**
 * AdminsSection — «Администраторы» (0.11.0 unit 7), approved mockup
 * docs/06_DESIGN/0.11.0 screen 07.
 *
 * Two cards. «Администраторы» — the table of everyone holding admin
 * rights: the player (name over «VK <id>»), where the right comes
 * from («Из настроек сервера» / «Выдано через панель»), who granted
 * it and when; the last column carries the red-outline «Снять
 * права…» — env admins and the current administrator get the grey
 * «Снять нельзя» instead. «Выдать права» — a search field suggesting
 * players from GET /admin/players?search=&limit=8, the chosen player
 * shown in the field, and «Выдать права…» disabled until a player is
 * chosen.
 *
 * Both buttons open the shared S-size Popup («Выдать права
 * администратора игроку «<имя>»?» / «Снять права администратора у
 * игрока «<имя>»?») with the mockup's warning text and «Отмена» /
 * «Выдать» or «Снять права». Server refusals keep the popup open with
 * their own Russian line (LAST_ADMIN, ROOT_ADMIN_PROTECTED,
 * CANNOT_REVOKE_SELF).
 *
 * A 401 from any call ends the session through the frame's
 * reportUnauthorized — the same rule every panel section follows.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminEntryDTO,
  AdminPlayerDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
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

const SEARCH_DEBOUNCE_MS = 300;
const SUGGEST_LIMIT = 8;

const GRANT_WARNING =
  'Администратор может всё в этой панели, включая сброс мира и ' +
  'удаление игроков. Каждое действие записывается в журнал. ' +
  'Администраторов из настроек сервера снять нельзя, а последнего ' +
  'администратора снять не получится.';
const SEARCH_LABEL = 'Игрок (поиск по имени или VK ID)';
const SEARCH_PLACEHOLDER = 'Имя или VK ID';
const REVOKE_FORBIDDEN = 'Снять нельзя';

/** The panel's own Russian line for each grant/revoke refusal. */
const REFUSAL_TEXTS: Record<string, string> = {
  LAST_ADMIN: 'Нельзя снять последнего администратора',
  ROOT_ADMIN_PROTECTED:
    'Этого администратора можно убрать только в настройках сервера',
  CANNOT_REVOKE_SELF: 'Нельзя снять права у самого себя',
};

function refusalText(error: unknown): string {
  if (error instanceof ApiError && error.code in REFUSAL_TEXTS) {
    return REFUSAL_TEXTS[error.code];
  }
  return errorText(error);
}

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup 07: .card, .btn, .warn).      */
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

/** The yellow caution block of the «Выдать права» card (mockup .warn). */
function WarnBlock({ text }: { text: string }) {
  return (
    <div
      data-testid="grant-warning"
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
      <span>{text}</span>
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Display helpers.                                                  */
/* ---------------------------------------------------------------- */

/** The name line of a player cell — the display name or the VK id. */
function nameOf(vkUserId: number, displayName: string | null): string {
  return displayName ?? `VK ${vkUserId}`;
}

/** "2026-10-24 15:40:12" → "24.10.2026 15:40" — the mockup's cell. */
function grantedAtText(value: string): string {
  const [datePart, timePart = ''] = value.split(' ');
  const [year, month, day] = datePart.split('-');
  return `${day}.${month}.${year} ${timePart.slice(0, 5)}`;
}

/* ---------------------------------------------------------------- */
/* The section.                                                      */
/* ---------------------------------------------------------------- */

type ListStatus = 'loading' | 'ready' | 'error';

type ConfirmPopup =
  | { kind: 'grant'; player: AdminPlayerDTO }
  | { kind: 'revoke'; admin: AdminEntryDTO };

export function AdminsSection() {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();

  const [items, setItems] = useState<AdminEntryDTO[]>([]);
  const [status, setStatus] = useState<ListStatus>('loading');

  // The «Выдать права» search: text in the field, the debounced
  // suggestions, the picked player.
  const [search, setSearch] = useState('');
  const [suggestions, setSuggestions] = useState<AdminPlayerDTO[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [chosen, setChosen] = useState<AdminPlayerDTO | null>(null);

  const [popup, setPopup] = useState<ConfirmPopup | null>(null);
  const [busy, setBusy] = useState(false);
  const [popupError, setPopupError] = useState<string | null>(null);

  // Guards: only the latest load/suggest writes.
  const loadSeq = useRef(0);
  const suggestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    try {
      const admins = await api.adminAdmins(token);
      if (seq !== loadSeq.current) {
        return;
      }
      setItems(admins);
      setStatus('ready');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      if (seq === loadSeq.current) {
        setStatus('error');
      }
    }
  }, [token, reportUnauthorized]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const pickPlayer = (player: AdminPlayerDTO) => {
    setChosen(player);
    setSearch(nameOf(player.vk_user_id, player.display_name));
    setSuggestions([]);
    setSuggestOpen(false);
  };

  const onSearchChange = (value: string) => {
    setChosen(null);
    setSearch(value);
    setSuggestOpen(true);
  };

  const openGrant = () => {
    if (chosen === null) {
      return;
    }
    setPopup({ kind: 'grant', player: chosen });
    setPopupError(null);
  };

  const openRevoke = (admin: AdminEntryDTO) => {
    setPopup({ kind: 'revoke', admin });
    setPopupError(null);
  };

  const closePopup = () => {
    setPopup(null);
    setPopupError(null);
  };

  const runGrant = async () => {
    if (popup === null || popup.kind !== 'grant') {
      return;
    }
    const player = popup.player;
    setBusy(true);
    setPopupError(null);
    try {
      await api.adminGrantAdmin(token, player.vk_user_id);
      const name = nameOf(player.vk_user_id, player.display_name);
      closePopup();
      setChosen(null);
      setSearch('');
      notify(`Игроку «${name}» выданы права администратора.`);
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setPopupError(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const runRevoke = async () => {
    if (popup === null || popup.kind !== 'revoke') {
      return;
    }
    const target = popup.admin;
    setBusy(true);
    setPopupError(null);
    try {
      await api.adminRevokeAdmin(token, target.vk_user_id);
      const name = nameOf(target.vk_user_id, target.display_name);
      closePopup();
      notify(`У игрока «${name}» сняты права администратора.`);
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      setPopupError(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const popupTitle =
    popup === null
      ? ''
      : popup.kind === 'grant'
        ? `Выдать права администратора игроку «${nameOf(
            popup.player.vk_user_id,
            popup.player.display_name,
          )}»?`
        : `Снять права администратора у игрока «${nameOf(
            popup.admin.vk_user_id,
            popup.admin.display_name,
          )}»?`;

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
        <PanelIcon name="shield" accent size={20} />
        Администраторы
      </h1>

      <PanelCard title="Администраторы">
        {status === 'loading' && <LoadingState height={150} />}
        {status === 'error' && (
          <ErrorState
            onRetry={() => {
              setStatus('loading');
              void load();
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState text="Администраторов нет." />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="admins-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['Игрок', 'Откуда право', 'Кто выдал', ''].map(
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
              {items.map((entry, index) => {
                const revocable =
                  entry.source !== 'env' && !entry.is_self;
                return (
                  <tr key={entry.vk_user_id} data-testid="admin-row">
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
                      }}
                    >
                      <span style={{ fontWeight: 500 }}>
                        {nameOf(entry.vk_user_id, entry.display_name)}
                      </span>
                      {entry.display_name !== null && (
                        <>
                          <br />
                          <span
                            style={{
                              ...TEXT_STYLES['caption'],
                              fontFamily: 'monospace',
                              color: tokenVar('ink-muted'),
                            }}
                          >
                            VK {entry.vk_user_id}
                          </span>
                        </>
                      )}
                    </td>
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
                      }}
                    >
                      {entry.source === 'env'
                        ? 'Из настроек сервера'
                        : 'Выдано через панель'}
                    </td>
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
                      }}
                    >
                      {entry.source === 'grant' ? (
                        <>
                          {entry.granted_by_vk_user_id !== null
                            ? nameOf(
                                entry.granted_by_vk_user_id,
                                entry.granted_by_name,
                              )
                            : '—'}
                          {entry.granted_at !== null && (
                            <>
                              <br />
                              <span
                                style={{
                                  ...TEXT_STYLES['caption'],
                                  color: tokenVar('ink-muted'),
                                }}
                              >
                                {grantedAtText(entry.granted_at)}
                              </span>
                            </>
                          )}
                        </>
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
                        textAlign: 'right',
                      }}
                    >
                      {revocable ? (
                        <PanelButton
                          kind="danger-outline"
                          small
                          testId={`revoke-${entry.vk_user_id}`}
                          onClick={() => openRevoke(entry)}
                        >
                          Снять права…
                        </PanelButton>
                      ) : (
                        <span
                          style={{
                            ...TEXT_STYLES['caption'],
                            color: tokenVar('ink-muted'),
                          }}
                        >
                          {REVOKE_FORBIDDEN}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </PanelCard>

      <PanelCard title="Выдать права">
        <div>
          <label
            htmlFor="admins-grant-search"
            style={{
              display: 'block',
              marginBottom: 6,
              ...TEXT_STYLES['label'],
              color: tokenVar('ink-muted'),
            }}
          >
            {SEARCH_LABEL}
          </label>
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: SPACING['space-3'],
            }}
          >
            <div style={{ position: 'relative', flexGrow: 1, minWidth: 0 }}>
              <input
                id="admins-grant-search"
                data-testid="admins-grant-search"
                value={search}
                placeholder={SEARCH_PLACEHOLDER}
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
                  data-testid="grant-suggestions"
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
                      data-testid={`suggest-${player.vk_user_id}`}
                      // mousedown runs before the input's blur hides the list.
                      onMouseDown={(event) => {
                        event.preventDefault();
                        pickPlayer(player);
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'baseline',
                        gap: 8,
                        width: '100%',
                        padding: '8px 12px',
                        border: 'none',
                        borderBottom: `1px solid ${tokenVar('line')}`,
                        background: 'transparent',
                        color: tokenVar('ink'),
                        textAlign: 'left',
                        cursor: 'pointer',
                        ...TEXT_STYLES['body'],
                      }}
                    >
                      <span style={{ fontWeight: 500 }}>
                        {nameOf(player.vk_user_id, player.display_name)}
                      </span>
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          fontFamily: 'monospace',
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        VK {player.vk_user_id}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <PanelButton
              kind="primary"
              disabled={chosen === null}
              testId="open-grant"
              onClick={openGrant}
            >
              Выдать права…
            </PanelButton>
          </div>
        </div>
        <WarnBlock text={GRANT_WARNING} />
      </PanelCard>

      {popup !== null && (
        <Popup
          size="S"
          title={popupTitle}
          testId={
            popup.kind === 'grant' ? 'grant-popup' : 'revoke-popup'
          }
          onClose={closePopup}
          footer={
            <>
              <PanelButton disabled={busy} onClick={closePopup}>
                Отмена
              </PanelButton>
              {popup.kind === 'grant' ? (
                <PanelButton
                  kind="primary"
                  disabled={busy}
                  testId="confirm-grant"
                  onClick={() => void runGrant()}
                >
                  Выдать
                </PanelButton>
              ) : (
                <PanelButton
                  kind="danger"
                  disabled={busy}
                  testId="confirm-revoke"
                  onClick={() => void runRevoke()}
                >
                  Снять права
                </PanelButton>
              )}
            </>
          }
        >
          <span style={TEXT_STYLES['body']}>{GRANT_WARNING}</span>
          {popupError !== null && (
            <span
              data-testid="admins-popup-error"
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('danger'),
              }}
            >
              {popupError}
            </span>
          )}
        </Popup>
      )}
    </>
  );
}
