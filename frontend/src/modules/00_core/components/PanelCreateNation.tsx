/**
 * PanelCreateNation — the "no nation yet" screen (UI Spec 9.6 — version
 * 0.9.0 unit 8c): the «СОЗДАНИЕ ГОСУДАРСТВА» window built only from
 * `shared/ui` — a `BlockTitle` with the document icon and «ШАГ N ИЗ 4»
 * at the right of the row, the four-tab strip of `CreateNationTabBar`
 * («Основные данные и символика», «Глава государства», «История»,
 * «Территории»), one `surface`/`radius-lg`/`space-4` block per tab with
 * its own `BlockTitle`, and the buttons row under it: «← Назад» (not on
 * tab 1), «Далее →» — on tab 4 «Отправить анкету», disabled until
 * `missingRequired` is empty, with the red-dot hint or the review note
 * between the buttons.
 *
 * «Отправить анкету» (Spec applications §10, 0.13.0 unit 7a) runs the
 * sequence: PUT /applications/me (draft) → the chosen pictures onto
 * the draft → POST /applications/me/submit. A failure at any step
 * keeps the draft, shows the error at its own tab and the same button
 * repeats the whole sequence. A server DRAFT (returned / cancelled /
 * plain) fills the form and shows its plate above the tabs.
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
import { ErrorCodes } from '../../../shared/types';
import type { ApplicationDTO } from '../../../shared/types';
import {
  BlockTitle,
  FieldMessage,
  ImageSlot,
  LoadingState,
  pickImageFile,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
  type ImageSlotKind,
} from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { imageErrorText } from './imageErrorTexts';
import { ImageUploadPreview } from './ImageUploadPreview';
import {
  applicationReviewHoursText,
  isValidColorHex,
  normalizeColorHex,
  registrationFormFromApplication,
} from './registrationForm';
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
  /**
   * The server's DRAFT application (Spec applications §10): fills the
   * form — it wins over the session draft — and its `draft_reason`
   * shows the returned/cancelled plate above the tabs.
   */
  draft?: ApplicationDTO | null;
  onSubmitted: (application: ApplicationDTO) => void;
  /**
   * Called when a request answers 409 APPLICATION_NOT_EDITABLE — the
   * application went PENDING elsewhere (audit of PR 267): the shell
   * refetches and moves to «Анкета» instead of a banner.
   */
  onRefresh?: () => void;
}

