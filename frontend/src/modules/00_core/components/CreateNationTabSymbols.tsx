/**
 * Tab 1 «Основные данные и символика» of the registration window (UI
 * Spec 9.6 — version 0.9.0 unit 8c): row «Полное название *» +
 * «Краткое название *», row «Описание» (two-line TextArea, the wider
 * field) left + «Девиз» right, then «Цвет государства *» — the palette
 * grid + HEX field + the live «цвет свободен» check. Purely
 * presentational for the
 * form values — they live in the container's RegistrationForm; only
 * the debounced color-check hint is local state, because it is a pure
 * UI preview that never reaches the request body and never blocks
 * submit (the server decides at POST /nations).
 */

import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { Icon16Done } from '@vkontakte/icons';

import { api } from '../../../shared/api-client';
import { useSession } from '../hooks/useAuth';
import {
  FieldLabel,
  FieldMessage,
  RADII,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import {
  CreateNationTextArea,
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';
import { isValidColorHex, normalizeColorHex } from './registrationForm';
import { nationColorCheckText } from './nationErrorTexts';

/** Spec: the color-check fires after ~400 ms of typing silence. */
const COLOR_CHECK_DEBOUNCE_MS = 400;
/** 12 columns → the 36-color config palette wraps into 3 tidy rows. */
const PALETTE_COLUMNS = 12;

const row: CSSProperties = {
  display: 'flex',
  gap: 16,
  alignItems: 'flex-start',
};

const cell: CSSProperties = {
  flex: '1 1 0',
  minWidth: 0,
};

const selectedTile: CSSProperties = {
  outline: `2px solid ${tokenVar('action')}`,
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
  errors,
  onFieldChange,
  imageSlot,
}: RegistrationTabProps & { imageSlot?: ReactNode }) {
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
      <div style={row}>
        <div style={cell}>
          <CreateNationTextField
            id="nation-name"
            label="Полное название"
            required
            testId="form-item-name"
            value={form.name}
            maxLength={rules?.name_max_length}
            error={errors.name}
            onChange={(v) => onFieldChange('name', v)}
            placeholder="напр. Северный Синдикат"
          />
        </div>
        <div style={cell}>
          <CreateNationTextField
            id="nation-short-name"
            label="Краткое название"
            required
            testId="form-item-short-name"
            value={form.shortName}
            maxLength={rules?.short_name_max_length}
            error={errors.shortName}
            onChange={(v) => onFieldChange('shortName', v)}
            placeholder="напр. Синдикат"
          />
        </div>
      </div>

      <div style={{ ...row, marginTop: 16 }}>
        <div style={{ flex: '2 1 0', minWidth: 0 }}>
          <CreateNationTextArea
            id="nation-description"
            label="Описание"
            rows={2}
            testId="form-item-description"
            value={form.description}
            maxLength={rules?.description_max_length}
            error={errors.description}
            onChange={(v) => onFieldChange('description', v)}
            placeholder="Пара строк о вашем государстве"
          />
        </div>
        <div style={cell}>
          <CreateNationTextField
            id="nation-motto"
            label="Девиз"
            testId="form-item-motto"
            value={form.motto}
            maxLength={rules?.motto_max_length}
            error={errors.motto}
            onChange={(v) => onFieldChange('motto', v)}
            placeholder="напр. Север помнит всё"
          />
        </div>
      </div>

      <div data-testid="form-item-color" style={{ marginTop: 16 }}>
        <FieldLabel
          label="Цвет государства"
          required
          htmlFor="nation-color-hex"
        />
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
                  borderRadius: RADII['radius-md'],
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
          <input
            id="nation-color-hex"
            value={form.color}
            maxLength={7}
            placeholder="#RRGGBB"
            onChange={(e) =>
              onFieldChange('color', e.currentTarget.value.toUpperCase())
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
              }
            }}
            style={{
              flex: 1,
              minWidth: 0,
              height: 36,
              boxSizing: 'border-box',
              background: tokenVar('surface-inset'),
              color: tokenVar('ink'),
              border: `1px solid ${tokenVar('ink-faint')}`,
              borderRadius: RADII['radius-md'],
              padding: '0 12px',
              ...TEXT_STYLES['body'],
            }}
          />
          <div
            aria-hidden="true"
            data-testid="color-preview"
            style={{
              width: 36,
              height: 36,
              flex: 'none',
              borderRadius: RADII['radius-md'],
              border: `1px solid ${tokenVar('ink-faint')}`,
              background: colorIsValid
                ? normalizedColor
                : tokenVar('surface-inset'),
            }}
          />
        </div>
        <FieldMessage
          error={errors.color}
          hint={errors.color === undefined ? (colorHint ?? undefined) : undefined}
        />
      </div>

      {/* 0.12.0 board 13 — the optional flag block closes the tab. */}
      {imageSlot !== undefined && (
        <div data-testid="form-item-flag" style={{ marginTop: 16 }}>
          <FieldLabel label="Флаг" />
          {imageSlot}
        </div>
      )}
    </>
  );
}
