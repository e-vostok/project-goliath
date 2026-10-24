/**
 * PlayersSection — «Игроки» (0.11.0 unit 6b), approved mockup
 * docs/06_DESIGN/0.11.0 screen 06.
 *
 * One card with the players table: name over «VK <id>», the nation's
 * short name or the grey «Государства нет», the registration date, an
 * «Администратор» badge for admins, and the last column's red-outline
 * «Удалить…» — admins get the grey «Администратора удалить нельзя»
 * instead. Above the card sits the search row of screen 03's pattern
 * (hidden label + «Показано N из M»); «Показать ещё» pages further
 * while `total` exceeds what is shown.
 *
 * «Удалить…» opens the shared S-size Popup: the fixed warning line,
 * the non-zero consequences of GET /admin/players/{id}/delete-preview
 * as bullets, a retype-the-VK-id confirmation field and «Отмена» /
 * «Удалить игрока» — danger, disabled until the typed id matches
 * exactly. On success the shared Notice fires, the popup closes and
 * the list reloads. Server refusals (CANNOT_DELETE_SELF,
 * CANNOT_DELETE_ADMIN and friends) show their Russian line inside the
 * popup — it stays open.
 *
 * A 401 from any call ends the session through the frame's
 * reportUnauthorized — the same rule every panel section follows.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminPlayerDTO,
  AdminPlayerDeleteResultDTO,
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

const PAGE_SIZE = 50;
/** The search fires on a pause, not on every keystroke. */
const SEARCH_DEBOUNCE_MS = 350;

const SEARCH_PLACEHOLDER = 'Поиск по имени, VK ID или государству';
const DELETE_WARNING =
  'Это нельзя отменить. Вместе с игроком исчезнет:';
const ADMIN_UNDELETABLE = 'Администратора удалить нельзя';

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup 06: .card, .btn, .badge).     */
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

/* ---------------------------------------------------------------- */
/* Display helpers.                                                  */
/* ---------------------------------------------------------------- */

/** "2026-10-25 00:00:03" → "25.10.2026" — the mockup's date column. */
function registrationDate(value: string): string {
  const [year, month, day] = value.split(' ')[0].split('-');
  return `${day}.${month}.${year}`;
}

/** The name line of a player cell / popup title — name or the VK id. */
function displayName(player: AdminPlayerDTO): string {
  return player.display_name ?? `VK ${player.vk_user_id}`;
}

/**
 * The non-zero "what disappears" lines of a delete-preview — one
 * bullet per consequence, zero counts skipped (mockup 06 wording).
 */
function consequenceLines(preview: AdminPlayerDeleteResultDTO): string[] {
  const lines: string[] = [];
  if (preview.nation_name !== null) {
    lines.push(
      `государство «${preview.nation_name}», ` +
        `${preview.provinces_released} провинций станут свободными;`,
    );
  }
  if (preview.orders_author > 0) {
    lines.push(`приказов автора: ${preview.orders_author};`);
  }
  if (preview.orders_judge_undecided > 0) {
    lines.push(
      `приказов судьи без вердикта: ${preview.orders_judge_undecided};`,
    );
  }
  if (preview.orders_judge_decided > 0) {
    lines.push(
      `приказов судьи с вердиктом: ${preview.orders_judge_decided};`,
    );
  }
  if (preview.outbox_rows > 0) {
    lines.push(`сообщений в очереди бота: ${preview.outbox_rows};`);
  }
  if (preview.consent_rows > 0) {
    lines.push('согласие на сообщения;');
  }
  if (preview.vk_profile_rows > 0) {
    lines.push('кэш профиля ВК.');
  }
  return lines;
}

/* ---------------------------------------------------------------- */
/* The section.                                                      */
/* ---------------------------------------------------------------- */

type ListStatus = 'loading' | 'ready' | 'error';

