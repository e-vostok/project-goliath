/**
 * Tab 2 «Глава государства» of the registration window (UI Spec 9.6 —
 * version 0.9.0 unit 8c): the portrait catalog row (a portrait is
 * ALWAYS selected — no «Без портрета», the first catalog portrait is
 * preselected and stands in for a legacy NULL portrait), then one row
 * «Имя лидера *» + «Должность лидера *» + «Пол *» (two small square
 * icon buttons — the Venus mirror and the Mars spear, one active at a
 * time), the optional «Биография лидера» TextArea of three lines, and
 * the four succession-type cards (one 2×2 radio group, marked by
 * outline + check, not color alone) with the «Пока без последствий в
 * игре» caption. The card/gender labels live in nationLabels.ts; the
 * rules order decides what renders. Purely presentational — every
 * value lives in the container's RegistrationForm.
 */

import { useRef, type CSSProperties, type KeyboardEvent } from 'react';
import {
  Icon28CrownOutline,
  Icon28PollSquareOutline,
  Icon28SlidersOutline,
  Icon28UserAddOutline,
} from '@vkontakte/icons';

import {
  FieldLabel,
  FieldMessage,
  MarsIcon,
  RADII,
  SIZES,
  TEXT_STYLES,
  tokenVar,
  VenusIcon,
} from '../../../shared/ui';
import {
  CreateNationTextArea,
  CreateNationTextField,
  PickCheck,
  type RegistrationTabProps,
} from './CreateNationFields';
import { GENDER_LABELS, SUCCESSION_LABELS } from './nationLabels';

const selectedTile: CSSProperties = {
  outline: `2px solid ${tokenVar('action')}`,
  outlineOffset: 2,
};

/** One icon per fixed succession code (Spec 1.3 Part 5, tab 2). */
const SUCCESSION_ICONS = {
  elections: Icon28PollSquareOutline,
  appointment: Icon28UserAddOutline,
  criteria: Icon28SlidersOutline,
  inheritance: Icon28CrownOutline,
};

/** One icon per fixed gender code — Venus mirror / Mars spear. */
const GENDER_ICONS = {
  female: VenusIcon,
  male: MarsIcon,
};

/** Spec order of the gender buttons: Venus mirror, then Mars spear. */
const GENDER_ORDER = ['female', 'male'] as const;

/**
 * Arrow keys move selection and focus inside a role="radiogroup" of
 * buttons, like native radios; every card stays a real <button>, so
 * Enter/Space pick the focused one on their own.
 */
function onRadioArrow(
  event: KeyboardEvent<HTMLButtonElement>,
  index: number,
  order: readonly string[],
  refs: Map<string, HTMLButtonElement>,
  pick: (code: string) => void,
) {
  const delta =
    event.key === 'ArrowRight' || event.key === 'ArrowDown'
      ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
        ? -1
        : 0;
  if (delta === 0 || order.length === 0) {
    return;
  }
  event.preventDefault();
  const code = order[(index + delta + order.length) % order.length];
  pick(code);
  refs.get(code)?.focus();
}

