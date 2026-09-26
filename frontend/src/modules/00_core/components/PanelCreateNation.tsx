/**
 * PanelCreateNation — the "no nation yet" screen.
 *
 * Group → FormItem(name, Input) → FormItem(color, native <input type="color">
 * — VKUI ships no color picker; per spec this is the pragmatic choice, not a
 * violation) → FormItem(provinces, ChipsInput with numeric-only entry) →
 * submit Button.
 *
 * Server-side `ErrorResponse.code` values map to inline FormItem errors
 * (see `mapErrorCodeToField`); anything else surfaces as a generic
 * FormStatus banner.
 */

import { useState, type FormEvent } from 'react';
import bridge from '@vkontakte/vk-bridge';
import {
  Button,
  ChipsInput,
  Div,
  Footnote,
  FormItem,
  FormStatus,
  Group,
  Input,
  PanelHeader,
} from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { ErrorCodes, type NationDTO } from '../../../shared/types';
import { useSession } from '../hooks/useAuth';
import { useProvinces } from '../hooks/useProvinces';

type NationField = 'name' | 'color' | 'provinces';

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
    default:
      return null;
  }
}

// Cosmetic client-side bounds (Spec Part 4 defaults: min 3, max 40).
// The authoritative check is server-side via CoreConfig.
const NAME_MAX_LENGTH = 40;
const MAX_FREE_HINT_IDS = 20;

const sendTaptic = () => {
  void bridge
    .send('VKWebAppTapticImpactOccurred', { style: 'medium' })
    .catch(() => {});
};

interface ChipOption {
  value: number;
  label: string;
}

export interface PanelCreateNationProps {
  onCreated: (nation: NationDTO) => void;
}

export function PanelCreateNation({ onCreated }: PanelCreateNationProps) {
  const { token } = useSession();
  const freeProvinces = useProvinces({ freeOnly: true });

  const [name, setName] = useState('');
  const [color, setColor] = useState('#e64545');
  const [chips, setChips] = useState<ChipOption[]>([]);
  const [chipsInput, setChipsInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<NationField, string>>
  >({});
  const [formError, setFormError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const canSubmit = trimmedName.length >= 3 && chips.length >= 1 && !submitting;

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
        setFormError('Network error — please try again.');
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
      ? `Free province IDs: ${freeIds.slice(0, MAX_FREE_HINT_IDS).join(', ')}` +
        (freeIds.length > MAX_FREE_HINT_IDS
          ? ` … (${freeIds.length} total)`
          : '')
      : undefined;

  return (
    <>
      <PanelHeader>Create your nation</PanelHeader>
      <Group>
        <form onSubmit={handleSubmit} data-testid="create-nation-form">
          {formError && (
            <FormStatus mode="error" title="Could not create nation">
              {formError}
            </FormStatus>
          )}

          <FormItem
            top="Nation name"
            htmlFor="nation-name"
            status={fieldErrors.name ? 'error' : 'default'}
            bottom={fieldErrors.name}
            data-testid="form-item-name"
          >
            <Input
              id="nation-name"
              value={name}
              maxLength={NAME_MAX_LENGTH}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="e.g. Northern Syndicate"
            />
          </FormItem>

          <FormItem
            top="Nation color"
            htmlFor="nation-color"
            status={fieldErrors.color ? 'error' : 'default'}
            bottom={fieldErrors.color}
            data-testid="form-item-color"
          >
            <input
              id="nation-color"
              type="color"
              value={color}
              onChange={(e) => setColor(e.currentTarget.value)}
              style={{
                width: '100%',
                height: 36,
                padding: 0,
                border: 'none',
                background: 'none',
                cursor: 'pointer',
              }}
            />
          </FormItem>

          <FormItem
            top="Provinces"
            status={fieldErrors.provinces ? 'error' : 'default'}
            bottom={fieldErrors.provinces ?? freeHint}
            data-testid="form-item-provinces"
          >
            <ChipsInput
              value={chips}
              inputValue={chipsInput}
              placeholder="Type a province ID and press Enter"
              onInputChange={(e) =>
                setChipsInput(e.currentTarget.value.replace(/\D/g, ''))
              }
              onChange={setChips}
              getNewOptionData={(_, label) => ({
                value: Number(label),
                label: String(label),
              })}
              addOnBlur
            />
          </FormItem>

          <Div>
            <Button
              type="submit"
              size="l"
              stretched
              disabled={!canSubmit}
              loading={submitting}
            >
              Found nation
            </Button>
          </Div>
        </form>
        {freeProvinces.status === 'loading' && (
          <Footnote style={{ padding: '0 16px 12px' }}>
            Loading free provinces…
          </Footnote>
        )}
      </Group>
    </>
  );
}
