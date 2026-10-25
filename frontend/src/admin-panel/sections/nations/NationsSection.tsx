/**
 * NationsSection — «Государства» (0.11.0 unit 8a), approved mockups
 * docs/06_DESIGN/0.11.0 screens 03 (list) and 03c (create).
 *
 * The list (screen 03): the search row with «Поиск по названию» and
 * «Показано N из M», the primary «Создать государство» button, and one
 * table card — Государство (catalog flag, short name over full name),
 * Владелец, Провинций, Столица — plus «Показать ещё» while total
 * exceeds what is shown. Unit 8a is list+create only: the mockup's
 * «Править»/«Удалить…» belong to 8b/8c and are deliberately absent.
 *
 * The create page (screen 03c): breadcrumbs «Государства / Новое
 * государство», the «Владелец» card with the player search
 * (suggestions from GET /admin/players?search=&limit=8, the hint
 * «VK ID … · государства нет — можно создать.» or the red «У этого
 * игрока уже есть государство»), the «Основные данные» grid with the
 * same counters and the same colour check the player's form runs
 * (POST /nations/color-check), the two selects (Пол лидера,
 * Преемственность) and the province picker (suggestions from
 * GET /admin/provinces?free_only=true; chips with ✕, the first chip
 * is «★ столица», a click on another chip moves it to the front).
 *
 * POST /admin/nations goes through the unchanged NationService path —
 * a refusal lands next to the field it concerns (the same
 * mapErrorCodeToField the player's wizard uses, plus 'owner' for
 * NATION_ALREADY_EXISTS / PLAYER_NOT_FOUND). On success the shared
 * Notice fires and the view returns to the list. A 401 ends the
 * session through the frame's reportUnauthorized, as everywhere.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminNationDTO,
  AdminPlayerDTO,
  AdminProvinceDTO,
  NationRulesDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { FieldLabel, FieldMessage, TextField } from '../../../shared/ui/fields';
import { FlagStub } from '../../../shared/ui/FlagStub';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { useNotice } from '../../../shared/ui/Notice';
import { useTheme } from '../../../shared/ui/theme';
import {
  FONTS,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import {
  isValidColorHex,
  mapErrorCodeToField,
  normalizeColorHex,
} from '../../../modules/00_core/components/registrationForm';
import { nationColorCheckText } from '../../../modules/00_core/components/nationErrorTexts';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';

const PAGE_SIZE = 50;
/** The search fires on a pause, not on every keystroke. */
const SEARCH_DEBOUNCE_MS = 350;
/** Suggestion lists use the players section's debounce too. */
const SUGGEST_DEBOUNCE_MS = 350;
/** The colour status check's pause — the player's form uses 400 ms. */
const COLOR_CHECK_DEBOUNCE_MS = 400;
/** The owner picker's page size (task: GET /admin/players?limit=8). */
const OWNER_SUGGEST_LIMIT = 8;
const PROVINCE_SUGGEST_LIMIT = 8;

const SEARCH_PLACEHOLDER = 'Поиск по названию';
const OWNER_PLACEHOLDER = 'Поиск…';
const PROVINCE_PLACEHOLDER = 'Поиск…';
const OWNER_CAN_CREATE = 'государства нет — можно создать.';
const OWNER_HAS_NATION = 'У этого игрока уже есть государство';
const HISTORY_HINT =
  'Обязательное поле: так устроено создание государства игроком.';
const CATALOG_HINT =
  'Флаг и портрет — первые из каталога, их можно сменить позже у ' +
  'игрока. Название столицы берётся по первой провинции. Анкета и ' +
  'рассмотрение не нужны.';
const PROVINCES_HINT =
  'Показываются только свободные провинции. Столица — первая в ' +
  'списке; чтобы выбрать другую, нажмите на её название.';

/** The mockup's lowercase labels for the fixed code sets. */
const GENDER_OPTIONS: Record<string, string> = {
  male: 'мужской',
  female: 'женский',
};
const SUCCESSION_OPTIONS: Record<string, string> = {
  elections: 'демократические выборы',
  appointment: 'назначение игроком',
  criteria: 'назначение по критериям',
  inheritance: 'наследование',
};

/** Field keys that show a server refusal — 'owner' is this page's own. */
type FieldKey =
  | 'owner'
  | 'name'
  | 'shortName'
  | 'color'
  | 'motto'
  | 'leaderName'
  | 'leaderTitle'
  | 'gender'
  | 'successionType'
  | 'historyUrl'
  | 'provinces';