export function CreateNationTabLeadership({
  form,
  rules,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  const genderRefs = useRef(new Map<string, HTMLButtonElement>());
  const successionRefs = useRef(new Map<string, HTMLButtonElement>());

  // Spec order is fixed (Venus first) — the rules list just gates
  // which codes exist.
  const genders = GENDER_ORDER.filter((code) =>
    (rules?.genders ?? []).includes(code),
  ).concat(
    (rules?.genders ?? []).filter(
      (code) => !GENDER_ORDER.includes(code as never),
    ),
  );
  const successionTypes = rules?.succession_types ?? [];

  return (
    <>
      <div data-testid="form-item-portrait">
        <FieldLabel label="Портрет" required />
        {rules !== null && rules.portraits.length === 0 ? (
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            Портреты появятся позже
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {(rules?.portraits ?? []).map((portrait) => {
              const selected = form.portraitId === portrait.id;
              return (
                <button
                  key={portrait.id}
                  type="button"
                  aria-pressed={selected}
                  aria-label={portrait.id}
                  onClick={() => onFieldChange('portraitId', portrait.id)}
                  style={{
                    width: 90,
                    height: 120,
                    padding: 0,
                    border: 'none',
                    borderRadius: RADII['radius-md'],
                    background: 'none',
                    cursor: 'pointer',
                    position: 'relative',
                    ...(selected ? selectedTile : {}),
                  }}
                >
                  <img
                    src={portrait.url}
                    alt={portrait.id}
                    width={90}
                    height={120}
                    style={{ display: 'block', borderRadius: RADII['radius-md'] }}
                  />
                  {selected && <PickCheck />}
                </button>
              );
            })}
          </div>
        )}
        <FieldMessage error={errors.portraitId} />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'flex-end',
          marginTop: 16,
        }}
      >
        <div style={{ flex: '1 1 0', minWidth: 0 }}>
          <CreateNationTextField
            id="nation-leader-name"
            label="Имя лидера"
            required
            testId="form-item-leader-name"
            value={form.leaderName}
            maxLength={rules?.leader_name_max_length}
            error={errors.leaderName}
            onChange={(v) => onFieldChange('leaderName', v)}
            placeholder="напр. Иван Грозный"
          />
        </div>
        <div style={{ flex: '1 1 0', minWidth: 0 }}>
          <CreateNationTextField
            id="nation-leader-title"
            label="Должность лидера"
            required
            testId="form-item-leader-title"
            value={form.leaderTitle}
            maxLength={rules?.leader_title_max_length}
            error={errors.leaderTitle}
            onChange={(v) => onFieldChange('leaderTitle', v)}
            placeholder="напр. Верховный правитель"
          />
        </div>
        <div data-testid="form-item-gender" style={{ flex: '0 0 auto' }}>
          <FieldLabel label="Пол" required />
          <div
            role="radiogroup"
            aria-label="Пол"
            style={{ display: 'flex', gap: 8 }}
          >
            {genders.map((code, index) => {
              const selected = form.gender === code;
              const GenderIcon =
                GENDER_ICONS[code as keyof typeof GENDER_ICONS];
              const label = GENDER_LABELS[code] ?? code;
              return (
                <button
                  key={code}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={label}
                  title={label}
                  ref={(el) => {
                    if (el) {
                      genderRefs.current.set(code, el);
                    } else {
                      genderRefs.current.delete(code);
                    }
                  }}
                  onClick={() => onFieldChange('gender', code)}
                  onKeyDown={(e) =>
                    onRadioArrow(e, index, genders, genderRefs.current, (c) =>
                      onFieldChange('gender', c),
                    )
                  }
                  style={{
                    width: SIZES['button-h'],
                    height: SIZES['button-h'],
                    padding: 0,
                    border: `1px solid ${tokenVar('ink-faint')}`,
                    borderRadius: RADII['radius-md'],
                    background: tokenVar('surface-inset'),
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: tokenVar(selected ? 'action' : 'ink-muted'),
                    ...(selected ? selectedTile : {}),
                  }}
                >
                  {GenderIcon !== undefined ? <GenderIcon /> : label}
                </button>
              );
            })}
          </div>
          <FieldMessage error={errors.gender} />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <CreateNationTextArea
          id="nation-leader-bio"
          label="Биография лидера"
          rows={3}
          testId="form-item-leader-bio"
          value={form.leaderBio}
          maxLength={rules?.leader_bio_max_length}
          error={errors.leaderBio}
          onChange={(v) => onFieldChange('leaderBio', v)}
          placeholder="Пара строк о жизни и характере лидера"
        />
      </div>

      <div data-testid="form-item-succession" style={{ marginTop: 16 }}>
        <FieldLabel label="Способ смены лидера" required />
        <div
          role="radiogroup"
          aria-label="Способ смены лидера"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 8,
          }}
        >
          {successionTypes.map((code, index) => {
            const label = SUCCESSION_LABELS[code];
            const Icon = SUCCESSION_ICONS[code as keyof typeof SUCCESSION_ICONS];
            const selected = form.successionType === code;
            return (
              <button
                key={code}
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={label?.title ?? code}
                ref={(el) => {
                  if (el) {
                    successionRefs.current.set(code, el);
                  } else {
                    successionRefs.current.delete(code);
                  }
                }}
                onClick={() => onFieldChange('successionType', code)}
                onKeyDown={(e) =>
                  onRadioArrow(
                    e,
                    index,
                    successionTypes,
                    successionRefs.current,
                    (c) => onFieldChange('successionType', c),
                  )
                }
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                  padding: 12,
                  border: `1px solid ${tokenVar('ink-faint')}`,
                  borderRadius: RADII['radius-md'],
                  background: tokenVar('surface-inset'),
                  cursor: 'pointer',
                  textAlign: 'left',
                  position: 'relative',
                  color: tokenVar('ink'),
                  ...(selected ? selectedTile : {}),
                }}
              >
                {Icon && (
                  <Icon
                    width={28}
                    height={28}
                    style={{
                      color: tokenVar('action'),
                      flexShrink: 0,
                      marginTop: 2,
                    }}
                    aria-hidden="true"
                  />
                )}
                <span>
                  <span
                    style={{
                      display: 'block',
                      ...TEXT_STYLES['body'],
                      fontWeight: 600,
                    }}
                  >
                    {label?.title ?? code}
                  </span>
                  <span
                    style={{
                      display: 'block',
                      marginTop: 2,
                      ...TEXT_STYLES['caption'],
                      color: tokenVar('ink-muted'),
                    }}
                  >
                    {label?.description ?? ''}
                  </span>
                </span>
                {selected && <PickCheck />}
              </button>
            );
          })}
        </div>
        <FieldMessage
          error={errors.successionType}
          hint="Пока без последствий в игре"
        />
      </div>
    </>
  );
}
