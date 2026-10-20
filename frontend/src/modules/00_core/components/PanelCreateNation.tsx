/**
 * PanelCreateNation — the "no nation yet" screen: a window of four tabs
 * (Spec 1.3 Part 5).
 *
 * Tab 1 «Основные данные и символика», tab 2 «Руководство», tab 3
 * «История и культура», tab 4 «Территории». The current tab and every
 * field value live in this container as one `RegistrationForm` object —
 * the chevron arrows and the clickable titles in CreateNationTabBar
 * switch tabs without sending or losing anything; the single submit
 * Button fires one POST /nations with the whole form.
 *
 * Provinces are picked on the map — the «Выбрать на карте» button on
 * tab 4 opens the 01_map ProvincePicker popup; the selection lives in
 * `form.provinces` (value = province id, label = display name, order =
 * selection order).
 *
 * The whole form is mirrored into the session draft under
 * 'nation-create-v2'; a successful creation deletes it. Length/host/
 * province-count limits come from GET /nations/rules via useNationRules —
 * the server stays the source of truth; the client only shows hints and
 * gates the button on `missingRequired`.
 *
 * Server-side `ErrorResponse.code` values map to inline FormItem errors
 * through `mapErrorCodeToField` and become Russian text through the
 * shared `errorText` (nation field codes keep the limits-aware texts of
 * `nationErrorTexts`; the English `detail` is never shown). An error
 * or a missing required field on an inactive tab marks its title with a
 * Badge — the window never switches tabs on its own. Anything else
 * surfaces as a generic FormStatus banner.
 */

import { useEffect, useState, type FormEvent } from 'react';
import bridge from '@vkontakte/vk-bridge';
import {
  Button,
  Div,
  FormStatus,
  Group,
  PanelHeader,
  Spinner,
} from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { useFormDraft } from '../../../shared/formDraft';
import { SUCCESS_RU } from '../../../shared/texts/success.ru';
import type { NationDTO } from '../../../shared/types';
import { useNotice } from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
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
import { CreateNationTabBar } from './CreateNationTabBar';
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
  // badges for missing required fields show right away.
  const [touched, setTouched] = useState(
    storedDraft !== null &&
      !registrationFormIsEmpty(registrationFormFromDraft(storedDraft)),
  );
  const [pickerOpen, setPickerOpen] = useState(false);
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
        // INV-14: the capital must stay among the chosen ids — a chip
        // removal that takes the capital away drops the mark.
        const chips = next.provinces;
        next.capitalProvinceId =
          prev.capitalProvinceId !== null &&
          chips.some((chip) => chip.value === prev.capitalProvinceId)
            ? prev.capitalProvinceId
            : null;
        // Until a manual edit the capital name follows the effective
        // capital (the marked chip, else the first selected one).
        if (!prev.capitalNameEdited) {
          const effective = next.capitalProvinceId ?? chips[0]?.value ?? null;
          next.capitalName =
            chips.find((chip) => chip.value === effective)?.label ?? '';
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

  // Tab badges: a server error on a field of that tab, or — once any
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

  // Mirror the form into the session draft; a pristine form drops it.
  useEffect(() => {
    if (registrationFormIsEmpty(form)) {
      clearDraft();
    } else {
      setStoredDraft(form);
    }
  }, [form, setStoredDraft, clearDraft]);

  const canSubmit = missing.length === 0 && !submitting;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);

    try {
      const nation = await api.createNation(token, toCreateRequest(form));
      sendTaptic();
      clearDraft();
      notify(SUCCESS_RU.nationCreated);
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
    return (
      <Div
        style={{
          display: 'flex',
          justifyContent: 'center',
          padding: '48px 0',
        }}
      >
        <Spinner size="l" />
      </Div>
    );
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

  return (
    <>
      <PanelHeader>Создание государства</PanelHeader>
      <Group>
        <CreateNationTabBar
          tab={tab}
          onTabChange={setTab}
          tabMarks={tabMarks}
        />

        <form onSubmit={handleSubmit} data-testid="create-nation-form">
          {formError && (
            <FormStatus mode="error" title="Не удалось создать государство">
              {formError}
            </FormStatus>
          )}

          {tab === 1 && <CreateNationTabSymbols {...tabProps} />}
          {tab === 2 && <CreateNationTabLeadership {...tabProps} />}
          {tab === 3 && <CreateNationTabHistory {...tabProps} />}
          {tab === 4 && (
            <CreateNationTabTerritories
              {...tabProps}
              onOpenPicker={() => setPickerOpen(true)}
            />
          )}

          <Div>
            <Button
              type="submit"
              size="l"
              stretched
              disabled={!canSubmit}
              loading={submitting}
            >
              Основать государство
            </Button>
          </Div>
        </form>
      </Group>
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
    </>
  );
}