export function PanelCreateNation({
  draft,
  onSubmitted,
  onRefresh,
}: PanelCreateNationProps) {
  const { token } = useSession();
  const rulesState = useNationRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;
  const hints = nationRulesHints(rules);
  const bot = useBotStatus();
  const [consentRequired, setConsentRequired] = useState(false);

  // Draft memory: reopening the registration screen restores whatever
  // was typed; a successful submission deletes it (see handleSubmit).
  // A server DRAFT wins over the session copy (Spec §10).
  const {
    draft: storedDraft,
    setDraft: setStoredDraft,
    clearDraft,
  } = useFormDraft<RegistrationForm>(REGISTRATION_DRAFT_KEY);

  const [tab, setTab] = useState<RegistrationTab>(1);
  const [form, setForm] = useState<RegistrationForm>(() =>
    draft !== undefined && draft !== null
      ? registrationFormFromApplication(draft)
      : registrationFormFromDraft(storedDraft),
  );
  // A restored draft means the player already edited the form — tab
  // dots for missing required fields show right away.
  const [touched, setTouched] = useState(
    draft !== undefined && draft !== null
      ? !registrationFormIsEmpty(registrationFormFromApplication(draft))
      : storedDraft !== null &&
          !registrationFormIsEmpty(
            registrationFormFromDraft(storedDraft),
          ),
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  // Images chosen at registration (0.12.0, Spec «Порядок в окне
  // регистрации»): kept in this window only — a File plus a local
  // object URL for the slot — and uploaded onto the saved draft one
  // by one before the submit (Spec applications §10). Not part of the
  // session draft: a reload loses the files, never the uploaded ones.
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
    setImageErrors((prev) => {
      if (!(kind in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[kind];
      return next;
    });
  };
  const [submitting, setSubmitting] = useState(false);
  // A failed draft upload marks its own tab (flag → 1, portrait → 2)
  // and waits under the slot — the draft stays on the server.
  const [imageErrors, setImageErrors] = useState<
    Partial<Record<ImageSlotKind, string>>
  >({});
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
  if (imageErrors.flag !== undefined) {
    tabMarks[1] = true;
  }
  if (imageErrors.portrait !== undefined) {
    tabMarks[2] = true;
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
    setImageErrors({});
    setFormError(null);

    // The consent gate + field error mapping, shared by the draft
    // save and the submit — the server enforces either at any stage
    // (the submit runs the consent check too).
    const fail = async (error: unknown) => {
      if (
        error instanceof ApiError &&
        error.code === ErrorCodes.APPLICATION_NOT_EDITABLE
      ) {
        // The application went PENDING elsewhere — the shell refetches
        // and moves to «Анкета» instead of a banner (audit of PR 267).
        onRefresh?.();
        return;
      }
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
    };

    try {
      // Spec §10: save the draft, upload the chosen pictures onto it,
      // then submit. A failure at any step keeps the draft, shows the
      // error at its own tab and the same button repeats the sequence.
      await api.putApplication(token, toCreateRequest(form));

      let uploadFailed = false;
      for (const kind of ['flag', 'portrait'] as const) {
        const pending = pendingImages[kind];
        if (pending === undefined) {
          continue;
        }
        try {
          await api.uploadApplicationImage(token, kind, pending.file);
        } catch (uploadError) {
          if (
            uploadError instanceof ApiError &&
            uploadError.code === ErrorCodes.APPLICATION_NOT_EDITABLE
          ) {
            await fail(uploadError);
            return;
          }
          uploadFailed = true;
          setImageErrors((prev) => ({
            ...prev,
            [kind]: imageErrorText(uploadError, kind, rules),
          }));
        }
      }
      if (uploadFailed) {
        return;
      }

      const submitted = await api.submitApplication(token);
      sendTaptic();
      clearDraft();
      onSubmitted(submitted);
    } catch (error) {
      await fail(error);
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

      {draft?.draft_reason === 'returned' ||
      draft?.draft_reason === 'failed' ? (
        <section
          data-testid="application-returned-plate"
          style={{
            background: tokenVar('warning-bg'),
            borderRadius: RADII['radius-lg'],
            padding: '12px 16px',
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
          }}
        >
          <svg
            width={20}
            height={20}
            viewBox="0 0 16 16"
            fill="none"
            stroke={tokenVar('signal-ink')}
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            style={{ display: 'block', flexShrink: 0, marginTop: 1 }}
          >
            <path d="M8 2.2L14.2 13H1.8z" />
            <path d="M8 6.4v3" />
            <circle cx="8" cy="11.4" r="0.4" fill={tokenVar('signal-ink')} />
          </svg>
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                ...TEXT_STYLES['body'],
                fontWeight: 600,
                color: tokenVar('ink'),
              }}
            >
              {draft.draft_reason === 'returned'
                ? 'Анкета возвращена администратором'
                : 'Анкета возвращена'}
            </div>
            {draft.return_comment !== null &&
              draft.return_comment !== '' && (
                <div
                  style={{
                    ...TEXT_STYLES['body'],
                    color: tokenVar('ink'),
                    marginTop: 2,
                  }}
                >
                  «{draft.return_comment}»
                </div>
              )}
            <div
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('ink-muted'),
                marginTop: 4,
              }}
            >
              Исправьте анкету и отправьте снова: провинции, цвет и
              названия закрепятся заново{' '}
              {applicationReviewHoursText(rules?.application.review_hours)}.
            </div>
          </div>
        </section>
      ) : draft?.draft_reason === 'cancelled' ? (
        <section
          data-testid="application-cancelled-plate"
          style={{
            background: tokenVar('surface'),
            border: `1px solid ${tokenVar('line')}`,
            borderRadius: RADII['radius-lg'],
            padding: '12px 16px',
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
          }}
        >
          <span
            aria-hidden="true"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 24,
              height: 24,
              flexShrink: 0,
              borderRadius: RADII['radius-md'],
              background: tokenVar('surface-inset'),
            }}
          >
            <svg
              width={14}
              height={14}
              viewBox="0 0 16 16"
              fill="none"
              stroke={tokenVar('signal-ink')}
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              style={{ display: 'block' }}
            >
              <path d="M3 7a5 5 0 1 0 1.4-3.4L3 5" />
              <path d="M3 2v3h3" />
            </svg>
          </span>
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                ...TEXT_STYLES['body'],
                fontWeight: 600,
                color: tokenVar('ink'),
              }}
            >
              Вы отменили анкету
            </div>
            <div
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('ink-muted'),
                marginTop: 2,
              }}
            >
              Все данные сохранены. Исправьте их и отправьте анкету
              снова — провинции, цвет и названия закрепятся заново{' '}
              {applicationReviewHoursText(rules?.application.review_hours)}.
            </div>
          </div>
        </section>
      ) : null}

      <CreateNationTabBar tab={tab} onTabChange={setTab} tabMarks={tabMarks} />

      {formError && (
        <FormStatus mode="error" title="Не удалось отправить анкету">
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
              <>
                <ImageSlot
                  kind="flag"
                  size="registration"
                  src={
                    pendingImages.flag?.url ??
                    draft?.images.flag?.url ??
                    null
                  }
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
                <FieldMessage error={imageErrors.flag} />
              </>
            }
          />
        )}
        {tab === 2 && (
          <CreateNationTabLeadership
            {...tabProps}
            imageSlot={
              <>
                <ImageSlot
                  kind="portrait"
                  size="registration"
                  src={
                    pendingImages.portrait?.url ??
                    draft?.images.portrait?.url ??
                    null
                  }
                  alt="Портрет лидера"
                  interactive
                  rules={rules}
                  onPick={(file) => setImagePick({ kind: 'portrait', file })}
                />
                <FieldMessage error={imageErrors.portrait} />
              </>
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
          {tab === 4
            ? missing.length > 0
              ? 'Заполните обязательные поля (отмечены *) на вкладках с красной точкой'
              : 'Анкета уйдёт на рассмотрение администратору. Править её после отправки нельзя, можно только отменить.'
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
            onClick={() => void handleSubmit()}
          >
            {submitting ? 'Отправляем…' : 'Отправить анкету'}
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
