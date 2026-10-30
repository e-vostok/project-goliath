/**
 * PanelCreateNation — the "no nation yet" screen (UI Spec 9.6 — version
 * 0.9.0 unit 8c): the «СОЗДАНИЕ ГОСУДАРСТВА» window built only from
 * `shared/ui` — a `BlockTitle` with the document icon and «ШАГ N ИЗ 4»
 * at the right of the row, the four-tab strip of `CreateNationTabBar`
 * («Основные данные и символика», «Глава государства», «История»,
 * «Территории»), one `surface`/`radius-lg`/`space-4` block per tab with
 * its own `BlockTitle`, and the buttons row under it: «← Назад» (not on
 * tab 1), «Далее →» — on tab 4 «Основать государство», disabled until
 * `missingRequired` is empty, with the red-dot hint between the
 * buttons.
 *
 * The current tab and every field value live in this container as one
 * `RegistrationForm` object (the anthem field is gone; `anthem_url`
 * is never sent).
 *
 * Provinces are picked on the map — the «Выбрать на карте» button on
 * tab 4 opens the 01_map ProvincePicker popup; the selection lives in
 * `form.provinces` (value = province id, label = display name, order =
 * selection order), the tab renders the names as rows.
 *
 * The form mirrors into the session draft under 'nation-create-v2'
 * once the player touches a field; a successful creation deletes it.
 * Length/host/province-count limits come from `useNationRules` — the
 * server stays the source of truth.
 *
 * Server-side `ErrorResponse.code` values map to inline field errors
 * through `mapErrorCodeToField` + `errorText`; an error or a missing
 * required field marks an inactive tab with a red dot — the window
 * never switches tabs on its own. Anything else surfaces as a generic
 * FormStatus banner.
 *
 * Keyboard rule: there is no `<form>` and no submit-on-Enter — a
 * one-line field swallows Enter, a textarea takes a line break, only
 * the explicit buttons act.
 */

import { useEffect, useRef, useState } from 'react';
import bridge from '@vkontakte/vk-bridge';
import { Button, FormStatus } from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { useFormDraft } from '../../../shared/formDraft';
import { SUCCESS_RU } from '../../../shared/texts/success.ru';
import type { NationDTO } from '../../../shared/types';
import {
  BlockTitle,
  ImageSlot,
  LoadingState,
  pickImageFile,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
  useNotice,
  type ImageSlotKind,
} from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { imageErrorText } from './imageErrorTexts';
import {
  imageUploadLaterBothText,
  imageUploadLaterText,
} from './imageEditor';
import { ImageUploadPreview } from './ImageUploadPreview';
import { isValidColorHex, normalizeColorHex } from './registrationForm';
import { useBotStatus } from '../../02_bot/hooks/useBotStatus';
import { PanelBotGate } from '../../02_bot/components/PanelBotGate';
import {
  fetchBotStatus,
  isConsentRequiredError,
  toBotStatus,
} from '../../02_bot/api';
import {
  nationRulesHints,
  type RegistrationTabProps,
} from './CreateNationFields';
import {
  fieldToTab,
  mapErrorCodeToField,
  missingRequired,
  REGISTRATION_DRAFT_KEY,
  registrationFormFromDraft,
  registrationFormIsEmpty,
  toCreateRequest,
  type ChipOption,
  type NationField,
  type RegistrationForm,
  type RegistrationTab,
} from './registrationForm';
import {
  CreateNationTabBar,
  CREATE_NATION_TABS,
} from './CreateNationTabBar';
import { CreateNationTabSymbols } from './CreateNationTabSymbols';
import { CreateNationTabLeadership } from './CreateNationTabLeadership';
import { CreateNationTabHistory } from './CreateNationTabHistory';
import { CreateNationTabTerritories } from './CreateNationTabTerritories';
import { ProvincePicker } from '../../01_map/components/ProvincePicker';

const sendTaptic = () => {
  void bridge
    .send('VKWebAppTapticImpactOccurred', { style: 'medium' })
    .catch(() => {});
};

export interface PanelCreateNationProps {
  onCreated: (nation: NationDTO) => void;
}

