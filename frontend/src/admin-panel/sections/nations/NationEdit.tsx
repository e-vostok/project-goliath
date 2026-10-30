/**
 * NationEdit — the «Правка государства» page (0.11.0 unit 8b,
 * mockup screen 03b): breadcrumbs «Государства / <краткое
 * название>», one card with the ten-field grid (Полное название,
 * Краткое название, Цвет, Девиз, Имя лидера, Должность лидера,
 * Пол лидера, Преемственность, Столица, Ссылка на историю), the
 * two text areas (Описание, Биография лидера), the info note
 * «Здесь меняются только текстовые данные…» and the
 * Отмена/Сохранить row.
 *
 * The colour field re-checks through the panel's own
 * POST /admin/nations/color-check with nation_id — an unchanged
 * colour sends nothing. «Столица» is disabled for a nation without
 * a capital province. PATCH /admin/nations/{id} carries only the
 * changed fields (nationEdit.ts's own diff helper); a refusal lands
 * next to the field it concerns, a 401 ends the session through
 * the frame, and a success fires the shared Notice and returns to
 * the list.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminNationDTO,
  AdminNationDetailDTO,
  NationRulesDTO,
} from '../../../shared/types';
import { ErrorState } from '../../../shared/ui/ErrorState';
import {
  FieldLabel,
  FieldMessage,
  TextArea,
  TextField,
} from '../../../shared/ui/fields';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { useNotice } from '../../../shared/ui/Notice';
import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import {
  isValidColorHex,
  normalizeColorHex,
} from '../../../modules/00_core/components/registrationForm';
import { nationColorCheckText } from '../../../modules/00_core/components/nationErrorTexts';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';
import {
  COLOR_CHECK_DEBOUNCE_MS,
  GENDER_OPTIONS,
  PanelButton,
  PanelCard,
  SUCCESSION_OPTIONS,
  controlStyle,
  inputStyle,
} from './shared';
import {
  editFieldForError,
  formFromNation,
  toAdminUpdateRequest,
} from './nationEditForm';
import type { EditFieldKey, NationEditForm } from './nationEditForm';
import { NationImagesBlock } from './NationImagesBlock';

const COLOR_HINT =
  'Должен заметно отличаться от цветов других государств.';
const CAPITAL_HINT =
  'Название столицы — только текст; сами провинции здесь не меняются.';
const CAPITAL_NO_PROVINCE =
  'У этого государства нет столичной провинции — название столицы ' +
  'менять нельзя.';
const HISTORY_HINT = 'Статья ВК.';

type LoadStatus = 'loading' | 'ready' | 'error';

export function NationEdit({
  nation,
  onDone,
}: {
  /** The list row — id for the calls, short_name for the breadcrumb. */
  nation: AdminNationDTO;
  onDone: (saved: boolean) => void;
}) {
  const { token, reportUnauthorized } = useAdminSession();

  const [status, setStatus] = useState<LoadStatus>('loading');
  const [detail, setDetail] = useState<AdminNationDetailDTO | null>(null);
  const [rules, setRules] = useState<NationRulesDTO | null>(null);
  const loadSeq = useRef(0);

  const load = useCallback(() => {
    const seq = ++loadSeq.current;
    setStatus('loading');
    Promise.all([
      api.adminNation(token, nation.id),
      // Counters degrade silently when the rules call fails —
      // the server decides on submit anyway.
      api.getNationRules(token).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
        }
        return null;
      }),
    ])
      .then(([nationDetail, nationRules]) => {
        if (seq !== loadSeq.current) {
          return;
        }
        setDetail(nationDetail);
        setRules(nationRules);
        setStatus('ready');
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq === loadSeq.current) {
          setStatus('error');
        }
      });
  }, [token, nation.id, reportUnauthorized]);

  useEffect(load, [load]);

  return (
    <>
      {/* Screen 03b breadcrumbs. */}
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
          data-testid="nation-edit-back"
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
        <span style={{ fontWeight: 500 }}>{nation.short_name}</span>
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
        Правка государства
      </h1>

      {status === 'loading' && <LoadingState height={200} />}
      {status === 'error' && <ErrorState onRetry={load} />}
      {status === 'ready' && detail !== null && (
        <NationEditForm
          nation={detail}
          rules={rules}
          onDone={onDone}
        />
      )}
    </>
  );
}

