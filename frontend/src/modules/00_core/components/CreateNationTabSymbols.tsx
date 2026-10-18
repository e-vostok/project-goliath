/**
 * Tab 1 «Основные данные и символика» of the registration window —
 * complete in this issue: full name, short name, motto, description,
 * the color picker (palette grid + HEX field + live color-check hint)
 * and the flag catalog grid. Purely presentational for the form
 * values — they live in the container's RegistrationForm; only the
 * debounced color-check hint is local state, because it is a pure UI
 * preview that never reaches the request body and never blocks submit
 * (the server decides at POST /nations).
 */

import { useEffect, useState, type CSSProperties } from 'react';
import { FormItem, Input } from '@vkontakte/vkui';
import { Icon16Done } from '@vkontakte/icons';

import { api } from '../../../shared/api-client';
import { useSession } from '../hooks/useAuth';
import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';
import { isValidColorHex, normalizeColorHex } from './registrationForm';
import { nationColorCheckText } from './nationErrorTexts';

/** Spec: the color-check fires after ~400 ms of typing silence. */
const COLOR_CHECK_DEBOUNCE_MS = 400;
/** 12 columns → the 36-color config palette wraps into 3 tidy rows. */
const PALETTE_COLUMNS = 12;

const selectedTile: CSSProperties = {
  outline: '2px solid var(--vkui--color_accent)',
  outlineOffset: 2,
};

const checkStyle: CSSProperties = {
  color: '#FFFFFF',
  filter: 'drop-shadow(0 0 2px rgba(0, 0, 0, 0.8))',
  pointerEvents: 'none',
};

export function CreateNationTabSymbols({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  const { token } = useSession();
  const normalizedColor = normalizeColorHex(form.color);
  const colorIsValid = isValidColorHex(form.color);
  const [colorHint, setColorHint] = useState<string | null>(null);

  // The live «цвет свободен / занят / слишком похож» hint: fires only
  // for a syntactically valid #RRGGBB, 400 ms after the last keystroke,
  // the previous request aborted. A failed request shows no hint.
  useEffect(() => {
    setColorHint(null);
    if (!colorIsValid) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api
        .checkNationColor(token, normalizedColor, controller.signal)
        .then((dto) => {
          if (!controller.signal.aborted) {
            setColorHint(nationColorCheckText(dto.status));
          }
        })
        .catch(() => {});
    }, COLOR_CHECK_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [token, normalizedColor, colorIsValid]);

  return (
    <>
      <CreateNationTextField
        id="nation-name"
        label="Название государства"
        testId="form-item-name"
        value={form.name}
        maxLength={rules?.name_max_length}
        error={errors.name}
        hint={hints?.name}
        counter
        onChange={(v) => onFieldChange('name', v)}
        placeholder="напр. Северный Синдикат"
      />

      <CreateNationTextField
        id="nation-short-name"
        label="Краткое название"
        testId="form-item-short-name"
        value={form.shortName}
        maxLength={rules?.short_name_max_length}
        error={errors.shortName}
        hint={hints?.shortName}
        counter
        onChange={(v) => onFieldChange('shortName', v)}
        placeholder="напр. Синдикат"
      />

      <CreateNationTextField
        id="nation-motto"
        label="Девиз (необязательно)"
        testId="form-item-motto"
        value={form.motto}
        maxLength={rules?.motto_max_length}
        error={errors.motto}
        hint={hints?.motto}
        counter
        onChange={(v) => onFieldChange('motto', v)}
        placeholder="напр. Север помнит всё"
      />

      <CreateNationTextField
        id="nation-description"
        label="Описание (необязательно)"
        testId="form-item-description"
        value={form.description}
        maxLength={rules?.description_max_length}
        error={errors.description}
        hint={hints?.description}
        counter
        onChange={(v) => onFieldChange('description', v)}
        placeholder="одна строка о вашем государстве"
      />

      <FormItem
        top="Цвет государства"
        htmlFor="nation-color-hex"
        status={errors.color ? 'error' : 'default'}
        bottom={errors.color ?? colorHint ?? undefined}
        data-testid="form-item-color"
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${PALETTE_COLUMNS}, 1fr)`,
            gap: 6,
            marginBottom: 8,
          }}
        >
          {(rules?.palette ?? []).map((hex) => {
            const upper = hex.toUpperCase();
            const selected = normalizedColor === upper;
            return (
              <button
                key={hex}
                type="button"
                aria-label={upper}
                data-testid={`color-swatch-${upper}`}
                onClick={() => onFieldChange('color', upper)}
                style={{
                  height: 32,
                  padding: 0,
                  border: 'none',
                  borderRadius: 6,
                  backgroundColor: hex,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  ...(selected ? selectedTile : {}),
                }}
              >
                {selected && (
                  <Icon16Done style={checkStyle} aria-hidden="true" />
                )}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ flex: 1 }}>
            <Input
              id="nation-color-hex"
              value={form.color}
              maxLength={7}
              placeholder="#RRGGBB"
              onChange={(e) =>
                onFieldChange('color', e.currentTarget.value.toUpperCase())
              }
            />
          </div>
          <div
            aria-hidden="true"
            data-testid="color-preview"
            style={{
              width: 36,
              height: 36,
              flex: 'none',
              borderRadius: 6,
              border: '1px solid var(--vkui--color_field_border)',
              background: colorIsValid
                ? normalizedColor
                : 'var(--vkui--color_field_background)',
            }}
          />
        </div>
      </FormItem>

      <FormItem
        top="Флаг"
        status={errors.flagId ? 'error' : 'default'}
        bottom={errors.flagId}
        data-testid="form-item-flag"
      >
        {rules !== null && rules.flags.length === 0 ? (
          <div style={{ color: 'var(--vkui--color_text_secondary)' }}>
            Флаги появятся позже
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <button
              type="button"
              onClick={() => onFieldChange('flagId', null)}
              style={{
                width: 90,
                height: 60,
                padding: 0,
                border: '1px dashed var(--vkui--color_field_border)',
                borderRadius: 6,
                background: 'none',
                cursor: 'pointer',
                color: 'var(--vkui--color_text_secondary)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'relative',
                ...(form.flagId === null ? selectedTile : {}),
              }}
            >
              Без флага
              {form.flagId === null && <FlagCheck />}
            </button>
            {(rules?.flags ?? []).map((flag) => {
              const selected = form.flagId === flag.id;
              return (
                <button
                  key={flag.id}
                  type="button"
                  onClick={() => onFieldChange('flagId', flag.id)}
                  style={{
                    width: 90,
                    height: 60,
                    padding: 0,
                    border: 'none',
                    borderRadius: 6,
                    background: 'none',
                    cursor: 'pointer',
                    position: 'relative',
                    ...(selected ? selectedTile : {}),
                  }}
                >
                  <img
                    src={flag.url}
                    alt={flag.id}
                    width={90}
                    height={60}
                    style={{ display: 'block', borderRadius: 6 }}
                  />
                  {selected && <FlagCheck />}
                </button>
              );
            })}
          </div>
        )}
      </FormItem>
    </>
  );
}

/** The selection badge on a flag tile: a check mark, not color alone. */
function FlagCheck() {
  return (
    <span
      aria-hidden="true"
      style={{
        position: 'absolute',
        top: 4,
        right: 4,
        width: 20,
        height: 20,
        borderRadius: '50%',
        background: 'var(--vkui--color_accent)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Icon16Done width={12} height={12} style={{ color: '#FFFFFF' }} />
    </span>
  );
}