export function PanelCreateNation({ onCreated }: PanelCreateNationProps) {
  const { token } = useSession();
  const notify = useNotice();
  const rulesState = useNationRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;
  const hints = nationRulesHints(rules);
  const bot = useBotStatus();
  const [consentRequired, setConsentRequired] = useState(false);

  // Draft memory: reopening the registration screen restores whatever
  // was typed; a successful creation deletes it (see handleSubmit).
  const {
    draft: storedDraft,
    setDraft: setStoredDraft,
    clearDraft,
  } = useFormDraft<RegistrationForm>(REGISTRATION_DRAFT_KEY);

  const [tab, setTab] = useState<RegistrationTab>(1);
  const [form, setForm] = useState<RegistrationForm>(() =>
    registrationFormFromDraft(storedDraft),
  );
  // A restored draft means the player already edited the form — tab
  // dots for missing required fields show right away.
  const [touched, setTouched] = useState(
    storedDraft !== null &&
      !registrationFormIsEmpty(registrationFormFromDraft(storedDraft)),
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  // Images chosen at registration (0.12.0, Spec «Порядок в окне
  // регистрации»): kept in this window only — a File plus a local
  // object URL for the slot — and sent one by one AFTER the nation
  // exists. Not part of the session draft: a reload loses them.
  const [pendingImages, setPendingImages] = useState<
    Partial<Record<ImageSlotKind, { file: File; url: string }>>
  >({});
  const pendingRef = useRef(pendingImages);
  pendingRef.current = pendingImages;
  useEffect(
    () => () => {
      for (const pending of Object.values(pendingRef.current)) {
        if (pending !== undefined) {
          URL.revokeObjectURL(pending.url);
        }
      }
    },
    [],
  );
  const [imagePick, setImagePick] = useState<{
    kind: ImageSlotKind;
    file: File;
  } | null>(null);
  const storePendingImage = (kind: ImageSlotKind, file: File) => {
    setPendingImages((prev) => {
      const old = prev[kind];
      if (old !== undefined) {
        URL.revokeObjectURL(old.url);
      }
      return { ...prev, [kind]: { file, url: URL.createObjectURL(file) } };
    });
  };
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<NationField, string>>
  >({});
  const [formError, setFormError] = useState<string | null>(null);

  const clearFieldError = (field: NationField) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });

  const onFieldChange: RegistrationTabProps['onFieldChange'] = (
    field,
    value,
  ) => {
    setTouched(true);
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'provinces') {
        // INV-14: the capital must stay among the chosen ids — a row
        // removal that takes the capital away drops the mark.
        const chips = next.provinces;
        next.capitalProvinceId =
          prev.capitalProvinceId !== null &&
          chips.some((chip) => chip.value === prev.capitalProvinceId)
            ? prev.capitalProvinceId
            : null;
        // Until a manual edit the capital name follows the effective
        // capital (the marked row, else the first selected one).
        if (!prev.capitalNameEdited) {
          const effective = next.capitalProvinceId ?? chips[0]?.value ?? null;
          next.capitalName =
            chips.find((chip) => chip.value === effective)?.label ?? '';
        }
      } else if (field === 'capitalProvinceId') {
        // «Сделать столицей» moves the mark — until a manual edit the
        // capital name follows the new effective capital.
        if (!prev.capitalNameEdited) {
          const effective =
            next.capitalProvinceId ?? next.provinces[0]?.value ?? null;
          next.capitalName =
            next.provinces.find((chip) => chip.value === effective)?.label ??
            '';
        }
      } else if (field === 'capitalName') {
        // A hand-typed name is never auto-overwritten again.
        next.capitalNameEdited = true;
      }
      return next;
    });
    clearFieldError(field);
    if (field === 'provinces') {
      clearFieldError('capitalProvinceId');
    }
  };

  // Tab dots: a server error on a field of that tab, or — once any
  // field was edited — a required field of that tab still missing.
  const missing = missingRequired(form, rules);
  const tabMarks: Record<RegistrationTab, boolean> = {
    1: false,
    2: false,
    3: false,
    4: false,
  };
  for (const field of Object.keys(fieldErrors) as NationField[]) {
    tabMarks[fieldToTab(field)] = true;
  }
  if (touched) {
    for (const field of missing) {
      tabMarks[fieldToTab(field)] = true;
    }
  }

  // Mirror the form into the session draft — only once the player
  // edited it; a form back to pristine drops the entry.
  useEffect(() => {
    if (!touched || registrationFormIsEmpty(form)) {
      clearDraft();
    } else {
      setStoredDraft(form);
    }
  }, [touched, form, setStoredDraft, clearDraft]);

  const canSubmit = missing.length === 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);

    try {
      const nation = await api.createNation(token, toCreateRequest(form));
      // The nation exists — now the pending pictures go one by one:
      // flag first, then the portrait. A failed upload never cancels
      // the registration (Spec «Порядок в окне регистрации»). The
      // notice slot shows ONE message, so failures collapse into one
      // danger notice: one failure — reason + the «в «Штабе»» tail;
      // both — both reasons + the shared both-failed tail.
      const failedImages: Partial<Record<ImageSlotKind, string>> = {};
      for (const kind of ['flag', 'portrait'] as const) {
        const pending = pendingImages[kind];
        if (pending === undefined) {
          continue;
        }
        try {
          await api.uploadNationImage(token, kind, pending.file);
        } catch (uploadError) {
          failedImages[kind] = imageErrorText(uploadError, kind, rules);
        }
      }
      sendTaptic();
      clearDraft();
      const flagReason = failedImages.flag;
      const portraitReason = failedImages.portrait;
      if (flagReason !== undefined && portraitReason !== undefined) {
        notify(
          `${flagReason} ${portraitReason} ${imageUploadLaterBothText}`,
          { tone: 'danger' },
        );
      } else if (flagReason !== undefined) {
        notify(`${flagReason} ${imageUploadLaterText('flag')}`, {
          tone: 'danger',
        });
      } else if (portraitReason !== undefined) {
        notify(`${portraitReason} ${imageUploadLaterText('portrait')}`, {
          tone: 'danger',
        });
      } else {
        notify(SUCCESS_RU.nationCreated);
      }
      onCreated(nation);
    } catch (error) {
      if (isConsentRequiredError(error)) {
        // The server enforced consent although the gate let the player
        // through (stale/failed status) — return to the gate; the form
        // values stay untouched in this container's state.
        setConsentRequired(true);
        try {
          const fresh =
            bot.state.status === 'ready'
              ? bot.state.dto
              : await fetchBotStatus(token);
          // The server just denied — treat consent as not allowed even
          // if the status snapshot still says ALLOWED.
          const next =
            fresh.consent === 'ALLOWED'
              ? { ...fresh, consent: 'UNKNOWN' as const }
              : fresh;
          if (toBotStatus(next).status === 'ready') {
            bot.update(next);
          } else {
            // No usable status (bot off / malformed) — keep the
            // pre-Issue behavior: a generic banner on the form.
            setConsentRequired(false);
            setFormError(errorText(error));
          }
        } catch {
          setConsentRequired(false);
          setFormError(errorText(error));
        }
      } else if (error instanceof ApiError) {
        const field = mapErrorCodeToField(error.code);
        if (field) {
          setFieldErrors({
            [field]: errorText(error, { rules }),
          });
        } else {
          setFormError(errorText(error));
        }
      } else {
        setFormError(errorText(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const onPickerDone = (
    ids: number[],
    names: Map<number, string>,
    capitalId: number | null,
  ) => {
    setTouched(true);
    setForm((prev) => {
      const provinces = ids.map(
        (id): ChipOption => ({
          value: id,
          label: names.get(id) ?? String(id),
        }),
      );
      // INV-14: the mark must be among the chosen ids (the picker
      // already guarantees it; re-validated here defensively).
      const marked =
        capitalId !== null && ids.includes(capitalId) ? capitalId : null;
      const next = { ...prev, provinces, capitalProvinceId: marked };
      // The capital name follows the effective capital until the
      // player edited the field by hand (capitalNameEdited).
      if (!prev.capitalNameEdited) {
        const effective = marked ?? ids[0] ?? null;
        next.capitalName =
          effective === null ? '' : (names.get(effective) ?? '');
      }
      return next;
    });
    clearFieldError('provinces');
    clearFieldError('capitalProvinceId');
    setPickerOpen(false);
  };

  // Spec 5.6 + INV-B15: the consent gate stands before the form only when
  // a good status explicitly requires consent. Failed requests and the
  // stale+UNKNOWN combination fall through to the form (fail-open); an
  // explicit 403 CONSENT_REQUIRED bypasses the stale exemption — the
  // server's refusal is definitive.
  const botDto = bot.state.status === 'ready' ? bot.state.dto : null;
  const showGate =
    botDto !== null &&
    botDto.registration_requires_consent &&
    botDto.consent !== 'ALLOWED' &&
    !(botDto.stale && botDto.consent === 'UNKNOWN' && !consentRequired);

  if (bot.state.status === 'loading') {
    // First status request in flight — the container's loading state;
    // the form must not flash before the gate decision is known.
    return <LoadingState height={400} />;
  }

  if (showGate && botDto !== null) {
    return (
      <PanelBotGate
        dto={botDto}
        onAllowed={bot.update}
        onDisabled={() => bot.update({ ...botDto, enabled: false })}
      />
    );
  }

  const tabProps: RegistrationTabProps = {
    form,
    rules,
    hints,
    errors: fieldErrors,
    onFieldChange,
  };
  const active = CREATE_NATION_TABS[tab - 1];

  return (
    <div
      data-testid="panel-create-nation"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-3'],
        padding: SPACING['space-4'],
        boxSizing: 'border-box',
        maxWidth: SIZES['win-screen'],
      }}
    >
      <BlockTitle
        icon="document"
        title="Создание государства"
        line={false}
        trailing={
          <span
            data-testid="step-indicator"
            style={{
              marginLeft: 'auto',
              ...TEXT_STYLES['figure'],
              color: tokenVar('ink-muted'),
            }}
          >
            Шаг {tab} из 4
          </span>
        }
      />
      <CreateNationTabBar tab={tab} onTabChange={setTab} tabMarks={tabMarks} />

      {formError && (
        <FormStatus mode="error" title="Не удалось создать государство">
          {formError}
        </FormStatus>
      )}

      <section
        data-testid="create-nation-form"
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: SPACING['space-4'],
        }}
      >
        <BlockTitle icon={active.icon} title={active.title} />
        {tab === 1 && (
          <CreateNationTabSymbols
            {...tabProps}
            imageSlot={
              <ImageSlot
                kind="flag"
                size="registration"
                src={pendingImages.flag?.url ?? null}
                stubColor={
                  isValidColorHex(form.color)
                    ? normalizeColorHex(form.color)
                    : undefined
                }
                alt="Флаг государства"
                interactive
                rules={rules}
                onPick={(file) => setImagePick({ kind: 'flag', file })}
              />
            }
          />
        )}
        {tab === 2 && (
          <CreateNationTabLeadership
            {...tabProps}
            imageSlot={
              <ImageSlot
                kind="portrait"
                size="registration"
                src={pendingImages.portrait?.url ?? null}
                alt="Портрет лидера"
                interactive
                rules={rules}
                onPick={(file) => setImagePick({ kind: 'portrait', file })}
              />
            }
          />
        )}
        {tab === 3 && <CreateNationTabHistory {...tabProps} />}
        {tab === 4 && (
          <CreateNationTabTerritories
            {...tabProps}
            onOpenPicker={() => setPickerOpen(true)}
          />
        )}
      </section>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        {tab > 1 && (
          <Button
            type="button"
            mode="secondary"
            size="m"
            data-testid="step-prev"
            onClick={() => setTab((tab - 1) as RegistrationTab)}
          >
            ← Назад
          </Button>
        )}
        <span
          style={{
            flex: '1 1 auto',
            textAlign: 'center',
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {tab === 4 && missing.length > 0
            ? 'Заполните обязательные поля (отмечены *) на вкладках с красной точкой'
            : ''}
        </span>
        {tab < 4 ? (
          <Button
            type="button"
            size="m"
            data-testid="step-next"
            onClick={() => setTab((tab + 1) as RegistrationTab)}
          >
            Далее →
          </Button>
        ) : (
          <Button
            type="button"
            size="m"
            disabled={!canSubmit}
            loading={submitting}
            onClick={() => void handleSubmit()}
          >
            Основать государство
          </Button>
        )}
      </div>

      {imagePick !== null && (
        <ImageUploadPreview
          key={`${imagePick.kind}:${imagePick.file.name}:${imagePick.file.size}:${imagePick.file.lastModified}`}
          kind={imagePick.kind}
          mode="register"
          file={imagePick.file}
          rules={rules}
          onConfirm={async (file) => {
            // Nothing is sent here — the file only lands in the
            // window state (Spec: stored until the nation exists).
            storePendingImage(imagePick.kind, file);
            setImagePick(null);
          }}
          // «Выбрать другой файл» opens the chooser right away; a pick
          // replaces the file in the SAME window (the key remounts the
          // preview — fresh decode, error state reset), a cancel keeps it.
          onPickAnother={() =>
            pickImageFile((file) =>
              setImagePick({ kind: imagePick.kind, file }),
            )
          }
          onClose={() => setImagePick(null)}
        />
      )}
      {pickerOpen && (
        <ProvincePicker
          initialSelectedIds={form.provinces.map((chip) => chip.value)}
          initialCapitalId={form.capitalProvinceId}
          limits={{
            min: rules?.min_provinces ?? null,
            max: rules?.max_provinces ?? null,
          }}
          onDone={onPickerDone}
          onCancel={() => setPickerOpen(false)}
        />
      )}
    </div>
  );
}