type FieldErrors = Partial<Record<FieldKey, string>>;

/** The keys a mapped field may take on this page (for the `in` guard). */
const FIELDS: Record<FieldKey, true> = {
  owner: true,
  name: true,
  shortName: true,
  color: true,
  motto: true,
  leaderName: true,
  leaderTitle: true,
  gender: true,
  successionType: true,
  historyUrl: true,
  provinces: true,
};

/* ---------------------------------------------------------------- */
/* Panel-local building blocks (mockup: .card, .btn, .in, .chip).    */
/* ---------------------------------------------------------------- */

function PanelCard({
  title,
  aside,
  children,
}: {
  /** No title on screen 03's table card — the mockup heads it nothing. */
  title?: string;
  /** Right end of the title row — captions and counters. */
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
      {(title !== undefined || aside !== undefined) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {title !== undefined && (
            <h2
              style={{
                margin: 0,
                ...TEXT_STYLES['heading'],
                color: tokenVar('ink'),
              }}
            >
              {title}
            </h2>
          )}
          <span style={{ flexGrow: 1, minWidth: 0 }} />
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

type PanelButtonKind = 'plain' | 'primary';

function PanelButton({
  kind = 'plain',
  disabled = false,
  onClick,
  children,
  testId,
}: {
  kind?: PanelButtonKind;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const { resolved } = useTheme();
  const onAction = tokenVar(resolved === 'dark' ? 'ground' : 'surface');
  const skin =
    kind === 'primary'
      ? { background: tokenVar('action'), color: onAction, border: 'none' }
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
        height: SIZES['button-h'],
        boxSizing: 'border-box',
        padding: '0 16px',
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

/** The .in frame for a select — same skin as the log section's. */
const controlStyle: CSSProperties = {
  height: SIZES['button-h'],
  boxSizing: 'border-box',
  padding: '0 12px',
  borderRadius: RADII['radius-md'],
  background: tokenVar('surface-inset'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
};

const inputStyle: CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  height: SIZES['button-h'],
  padding: '0 12px',
  borderRadius: RADII['radius-md'],
  background: tokenVar('surface-inset'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
};

/** One option row inside a suggestion dropdown. */
function SuggestionList({
  items,
  onPick,
  optionTestId,
  emptyText = 'Ничего не нашлось.',
}: {
  items: ReactNode[];
  onPick: (index: number) => void;
  optionTestId: (index: number) => string;
  emptyText?: string;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: '100%',
        left: 0,
        right: 0,
        zIndex: 10,
        marginTop: 4,
        background: tokenVar('surface-raised'),
        border: `1px solid ${tokenVar('line')}`,
        borderRadius: RADII['radius-md'],
        overflow: 'hidden',
      }}
    >
      {items.length === 0 ? (
        <div
          style={{
            padding: '8px 12px',
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {emptyText}
        </div>
      ) : (
        items.map((item, index) => (
          <button
            key={index}
            type="button"
            data-testid={optionTestId(index)}
            // mousedown precedes the input's blur, so the pick lands.
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(index);
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
            {item}
          </button>
        ))
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* The nation list (screen 03).                                      */
/* ---------------------------------------------------------------- */

type ListStatus = 'loading' | 'ready' | 'error';

/** The 24×16 catalog flag of a nation cell; a stub when none/unknown. */
function FlagCell({ flagId }: { flagId: string | null }) {
  const [failed, setFailed] = useState(false);
  if (flagId === null || failed) {
    return <FlagStub variant="cell" />;
  }
  return (
    <img
      src={`/assets/nations/flags/${flagId}.png`}
      alt=""
      width={24}
      height={16}
      onError={() => setFailed(true)}
      style={{ display: 'block', borderRadius: RADII['radius-sm'] }}
    />
  );
}

function NationsList({ onCreate }: { onCreate: () => void }) {
  const { token, reportUnauthorized } = useAdminSession();

  const [items, setItems] = useState<AdminNationDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');

  const loadSeq = useRef(0);

  const load = useCallback(
    async (searchText: string, offset: number, append: boolean) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminNations(token, {
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
        <PanelIcon name="flag" accent size={20} />
        Государства
      </h1>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        <div style={{ width: 340 }}>
          <label
            htmlFor="nations-search"
            style={{
              position: 'absolute',
              left: -9999,
              ...TEXT_STYLES['caption'],
            }}
          >
            Поиск
          </label>
          <input
            id="nations-search"
            data-testid="nations-search"
            value={search}
            placeholder={SEARCH_PLACEHOLDER}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={inputStyle}
          />
        </div>
        <span
          data-testid="nations-shown"
          style={{
            flexGrow: 1,
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {status === 'ready' && `Показано ${items.length} из ${total}`}
        </span>
        <PanelButton
          kind="primary"
          testId="nations-create-open"
          onClick={onCreate}
        >
          Создать государство
        </PanelButton>
      </div>

      <PanelCard>
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
                ? 'Государств пока нет.'
                : 'Ничего не нашлось по этому запросу.'
            }
          />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="nations-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['Государство', 'Владелец', 'Провинций', 'Столица'].map(
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
              {items.map((nation, index) => (
                <tr key={nation.id} data-testid="nation-row">
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
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 10,
                      }}
                    >
                      <FlagCell flagId={nation.flag_id} />
                      <span>
                        <span style={{ fontWeight: 500 }}>
                          {nation.short_name}
                        </span>
                        <br />
                        <span
                          style={{
                            ...TEXT_STYLES['caption'],
                            color: tokenVar('ink-muted'),
                          }}
                        >
                          {nation.name}
                        </span>
                      </span>
                    </span>
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
                    {nation.owner_name ?? `VK ${nation.owner_vk_user_id}`}
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
                      ...TEXT_STYLES['figure'],
                    }}
                  >
                    {nation.provinces_count}
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
                    {nation.capital_name ?? '—'}
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
            testId="nations-load-more"
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

/* ---------------------------------------------------------------- */
/* The create page (screen 03c).                                     */
/* ---------------------------------------------------------------- */

interface SelectedProvince {
  id: number;
  name: string;
}

function NationCreate({ onDone }: { onDone: (created: boolean) => void }) {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();

  const [rules, setRules] = useState<NationRulesDTO | null>(null);

  // The owner picker.
  const [owner, setOwner] = useState<AdminPlayerDTO | null>(null);
  const [ownerQuery, setOwnerQuery] = useState('');
  const [ownerSuggestions, setOwnerSuggestions] = useState<AdminPlayerDTO[]>([]);
  const [ownerSugOpen, setOwnerSugOpen] = useState(false);
  const ownerSeq = useRef(0);

  // The form fields.
  const [name, setName] = useState('');
  const [shortName, setShortName] = useState('');
  const [color, setColor] = useState('');
  const [colorStatus, setColorStatus] = useState<
    'OK' | 'TAKEN' | 'TOO_CLOSE' | null
  >(null);
  const [motto, setMotto] = useState('');
  const [leaderName, setLeaderName] = useState('');
  const [leaderTitle, setLeaderTitle] = useState('');
  const [gender, setGender] = useState('');
  const [successionType, setSuccessionType] = useState('');
  const [historyUrl, setHistoryUrl] = useState('');

  // The province picker — ordered chips, the first one is the capital.
  const [provinces, setProvinces] = useState<SelectedProvince[]>([]);
  const [provinceQuery, setProvinceQuery] = useState('');
  const [provinceSuggestions, setProvinceSuggestions] = useState<
    AdminProvinceDTO[]
  >([]);
  const [provinceSugOpen, setProvinceSugOpen] = useState(false);
  const provinceSeq = useRef(0);

  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Field limits arrive once; a failure only means no counters —
  // the server decides on submit anyway.
  useEffect(() => {
    api
      .getNationRules(token)
      .then(setRules)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
        }
      });
  }, [token, reportUnauthorized]);

  /* --- owner suggestions (GET /admin/players?search=&limit=8) --- */
  useEffect(() => {
    if (!ownerSugOpen) {
      return;
    }
    const seq = ++ownerSeq.current;
    const id = setTimeout(() => {
      api
        .adminPlayers(token, {
          search: ownerQuery.trim(),
          limit: OWNER_SUGGEST_LIMIT,
        })
        .then((page) => {
          if (seq === ownerSeq.current) {
            setOwnerSuggestions(page.items);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            reportUnauthorized();
          }
        });
    }, SUGGEST_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [ownerQuery, ownerSugOpen, token, reportUnauthorized]);

  /* --- province suggestions (GET /admin/provinces?free_only=true) --- */
  useEffect(() => {
    if (!provinceSugOpen) {
      return;
    }
    const seq = ++provinceSeq.current;
    const id = setTimeout(() => {
      api
        .adminProvinces(token, {
          search: provinceQuery.trim(),
          free_only: true,
          limit: PROVINCE_SUGGEST_LIMIT,
        })
        .then((page) => {
          if (seq === provinceSeq.current) {
            setProvinceSuggestions(page.items);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            reportUnauthorized();
          }
        });
    }, SUGGEST_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [provinceQuery, provinceSugOpen, token, reportUnauthorized]);

  /* --- the colour status check (POST /nations/color-check) --- */
  const colorSeq = useRef(0);
  useEffect(() => {
    if (!isValidColorHex(color)) {
      setColorStatus(null);
      return;
    }
    const seq = ++colorSeq.current;
    const id = setTimeout(() => {
      api
        .checkNationColor(token, normalizeColorHex(color))
        .then((answer) => {
          if (seq === colorSeq.current) {
            setColorStatus(answer.status);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            reportUnauthorized();
          }
        });
    }, COLOR_CHECK_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [color, token, reportUnauthorized]);

  const clearError = (key: FieldKey) =>
    setFieldErrors((prev) => {
      if (prev[key] === undefined) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });

  const pickOwner = (player: AdminPlayerDTO) => {
    setOwner(player);
    setOwnerQuery(player.display_name ?? `VK ${player.vk_user_id}`);
    setOwnerSugOpen(false);
    clearError('owner');
  };

  const addProvince = (province: AdminProvinceDTO) => {
    setProvinces((prev) => [
      ...prev,
      { id: province.id, name: province.name ?? `Провинция ${province.id}` },
    ]);
    setProvinceQuery('');
    setProvinceSugOpen(false);
    clearError('provinces');
  };

  const removeProvince = (id: number) => {
    setProvinces((prev) => prev.filter((chip) => chip.id !== id));
  };

  /** A click on a chip's name moves it to the front — the capital. */
  const makeCapital = (id: number) => {
    setProvinces((prev) => {
      const chip = prev.find((entry) => entry.id === id);
      if (chip === undefined) {
        return prev;
      }
      return [chip, ...prev.filter((entry) => entry.id !== id)];
    });
  };

  const missing: FieldKey[] = [];
  const empty = (value: string) => value.trim() === '';
  if (owner === null) {
    missing.push('owner');
  }
  if (name.trim().length < (rules?.name_min_length ?? 1)) {
    missing.push('name');
  }
  if (empty(shortName)) {
    missing.push('shortName');
  }
  if (!isValidColorHex(color)) {
    missing.push('color');
  }
  if (empty(leaderName)) {
    missing.push('leaderName');
  }
  if (empty(leaderTitle)) {
    missing.push('leaderTitle');
  }
  if (empty(gender)) {
    missing.push('gender');
  }
  if (empty(successionType)) {
    missing.push('successionType');
  }
  if (empty(historyUrl)) {
    missing.push('historyUrl');
  }
  if (provinces.length === 0) {
    missing.push('provinces');
  }
  const complete = missing.length === 0;

  const submit = async () => {
    if (!complete || busy || owner === null) {
      return;
    }
    setBusy(true);
    setFieldErrors({});
    setGeneralError(null);
    try {
      const created = await api.adminNationCreate(token, {
        owner_vk_user_id: owner.vk_user_id,
        name: name.trim(),
        short_name: shortName.trim(),
        color_hex: normalizeColorHex(color),
        leader_name: leaderName.trim(),
        leader_title: leaderTitle.trim(),
        gender,
        succession_type: successionType,
        history_url: historyUrl.trim(),
        motto: empty(motto) ? null : motto.trim(),
        province_ids: provinces.map((chip) => chip.id),
      });
      notify(`Государство «${created.short_name}» создано.`);
      onDone(true);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      if (error instanceof ApiError) {
        const text =
          error.code === 'NATION_ALREADY_EXISTS'
            ? OWNER_HAS_NATION
            : errorText(error, { rules });
        if (
          error.code === 'NATION_ALREADY_EXISTS' ||
          error.code === 'PLAYER_NOT_FOUND'
        ) {
          setFieldErrors({ owner: text });
        } else {
          // The capital/capital-name codes concern the chips row.
          const mapped = mapErrorCodeToField(error.code);
          const field =
            mapped === 'capitalProvinceId' || mapped === 'capitalName'
              ? 'provinces'
              : mapped;
          if (field !== null && field in FIELDS) {
            setFieldErrors({ [field as FieldKey]: text });
          } else {
            setGeneralError(text);
          }
        }
      } else {
        setGeneralError(errorText(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const genderCodes = rules?.genders ?? Object.keys(GENDER_OPTIONS);
  const successionCodes =
    rules?.succession_types ?? Object.keys(SUCCESSION_OPTIONS);
  const colorHint =
    colorStatus !== null ? nationColorCheckText(colorStatus) : undefined;

  return (
    <>
      {/* Screen 03c breadcrumbs. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          ...TEXT_STYLES['body'],
        }}
      >
        <button
          type="button"
          data-testid="nation-create-back"
          onClick={() => onDone(false)}
          style={{
            border: 'none',
            background: 'transparent',
            padding: 0,
            cursor: 'pointer',
            color: tokenVar('link'),
            ...TEXT_STYLES['body'],
          }}
        >
          Государства
        </button>
        <span style={{ color: tokenVar('ink-muted') }}>/</span>
        <span style={{ fontWeight: 500 }}>Новое государство</span>
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
        Создание государства
      </h1>

      <PanelCard title="Владелец">
        <div style={{ position: 'relative' }}>
          <FieldLabel
            label="Игрок (поиск по имени или VK ID)"
            required
            htmlFor="nation-owner"
          />
          <input
            id="nation-owner"
            data-testid="nation-owner-input"
            value={ownerQuery}
            placeholder={OWNER_PLACEHOLDER}
            onChange={(event) => {
              setOwnerQuery(event.currentTarget.value);
              setOwner(null);
              setOwnerSugOpen(true);
              clearError('owner');
            }}
            onFocus={() => setOwnerSugOpen(true)}
            onBlur={() => setOwnerSugOpen(false)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={{
              ...inputStyle,
              border: `1px solid ${tokenVar(
                fieldErrors.owner ? 'danger' : 'ink-faint',
              )}`,
            }}
          />
          {ownerSugOpen && (
            <SuggestionList
              items={ownerSuggestions.map((player) => (
                <span key={player.vk_user_id}>
                  {player.display_name ?? `VK ${player.vk_user_id}`}
                  {player.display_name !== null && (
                    <span
                      style={{
                        color: tokenVar('ink-muted'),
                        fontFamily: FONTS.mono,
                        fontSize: 12,
                        marginLeft: 8,
                      }}
                    >
                      VK {player.vk_user_id}
                    </span>
                  )}
                  {player.nation_short_name !== null && (
                    <span
                      style={{
                        color: tokenVar('ink-muted'),
                        marginLeft: 8,
                      }}
                    >
                      · {player.nation_short_name}
                    </span>
                  )}
                </span>
              ))}
              onPick={(index) => pickOwner(ownerSuggestions[index])}
              optionTestId={(index) => `owner-option-${index}`}
            />
          )}
        </div>
        {owner !== null && fieldErrors.owner === undefined && (
          <span
            data-testid="nation-owner-hint"
            style={{
              ...TEXT_STYLES['caption'],
              color:
                owner.nation_short_name === null
                  ? tokenVar('ink-muted')
                  : tokenVar('danger'),
            }}
          >
            VK ID{' '}
            <span style={{ fontFamily: FONTS.mono }}>{owner.vk_user_id}</span>
            {owner.nation_short_name === null
              ? ` · ${OWNER_CAN_CREATE}`
              : ` — ${OWNER_HAS_NATION}`}
          </span>
        )}
        <FieldMessage error={fieldErrors.owner} />
      </PanelCard>

      <PanelCard title="Основные данные">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: SPACING['space-3'],
          }}
        >
          <TextField
            id="nf-name"
            testId="nf-name"
            label="Полное название"
            required
            value={name}
            maxLength={rules?.name_max_length}
            error={fieldErrors.name}
            onChange={(value) => {
              setName(value);
              clearError('name');
            }}
          />
          <TextField
            id="nf-short-name"
            testId="nf-short-name"
            label="Краткое название"
            required
            value={shortName}
            maxLength={rules?.short_name_max_length}
            error={fieldErrors.shortName}
            onChange={(value) => {
              setShortName(value);
              clearError('shortName');
            }}
          />
          <div data-testid="nf-color" style={{ minWidth: 0 }}>
            <FieldLabel label="Цвет" required htmlFor="nf-color-input" />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                ...inputStyle,
                padding: 0,
                border: `1px solid ${tokenVar(
                  fieldErrors.color ? 'danger' : 'ink-faint',
                )}`,
              }}
            >
              <input
                id="nf-color-input"
                data-testid="nf-color-input"
                value={color}
                placeholder="#RRGGBB"
                onChange={(event) => {
                  setColor(event.currentTarget.value);
                  clearError('color');
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                  }
                }}
                style={{
                  flexGrow: 1,
                  minWidth: 0,
                  border: 'none',
                  background: 'transparent',
                  color: tokenVar('ink'),
                  height: SIZES['button-h'] - 2,
                  padding: '0 12px',
                  ...TEXT_STYLES['body'],
                }}
              />
              {isValidColorHex(color) && (
                <span
                  aria-hidden="true"
                  style={{
                    flexShrink: 0,
                    width: 24,
                    height: 16,
                    marginRight: 10,
                    borderRadius: RADII['radius-sm'],
                    background: normalizeColorHex(color),
                  }}
                />
              )}
            </div>
            <FieldMessage error={fieldErrors.color} hint={colorHint} />
          </div>
          <TextField
            id="nf-motto"
            testId="nf-motto"
            label="Девиз"
            value={motto}
            maxLength={rules?.motto_max_length}
            error={fieldErrors.motto}
            placeholder="Необязательно"
            onChange={(value) => {
              setMotto(value);
              clearError('motto');
            }}
          />
          <TextField
            id="nf-leader-name"
            testId="nf-leader-name"
            label="Имя лидера"
            required
            value={leaderName}
            maxLength={rules?.leader_name_max_length}
            error={fieldErrors.leaderName}
            onChange={(value) => {
              setLeaderName(value);
              clearError('leaderName');
            }}
          />
          <TextField
            id="nf-leader-title"
            testId="nf-leader-title"
            label="Должность лидера"
            required
            value={leaderTitle}
            maxLength={rules?.leader_title_max_length}
            error={fieldErrors.leaderTitle}
            onChange={(value) => {
              setLeaderTitle(value);
              clearError('leaderTitle');
            }}
          />
          <div data-testid="nf-gender" style={{ minWidth: 0 }}>
            <FieldLabel label="Пол лидера" required htmlFor="nf-gender-input" />
            <select
              id="nf-gender-input"
              data-testid="nf-gender-select"
              value={gender}
              onChange={(event) => {
                setGender(event.currentTarget.value);
                clearError('gender');
              }}
              style={{ ...controlStyle, width: '100%' }}
            >
              <option value="" disabled>
                Выберите…
              </option>
              {genderCodes.map((code) => (
                <option key={code} value={code}>
                  {GENDER_OPTIONS[code] ?? code}
                </option>
              ))}
            </select>
            <FieldMessage error={fieldErrors.gender} />
          </div>
          <div data-testid="nf-succession" style={{ minWidth: 0 }}>
            <FieldLabel
              label="Преемственность"
              required
              htmlFor="nf-succession-input"
            />
            <select
              id="nf-succession-input"
              data-testid="nf-succession-select"
              value={successionType}
              onChange={(event) => {
                setSuccessionType(event.currentTarget.value);
                clearError('successionType');
              }}
              style={{ ...controlStyle, width: '100%' }}
            >
              <option value="" disabled>
                Выберите…
              </option>
              {successionCodes.map((code) => (
                <option key={code} value={code}>
                  {SUCCESSION_OPTIONS[code] ?? code}
                </option>
              ))}
            </select>
            <FieldMessage error={fieldErrors.successionType} />
          </div>
          <TextField
            id="nf-history-url"
            testId="nf-history-url"
            label="Ссылка на историю (статья ВК)"
            required
            value={historyUrl}
            maxLength={rules?.history_url_max_length}
            error={fieldErrors.historyUrl}
            hint={fieldErrors.historyUrl === undefined ? HISTORY_HINT : undefined}
            onChange={(value) => {
              setHistoryUrl(value);
              clearError('historyUrl');
            }}
          />
        </div>
        <FieldMessage hint={CATALOG_HINT} />
      </PanelCard>

      <PanelCard
        title="Провинции"
        aside={
          <span
            data-testid="provinces-chosen"
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
              whiteSpace: 'nowrap',
            }}
          >
            Выбрано: <span style={{ fontFamily: FONTS.mono }}>{provinces.length}</span>
          </span>
        }
      >
        <div style={{ position: 'relative' }}>
          <FieldLabel
            label="Добавить провинцию (поиск по названию)"
            htmlFor="nation-province"
          />
          <input
            id="nation-province"
            data-testid="nation-province-input"
            value={provinceQuery}
            placeholder={PROVINCE_PLACEHOLDER}
            onChange={(event) => {
              setProvinceQuery(event.currentTarget.value);
              setProvinceSugOpen(true);
            }}
            onFocus={() => setProvinceSugOpen(true)}
            onBlur={() => setProvinceSugOpen(false)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={{
              ...inputStyle,
              border: `1px solid ${tokenVar(
                fieldErrors.provinces ? 'danger' : 'ink-faint',
              )}`,
            }}
          />
          {provinceSugOpen && (
            <SuggestionList
              items={provinceSuggestions
                .filter(
                  (province) =>
                    !provinces.some((chip) => chip.id === province.id),
                )
                .map((province) => province.name ?? `#${province.id}`)}
              onPick={(index) => {
                const available = provinceSuggestions.filter(
                  (province) =>
                    !provinces.some((chip) => chip.id === province.id),
                );
                addProvince(available[index]);
              }}
              optionTestId={(index) => `province-option-${index}`}
            />
          )}
        </div>
        {provinces.length > 0 && (
          <div
            data-testid="province-chips"
            style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}
          >
            {provinces.map((chip, index) => (
              <span
                key={chip.id}
                data-testid={`province-chip-${chip.id}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  height: 32,
                  padding: '0 8px',
                  boxSizing: 'border-box',
                  background: tokenVar('surface-inset'),
                  borderRadius: RADII['radius-sm'],
                  color: tokenVar('ink'),
                  ...TEXT_STYLES['body'],
                }}
              >
                <button
                  type="button"
                  data-testid={`province-capital-${chip.id}`}
                  title="Сделать столицей"
                  onClick={() => makeCapital(chip.id)}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    padding: 0,
                    cursor: 'pointer',
                    color: 'inherit',
                    ...TEXT_STYLES['body'],
                  }}
                >
                  {chip.name}
                </button>
                {index === 0 && (
                  <span
                    data-testid="province-capital-mark"
                    style={{
                      ...TEXT_STYLES['caption'],
                      color: tokenVar('ink-muted'),
                    }}
                  >
                    ★ столица
                  </span>
                )}
                <button
                  type="button"
                  data-testid={`province-remove-${chip.id}`}
                  aria-label={`Убрать ${chip.name}`}
                  onClick={() => removeProvince(chip.id)}
                  style={{
                    display: 'inline-flex',
                    border: 'none',
                    background: 'transparent',
                    padding: 0,
                    cursor: 'pointer',
                    color: tokenVar('ink-muted'),
                  }}
                >
                  <svg
                    width={12}
                    height={12}
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.8}
                    strokeLinecap="round"
                    aria-hidden="true"
                  >
                    <path d="M4 4l8 8M12 4l-8 8" />
                  </svg>
                </button>
              </span>
            ))}
          </div>
        )}
        <FieldMessage error={fieldErrors.provinces} hint={PROVINCES_HINT} />
      </PanelCard>

      {generalError !== null && (
        <div
          data-testid="nation-create-error"
          style={{
            ...TEXT_STYLES['body'],
            color: tokenVar('danger'),
          }}
        >
          {generalError}
        </div>
      )}
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          gap: SPACING['space-3'],
        }}
      >
        <PanelButton
          testId="nation-create-cancel"
          onClick={() => onDone(false)}
        >
          Отмена
        </PanelButton>
        <PanelButton
          kind="primary"
          testId="nation-create-submit"
          disabled={!complete || busy}
          onClick={submit}
        >
          Создать государство
        </PanelButton>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- */
/* The section: list ⇄ create.                                       */
/* ---------------------------------------------------------------- */

export function NationsSection() {
  const [view, setView] = useState<'list' | 'create'>('list');
  // Bumping reloadKey after a successful create refreshes the list.
  const [reloadKey, setReloadKey] = useState(0);

  return view === 'list' ? (
    <NationsList key={reloadKey} onCreate={() => setView('create')} />
  ) : (
    <NationCreate
      onDone={(created) => {
        if (created) {
          setReloadKey((key) => key + 1);
        }
        setView('list');
      }}
    />
  );
}
