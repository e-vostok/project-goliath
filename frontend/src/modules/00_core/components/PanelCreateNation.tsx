/**
 * PanelCreateNation — the "no nation yet" screen: a two-window container.
 *
 * Window 1 «Основная информация» (CreateNationStepOne): name, color,
 * provinces, leader name, leader title.
 * Window 2 «История государства» (CreateNationStepTwo): history link.
 *
 * The current step and every field value live in this container — the
 * chevron arrows in CreateNationStepBar switch windows without sending or
 * losing anything; the single submit Button (rendered under both windows)
 * fires one POST /nations with both windows' data.
 *
 * Length/host/province-count limits come from GET /nations/rules via
 * useNationRules — the server stays the source of truth; the client only
 * shows hints and gates the button. When rules fail to load the form stays
 * usable without hints and falls back to "non-empty" gating.
 *
 * Server-side `ErrorResponse.code` values map to inline FormItem errors
 * (see `mapErrorCodeToField`); an error for a field on the inactive window
 * marks that window's title with a Badge instead of auto-switching.
 * Anything else surfaces as a generic FormStatus banner.
 */

import { useState, type FormEvent } from 'react';
import bridge from '@vkontakte/vk-bridge';
import {
  Button,
  Div,
  Footnote,
  FormStatus,
  Group,
  PanelHeader,
} from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { ErrorCodes, type NationDTO } from '../../../shared/types';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { useProvinces } from '../hooks/useProvinces';
import {
  nationRulesHints,
  type NationField,
} from './CreateNationFields';
import { CreateNationStepBar } from './CreateNationStepBar';
import {
  CreateNationStepOne,
  type ChipOption,
} from './CreateNationStepOne';
import { CreateNationStepTwo } from './CreateNationStepTwo';

export type { NationField };

/** Maps ErrorResponse.code to the FormItem that should display it inline. */
export function mapErrorCodeToField(code: string): NationField | null {
  switch (code) {
    case ErrorCodes.NAME_TAKEN:
      return 'name';
    case ErrorCodes.COLOR_TAKEN:
      return 'color';
    case ErrorCodes.PROVINCE_TAKEN:
    case ErrorCodes.PROVINCE_NOT_FOUND:
    case ErrorCodes.PROVINCE_COUNT_OUT_OF_RANGE:
      return 'provinces';
    case ErrorCodes.LEADER_NAME_INVALID:
      return 'leaderName';
    case ErrorCodes.LEADER_TITLE_INVALID:
      return 'leaderTitle';
    case ErrorCodes.HISTORY_URL_INVALID:
      return 'historyUrl';
    default:
      return null;
  }
}

/** Which window of the wizard owns the field (history link lives on 2). */
export function fieldToStep(field: NationField): 1 | 2 {
  return field === 'historyUrl' ? 2 : 1;
}

const MAX_FREE_HINT_IDS = 20;

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
  const freeProvinces = useProvinces({ freeOnly: true });
  const rulesState = useNationRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;
  const hints = nationRulesHints(rules);

  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState('');
  const [color, setColor] = useState('#e64545');
  const [chips, setChips] = useState<ChipOption[]>([]);
  const [chipsInput, setChipsInput] = useState('');
  const [leaderName, setLeaderName] = useState('');
  const [leaderTitle, setLeaderTitle] = useState('');
  const [historyUrl, setHistoryUrl] = useState('');
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

  const stepErrors: Record<1 | 2, boolean> = { 1: false, 2: false };
  for (const field of Object.keys(fieldErrors) as NationField[]) {
    stepErrors[fieldToStep(field)] = true;
  }

  const trimmedName = name.trim();
  const canSubmit =
    trimmedName.length >= (rules?.name_min_length ?? 1) &&
    chips.length >= 1 &&
    leaderName.trim().length > 0 &&
    leaderTitle.trim().length > 0 &&
    historyUrl.trim().length > 0 &&
    !submitting;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);

    try {
      const nation = await api.createNation(token, {
        name: trimmedName,
        color_hex: color,
        province_ids: chips.map((chip) => chip.value),
        leader_name: leaderName.trim(),
        leader_title: leaderTitle.trim(),
        history_url: historyUrl.trim(),
      });
      sendTaptic();
      onCreated(nation);
    } catch (error) {
      if (error instanceof ApiError) {
        const field = mapErrorCodeToField(error.code);
        if (field) {
          setFieldErrors({ [field]: error.message });
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError('Ошибка сети — попробуйте ещё раз.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const freeIds =
    freeProvinces.status === 'ready'
      ? freeProvinces.provinces.map((p) => p.id)
      : [];
  const freeHint =
    freeIds.length > 0
      ? `Свободные провинции: ${freeIds.slice(0, MAX_FREE_HINT_IDS).join(', ')}` +
        (freeIds.length > MAX_FREE_HINT_IDS
          ? ` … (всего ${freeIds.length})`
          : '')
      : undefined;
  const provincesHintParts = [freeHint, hints?.provinces].filter(
    (part): part is string => Boolean(part),
  );
  const provincesHint = provincesHintParts.length
    ? provincesHintParts.join('. ')
    : undefined;

  return (
    <>
      <PanelHeader>Создание государства</PanelHeader>
      <Group>
        <CreateNationStepBar
          step={step}
          onStepChange={setStep}
          stepErrors={stepErrors}
        />

        <form onSubmit={handleSubmit} data-testid="create-nation-form">
          {formError && (
            <FormStatus mode="error" title="Не удалось создать государство">
              {formError}
            </FormStatus>
          )}

          {step === 1 ? (
            <CreateNationStepOne
              name={name}
              color={color}
              chips={chips}
              chipsInput={chipsInput}
              leaderName={leaderName}
              leaderTitle={leaderTitle}
              rules={rules}
              hints={hints}
              errors={fieldErrors}
              provincesHint={provincesHint}
              onNameChange={(v) => {
                setName(v);
                clearFieldError('name');
              }}
              onColorChange={(v) => {
                setColor(v);
                clearFieldError('color');
              }}
              onChipsChange={(next) => {
                setChips(next);
                clearFieldError('provinces');
              }}
              onChipsInputChange={setChipsInput}
              onLeaderNameChange={(v) => {
                setLeaderName(v);
                clearFieldError('leaderName');
              }}
              onLeaderTitleChange={(v) => {
                setLeaderTitle(v);
                clearFieldError('leaderTitle');
              }}
            />
          ) : (
            <CreateNationStepTwo
              historyUrl={historyUrl}
              rules={rules}
              hints={hints}
              error={fieldErrors.historyUrl}
              onHistoryUrlChange={(v) => {
                setHistoryUrl(v);
                clearFieldError('historyUrl');
              }}
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
        {freeProvinces.status === 'loading' && (
          <Footnote style={{ padding: '0 16px 12px' }}>
            Загрузка списка свободных провинций…
          </Footnote>
        )}
      </Group>
    </>
  );
}
