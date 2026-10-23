/**
 * Field set (UI Spec 6, элемент 11 — version 0.9.0 unit 8c): the one
 * labelled input grammar for every form.
 *
 * `FieldLabel` is the row above a field: the name in `label` style
 * (uppercase, `ink-muted`), a «*» after the name for required fields
 * (the ONLY required mark — the word «необязательно» is never written)
 * and the length counter «N / M» at the right end of the row. The
 * star sits OUTSIDE the <label> element so the accessible name stays
 * the plain field name.
 *
 * `TextField` — one-line input, `TextArea` — multi-line: `surface-inset`
 * background, `radius-md`, a 1 px `ink-faint` frame (`danger` while a
 * field error is shown), body text in `ink`. The error text lives under
 * the field in `danger` with a mark; an optional hint under the field
 * in `ink-muted` small text. There is never a second «до N символов»
 * under a field — the counter above already says the limit.
 *
 * Keyboard rule (every form): Enter in a one-line field does nothing
 * (preventDefault, focus stays), Enter in a TextArea inserts a line
 * break — nothing ever submits a form but the explicit buttons.
 */

import type { CSSProperties } from 'react';

import { RADII, SPACING, SIZES, TEXT_STYLES, tokenVar } from './tokens';

export interface FieldLabelProps {
  /** Field name shown in `label` style (uppercase via the style). */
  label: string;
  /** Appends the required star after the name. */
  required?: boolean;
  /** `htmlFor` of the label element — skip it for non-input groups. */
  htmlFor?: string;
  /** Right end of the row — the «N / M» counter when given. */
  counter?: { current: number; max: number };
  testId?: string;
}

export function FieldLabel({
  label,
  required = false,
  htmlFor,
  counter,
  testId,
}: FieldLabelProps) {
  const textStyle: CSSProperties = {
    ...TEXT_STYLES['label'],
    color: tokenVar('ink-muted'),
  };
  return (
    <div
      data-testid={testId}
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        gap: SPACING['space-2'],
        marginBottom: 6,
      }}
    >
      <span style={textStyle}>
        {htmlFor === undefined ? (
          label
        ) : (
          <label htmlFor={htmlFor} style={textStyle}>
            {label}
          </label>
        )}
        {required && (
          <span
            aria-hidden="true"
            style={{ color: tokenVar('danger'), marginLeft: 2 }}
          >
            *
          </span>
        )}
      </span>
      {counter !== undefined && (
        <span
          data-testid={testId ? `${testId}-counter` : undefined}
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
            whiteSpace: 'nowrap',
          }}
        >
          {counter.current} / {counter.max}
        </span>
      )}
    </div>
  );
}

/** Small error mark — the «значок» of a field error (Spec 7). */
function ErrorMark() {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <circle
        cx="7"
        cy="7"
        r="5.6"
        stroke="currentColor"
        strokeWidth={1.4}
      />
      <path
        d="M7 4.2v3.4"
        stroke="currentColor"
        strokeWidth={1.4}
        strokeLinecap="round"
      />
      <circle cx="7" cy="9.8" r="0.9" fill="currentColor" />
    </svg>
  );
}

const messageRow: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 4,
  marginTop: 4,
  ...TEXT_STYLES['caption'],
};

/**
 * The lines under a field (or under a group control like the palette
 * or a tile row — those have no input of their own): the error in
 * `danger` with a mark, then the hint in `ink-muted` small text.
 */
export function FieldMessage({
  error,
  hint,
}: {
  error?: string;
  hint?: string;
}) {
  return (
    <>
      {error !== undefined && error !== '' && (
        <div style={{ ...messageRow, color: tokenVar('danger') }}>
          <ErrorMark />
          <span>{error}</span>
        </div>
      )}
      {hint !== undefined && hint !== '' && (
        <div style={{ ...messageRow, color: tokenVar('ink-muted') }}>
          <span>{hint}</span>
        </div>
      )}
    </>
  );
}

const inputBase: CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: tokenVar('surface-inset'),
  color: tokenVar('ink'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  borderRadius: RADII['radius-md'],
  padding: '0 12px',
  ...TEXT_STYLES['body'],
};

export interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  required?: boolean;
  /** The «N / M» counter shows while a limit is known. */
  maxLength?: number;
  error?: string;
  hint?: string;
  placeholder?: string;
  testId?: string;
  onChange: (value: string) => void;
}

export function TextField({
  id,
  label,
  value,
  required = false,
  maxLength,
  error,
  hint,
  placeholder,
  testId,
  onChange,
}: TextFieldProps) {
  return (
    <div data-testid={testId} style={{ minWidth: 0 }}>
      <FieldLabel
        label={label}
        required={required}
        htmlFor={id}
        counter={
          maxLength !== undefined
            ? { current: value.length, max: maxLength }
            : undefined
        }
      />
      <input
        id={id}
        value={value}
        required={required}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => onChange(e.currentTarget.value)}
        onKeyDown={(e) => {
          // Enter never submits anything anywhere in the app.
          if (e.key === 'Enter') {
            e.preventDefault();
          }
        }}
        style={{
          ...inputBase,
          height: SIZES['button-h'],
          border: `1px solid ${tokenVar(error ? 'danger' : 'ink-faint')}`,
        }}
      />
      <FieldMessage error={error} hint={hint} />
    </div>
  );
}

export interface TextAreaProps extends Omit<TextFieldProps, 'onChange'> {
  /** Visible text lines — 2 for a short note, 3 for a biography. */
  rows?: number;
  onChange: (value: string) => void;
}

export function TextArea({
  id,
  label,
  value,
  required = false,
  maxLength,
  error,
  hint,
  placeholder,
  rows = 2,
  testId,
  onChange,
}: TextAreaProps) {
  return (
    <div data-testid={testId} style={{ minWidth: 0 }}>
      <FieldLabel
        label={label}
        required={required}
        htmlFor={id}
        counter={
          maxLength !== undefined
            ? { current: value.length, max: maxLength }
            : undefined
        }
      />
      <textarea
        id={id}
        value={value}
        required={required}
        maxLength={maxLength}
        placeholder={placeholder}
        rows={rows}
        onChange={(e) => onChange(e.currentTarget.value)}
        style={{
          ...inputBase,
          padding: '8px 12px',
          // Vertical drag only, never below the initial rows height
          // (acceptance 12b) and never past the 320 px cap.
          resize: 'vertical',
          minHeight: `calc(${rows} * 20px + 16px)`,
          maxHeight: 320,
          border: `1px solid ${tokenVar(error ? 'danger' : 'ink-faint')}`,
        }}
      />
      <FieldMessage error={error} hint={hint} />
    </div>
  );
}
