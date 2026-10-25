/**
 * NationCreate — the «Новое государство» page (0.11.0 unit 8a,
 * mockup screen 03c): breadcrumbs «Государства / Новое государство»,
 * the «Владелец» card with the player search (suggestions from
 * GET /admin/players?search=&limit=8, the hint «VK ID … · государства
 * нет — можно создать.» or the red «У этого игрока уже есть
 * государство»), the «Основные данные» grid with the same counters
 * and the same colour check the player's form runs — since unit 8b
 * through the panel's own POST /admin/nations/color-check — the two
 * selects (Пол лидера, Преемственность) and the province picker
 * (suggestions from GET /admin/provinces?free_only=true; chips with
 * ✕, the first chip is «★ столица», a click on another chip moves
 * it to the front).
 *
 * POST /admin/nations goes through the unchanged NationService path —
 * a refusal lands next to the field it concerns (the same
 * mapErrorCodeToField the player's wizard uses, plus 'owner' for
 * NATION_ALREADY_EXISTS / PLAYER_NOT_FOUND). On success the shared
 * Notice fires and the view returns to the list. A 401 ends the
 * session through the frame's reportUnauthorized, as everywhere.
 * Split out of NationsSection.tsx for unit 8b; behaviour unchanged.
 */

import { useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminPlayerDTO,
  AdminProvinceDTO,
  NationRulesDTO,
} from '../../../shared/types';
import { FieldLabel, FieldMessage, TextField } from '../../../shared/ui/fields';
import { useNotice } from '../../../shared/ui/Notice';
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
import {
  COLOR_CHECK_DEBOUNCE_MS,
  GENDER_OPTIONS,
  OWNER_SUGGEST_LIMIT,
  PROVINCE_SUGGEST_LIMIT,
  PanelButton,
  PanelCard,
  SUCCESSION_OPTIONS,
  SUGGEST_DEBOUNCE_MS,
  SuggestionList,
  controlStyle,
  inputStyle,
} from './shared';

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

interface SelectedProvince {
  id: number;
  name: string;
}

export function NationCreate({
  onDone,
}: {
  onDone: (created: boolean) => void;
}) {
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

  /* --- the colour check (POST /admin/nations/color-check, 8b) --- */
  const colorSeq = useRef(0);
  useEffect(() => {
    if (!isValidColorHex(color)) {
      setColorStatus(null);
      return;
    }
    const seq = ++colorSeq.current;
    const id = setTimeout(() => {
      api
        .adminNationColorCheck(token, {
          color_hex: normalizeColorHex(color),
        })
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