export function PlayersSection() {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();

  const [items, setItems] = useState<AdminPlayerDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');

  const [target, setTarget] = useState<AdminPlayerDTO | null>(null);
  const [preview, setPreview] = useState<AdminPlayerDeleteResultDTO | null>(
    null,
  );
  const [previewFailed, setPreviewFailed] = useState(false);
  const [typedId, setTypedId] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Guards: only the latest load writes, so a stale answer can never
  // land after a newer search.
  const loadSeq = useRef(0);

  const load = useCallback(
    async (searchText: string, offset: number, append: boolean) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminPlayers(token, {
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
    void load(appliedSearch, 0, false);
  }, [appliedSearch, load]);

  const loadMore = () => {
    setLoadingMore(true);
    void load(appliedSearch, items.length, true);
  };

  const openDelete = (player: AdminPlayerDTO) => {
    setTarget(player);
    setPreview(null);
    setPreviewFailed(false);
    setTypedId('');
    setDeleteError(null);
    api
      .adminPlayerDeletePreview(token, String(player.vk_user_id))
      .then(setPreview)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        setPreviewFailed(true);
      });
  };

  const closeDelete = () => {
    setTarget(null);
    setPreview(null);
    setTypedId('');
    setDeleteError(null);
  };

  const runDelete = async () => {
    if (target === null) {
      return;
    }
    setBusy(true);
    setDeleteError(null);
    try {
      await api.adminPlayerDelete(
        token,
        String(target.vk_user_id),
        typedId.trim(),
      );
      const name = displayName(target);
      closeDelete();
      notify(`Игрок «${name}» удалён.`);
      await load(appliedSearch, 0, false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setDeleteError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const expectedId = target === null ? '' : String(target.vk_user_id);

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
        <PanelIcon name="players" accent size={20} />
        Игроки
      </h1>

      {/* The screen-03 search row: a visually-hidden label, the field,
          and the «Показано N из M» caption on the right. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        <div style={{ width: 280 }}>
          <label
            htmlFor="players-search"
            style={{
              position: 'absolute',
              left: -9999,
              ...TEXT_STYLES['caption'],
            }}
          >
            Поиск
          </label>
          <input
            id="players-search"
            data-testid="players-search"
            value={search}
            placeholder={SEARCH_PLACEHOLDER}
            onChange={(event) => setSearch(event.currentTarget.value)}
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
          data-testid="players-shown"
          style={{
            flexGrow: 1,
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {status === 'ready' && `Показано ${items.length} из ${total}`}
        </span>
      </div>

      <PanelCard
        title="Игроки"
        aside={
          <span
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
              whiteSpace: 'nowrap',
            }}
          >
            Удаление — только для тестовых игроков, необратимо
          </span>
        }
      >
        {status === 'loading' && <LoadingState height={150} />}
        {status === 'error' && (
          <ErrorState
            onRetry={() => {
              setStatus('loading');
              void load(appliedSearch, 0, false);
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState
            text={
              appliedSearch === ''
                ? 'Игроков пока нет.'
                : 'Никого не нашлось по этому запросу.'
            }
          />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="players-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['Игрок', 'Государство', 'Регистрация', 'Роль', ''].map(
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
              {items.map((player, index) => (
                <tr key={player.vk_user_id} data-testid="player-row">
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
                      {displayName(player)}
                    </span>
                    {player.display_name !== null && (
                      <>
                        <br />
                        <span
                          style={{
                            ...TEXT_STYLES['caption'],
                            fontFamily: 'monospace',
                            color: tokenVar('ink-muted'),
                          }}
                        >
                          VK {player.vk_user_id}
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
                    {player.nation_short_name !== null ? (
                      player.nation_short_name
                    ) : (
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        Государства нет
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
                      fontFamily: 'monospace',
                    }}
                  >
                    {registrationDate(player.created_at)}
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
                    {player.is_admin ? (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '2px 8px',
                          borderRadius: 999,
                          background: tokenVar('surface-inset'),
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink'),
                        }}
                      >
                        Администратор
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
                    {player.is_admin ? (
                      <span
                        style={{
                          ...TEXT_STYLES['caption'],
                          color: tokenVar('ink-muted'),
                        }}
                      >
                        {ADMIN_UNDELETABLE}
                      </span>
                    ) : (
                      <PanelButton
                        kind="danger-outline"
                        small
                        testId={`delete-${player.vk_user_id}`}
                        onClick={() => openDelete(player)}
                      >
                        Удалить…
                      </PanelButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {status === 'ready' && items.length < total && (
          <div>
            <PanelButton
              disabled={loadingMore}
              testId="players-show-more"
              onClick={loadMore}
            >
              {loadingMore ? 'Загрузка…' : 'Показать ещё'}
            </PanelButton>
          </div>
        )}
      </PanelCard>

      {target !== null && (
        <Popup
          size="S"
          title={`Удалить игрока «${displayName(target)}»?`}
          testId="player-delete-popup"
          dirty={typedId !== ''}
          onClose={closeDelete}
          footer={
            <>
              <PanelButton disabled={busy} onClick={closeDelete}>
                Отмена
              </PanelButton>
              <PanelButton
                kind="danger"
                disabled={
                  busy || preview === null || typedId.trim() !== expectedId
                }
                testId="confirm-player-delete"
                onClick={() => void runDelete()}
              >
                Удалить игрока
              </PanelButton>
            </>
          }
        >
          <span style={TEXT_STYLES['body']}>{DELETE_WARNING}</span>
          {preview === null && !previewFailed && (
            <LoadingState height={60} />
          )}
          {previewFailed && (
            <span
              data-testid="player-delete-preview-error"
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('danger'),
              }}
            >
              Не удалось загрузить список последствий — закройте окно и
              попробуйте ещё раз.
            </span>
          )}
          {preview !== null && (
            <ul
              data-testid="player-delete-consequences"
              style={{
                margin: 0,
                paddingLeft: 20,
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              {consequenceLines(preview).map((line) => (
                <li key={line} style={TEXT_STYLES['body']}>
                  {line}
                </li>
              ))}
            </ul>
          )}
          <TextField
            id="player-delete-confirm"
            label={`Для подтверждения введите VK ID: ${expectedId}`}
            value={typedId}
            onChange={setTypedId}
          />
          {deleteError !== null && (
            <span
              data-testid="player-delete-error"
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('danger'),
              }}
            >
              {deleteError}
            </span>
          )}
        </Popup>
      )}
    </>
  );
}