type FieldErrors = Partial<Record<EditFieldKey, string>>;

function NationEditForm({
  nation,
  rules,
  onDone,
}: {
  nation: AdminNationDetailDTO;
  rules: NationRulesDTO | null;
  onDone: (saved: boolean) => void;
}) {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();

  const [form, setForm] = useState<NationEditForm>(() =>
    formFromNation(nation),
  );
  // The «Картинки государства» block's own state — deleting a picture
  // must never touch the (possibly unsaved) text form.
  const [images, setImages] = useState(() => nation.images);
  const [colorStatus, setColorStatus] = useState<
    'OK' | 'TAKEN' | 'TOO_CLOSE' | null
  >(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: EditFieldKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFieldErrors((prev) => {
      if (prev[key] === undefined) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  /* --- the colour check on change (POST /admin/nations/color-check) ---
     An unchanged colour sends nothing — the nation's own colour is
     always acceptable to it. */
  const colorSeq = useRef(0);
  const colorChanged =
    normalizeColorHex(form.color) !== nation.color_hex.toUpperCase();
  useEffect(() => {
    if (!colorChanged || !isValidColorHex(form.color)) {
      setColorStatus(null);
      return;
    }
    const seq = ++colorSeq.current;
    const id = setTimeout(() => {
      api
        .adminNationColorCheck(token, {
          color_hex: normalizeColorHex(form.color),
          nation_id: nation.id,
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
  }, [form.color, colorChanged, token, nation.id, reportUnauthorized]);

  const patch = toAdminUpdateRequest(form, nation);
  const dirty = Object.keys(patch).length > 0;
  const invalidChange =
    patch.color_hex !== undefined && !isValidColorHex(form.color);

  const submit = async () => {
    if (!dirty || invalidChange || busy) {
      return;
    }
    setBusy(true);
    setFieldErrors({});
    setGeneralError(null);
    try {
      const updated = await api.adminNationUpdate(token, nation.id, patch);
      setImages(updated.images);
      notify(`Данные государства «${updated.short_name}» сохранены.`);
      onDone(true);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      if (error instanceof ApiError) {
        const text = errorText(error, { rules });
        const field =
          error.code === null ? null : editFieldForError(error.code);
        if (field !== null) {
          setFieldErrors({ [field]: text });
        } else {
          setGeneralError(text);
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
    colorStatus !== null ? nationColorCheckText(colorStatus) : COLOR_HINT;
  const noCapital = nation.capital_province_id === null;

  return (
    <>
      {/* Screen 18: the «Картинки государства» card above the form. */}
      <NationImagesBlock
        nationId={nation.id}
        shortName={nation.short_name}
        colorHex={nation.color_hex}
        images={images}
        onImagesChanged={setImages}
      />
      <PanelCard>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: SPACING['space-3'],
          }}
        >
          <TextField
            id="ef-name"
            testId="ef-name"
            label="Полное название"
            value={form.name}
            maxLength={rules?.name_max_length}
            error={fieldErrors.name}
            onChange={(value) => set('name', value)}
          />
          <TextField
            id="ef-short-name"
            testId="ef-short-name"
            label="Краткое название"
            value={form.shortName}
            maxLength={rules?.short_name_max_length}
            error={fieldErrors.shortName}
            onChange={(value) => set('shortName', value)}
          />
          <div data-testid="ef-color" style={{ minWidth: 0 }}>
            <FieldLabel label="Цвет" htmlFor="ef-color-input" />
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
                id="ef-color-input"
                data-testid="ef-color-input"
                value={form.color}
                placeholder="#RRGGBB"
                onChange={(event) => set('color', event.currentTarget.value)}
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
              {isValidColorHex(form.color) && (
                <span
                  aria-hidden="true"
                  style={{
                    flexShrink: 0,
                    width: 24,
                    height: 16,
                    marginRight: 10,
                    borderRadius: RADII['radius-sm'],
                    background: normalizeColorHex(form.color),
                  }}
                />
              )}
            </div>
            <FieldMessage error={fieldErrors.color} hint={colorHint} />
          </div>
          <TextField
            id="ef-motto"
            testId="ef-motto"
            label="Девиз"
            value={form.motto}
            maxLength={rules?.motto_max_length}
            error={fieldErrors.motto}
            onChange={(value) => set('motto', value)}
          />
          <TextField
            id="ef-leader-name"
            testId="ef-leader-name"
            label="Имя лидера"
            value={form.leaderName}
            maxLength={rules?.leader_name_max_length}
            error={fieldErrors.leaderName}
            onChange={(value) => set('leaderName', value)}
          />
          <TextField
            id="ef-leader-title"
            testId="ef-leader-title"
            label="Должность лидера"
            value={form.leaderTitle}
            maxLength={rules?.leader_title_max_length}
            error={fieldErrors.leaderTitle}
            onChange={(value) => set('leaderTitle', value)}
          />
          <div data-testid="ef-gender" style={{ minWidth: 0 }}>
            <FieldLabel label="Пол лидера" htmlFor="ef-gender-select" />
            <select
              id="ef-gender-select"
              data-testid="ef-gender-select"
              value={form.gender}
              onChange={(event) => set('gender', event.currentTarget.value)}
              style={{ ...controlStyle, width: '100%' }}
            >
              {genderCodes.map((code) => (
                <option key={code} value={code}>
                  {GENDER_OPTIONS[code] ?? code}
                </option>
              ))}
            </select>
            <FieldMessage error={fieldErrors.gender} />
          </div>
          <div data-testid="ef-succession" style={{ minWidth: 0 }}>
            <FieldLabel
              label="Преемственность"
              htmlFor="ef-succession-select"
            />
            <select
              id="ef-succession-select"
              data-testid="ef-succession-select"
              value={form.successionType}
              onChange={(event) =>
                set('successionType', event.currentTarget.value)
              }
              style={{ ...controlStyle, width: '100%' }}
            >
              {successionCodes.map((code) => (
                <option key={code} value={code}>
                  {SUCCESSION_OPTIONS[code] ?? code}
                </option>
              ))}
            </select>
            <FieldMessage error={fieldErrors.successionType} />
          </div>
          <div data-testid="ef-capital" style={{ minWidth: 0 }}>
            <FieldLabel label="Столица" htmlFor="ef-capital-input" />
            <input
              id="ef-capital-input"
              data-testid="ef-capital-input"
              value={form.capitalName}
              disabled={noCapital}
              maxLength={rules?.capital_name_max_length}
              onChange={(event) => set('capitalName', event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                }
              }}
              style={{
                ...inputStyle,
                opacity: noCapital ? 0.5 : 1,
                border: `1px solid ${tokenVar(
                  fieldErrors.capitalName ? 'danger' : 'ink-faint',
                )}`,
              }}
            />
            <FieldMessage
              error={fieldErrors.capitalName}
              hint={noCapital ? CAPITAL_NO_PROVINCE : CAPITAL_HINT}
            />
          </div>
          <TextField
            id="ef-history-url"
            testId="ef-history-url"
            label="Ссылка на историю"
            value={form.historyUrl}
            maxLength={rules?.history_url_max_length}
            error={fieldErrors.historyUrl}
            hint={
              fieldErrors.historyUrl === undefined ? HISTORY_HINT : undefined
            }
            onChange={(value) => set('historyUrl', value)}
          />
        </div>

        <TextArea
          id="ef-description"
          testId="ef-description"
          label="Описание"
          value={form.description}
          maxLength={rules?.description_max_length}
          error={fieldErrors.description}
          rows={2}
          onChange={(value) => set('description', value)}
        />
        <TextArea
          id="ef-leader-bio"
          testId="ef-leader-bio"
          label="Биография лидера"
          value={form.leaderBio}
          maxLength={rules?.leader_bio_max_length}
          error={fieldErrors.leaderBio}
          rows={3}
          onChange={(value) => set('leaderBio', value)}
        />

        {/* The mockup's .info note. */}
        <div
          data-testid="ef-info-note"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          <span style={{ fontWeight: 500, color: tokenVar('ink') }}>
            Здесь меняются только текстовые данные.
          </span>{' '}
          Провинции передаются и выводятся в разделе «Провинции», флаг и
          портрет не меняются.
        </div>
      </PanelCard>

      {generalError !== null && (
        <div
          data-testid="nation-edit-error"
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
          testId="nation-edit-cancel"
          onClick={() => onDone(false)}
        >
          Отмена
        </PanelButton>
        <PanelButton
          kind="primary"
          testId="nation-edit-submit"
          disabled={!dirty || invalidChange || busy}
          onClick={submit}
        >
          Сохранить
        </PanelButton>
      </div>
    </>
  );
}
