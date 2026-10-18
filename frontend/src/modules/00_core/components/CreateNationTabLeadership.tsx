/**
 * Tab 2 «Руководство» of the registration window — complete in this
 * issue: the portrait catalog grid («Без портрета» option, empty
 * catalog message), leader name, gender as two pick-one buttons,
 * leader title, the optional biography Textarea with a length counter,
 * and the four succession-type cards (one 2×2 radio group, marked by
 * outline + check, not color alone) with the «Пока без последствий в
 * игре» caption. The card/gender labels live in nationLabels.ts so
 * Issue 16 reuses them; the rules order decides what renders.
 * Purely presentational — every value lives in the container's
 * RegistrationForm.
 */

import { useRef, type CSSProperties, type KeyboardEvent } from 'react';
import { FormItem, Textarea } from '@vkontakte/vkui';
import {
  Icon16Done,
  Icon28CrownOutline,
  Icon28PollSquareOutline,
  Icon28SlidersOutline,
  Icon28UserAddOutline,
} from '@vkontakte/icons';

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';
import { GENDER_LABELS, SUCCESSION_LABELS } from './nationLabels';

const selectedTile: CSSProperties = {
  outline: '2px solid var(--vkui--color_accent)',
  outlineOffset: 2,
};

/** One icon per fixed succession code (Spec 1.3 Part 5, tab 2). */
const SUCCESSION_ICONS = {
  elections: Icon28PollSquareOutline,
  appointment: Icon28UserAddOutline,
  criteria: Icon28SlidersOutline,
  inheritance: Icon28CrownOutline,
};

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
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  const genderRefs = useRef(new Map<string, HTMLButtonElement>());
  const successionRefs = useRef(new Map<string, HTMLButtonElement>());

  const genders = rules?.genders ?? [];
  const successionTypes = rules?.succession_types ?? [];

  return (
    <>
      <FormItem
        top="Портрет"
        status={errors.portraitId ? 'error' : 'default'}
        bottom={errors.portraitId}
        data-testid="form-item-portrait"
      >
        {rules !== null && rules.portraits.length === 0 ? (
          <div style={{ color: 'var(--vkui--color_text_secondary)' }}>
            Портреты появятся позже
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <button
              type="button"
              onClick={() => onFieldChange('portraitId', null)}
              style={{
                width: 90,
                height: 120,
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
                ...(form.portraitId === null ? selectedTile : {}),
              }}
            >
              Без портрета
              {form.portraitId === null && <PickCheck />}
            </button>
            {(rules?.portraits ?? []).map((portrait) => {
              const selected = form.portraitId === portrait.id;
              return (
                <button
                  key={portrait.id}
                  type="button"
                  onClick={() => onFieldChange('portraitId', portrait.id)}
                  style={{
                    width: 90,
                    height: 120,
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
                    src={portrait.url}
                    alt={portrait.id}
                    width={90}
                    height={120}
                    style={{ display: 'block', borderRadius: 6 }}
                  />
                  {selected && <PickCheck />}
                </button>
              );
            })}
          </div>
        )}
      </FormItem>

      <CreateNationTextField
        id="nation-leader-name"
        label="Имя лидера"
        testId="form-item-leader-name"
        value={form.leaderName}
        maxLength={rules?.leader_name_max_length}
        error={errors.leaderName}
        hint={hints?.leaderName}
        onChange={(v) => onFieldChange('leaderName', v)}
        placeholder="напр. Иван Грозный"
      />

      <FormItem
        top="Пол лидера"
        status={errors.gender ? 'error' : 'default'}
        bottom={errors.gender}
        data-testid="form-item-gender"
      >
        <div
          role="radiogroup"
          aria-label="Пол лидера"
          style={{ display: 'flex', gap: 8 }}
        >
          {genders.map((code, index) => {
            const selected = form.gender === code;
            return (
              <button
                key={code}
                type="button"
                role="radio"
                aria-checked={selected}
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
                  flex: 1,
                  padding: '8px 12px',
                  border: '1px solid var(--vkui--color_field_border)',
                  borderRadius: 8,
                  background: 'none',
                  cursor: 'pointer',
                  color: 'var(--vkui--color_text_primary)',
                  ...(selected ? selectedTile : {}),
                }}
              >
                {GENDER_LABELS[code] ?? code}
              </button>
            );
          })}
        </div>
      </FormItem>

      <CreateNationTextField
        id="nation-leader-title"
        label="Должность лидера"
        testId="form-item-leader-title"
        value={form.leaderTitle}
        maxLength={rules?.leader_title_max_length}
        error={errors.leaderTitle}
        hint={hints?.leaderTitle}
        onChange={(v) => onFieldChange('leaderTitle', v)}
        placeholder="напр. Верховный правитель"
      />

      <FormItem
        top="Биография лидера (необязательно)"
        htmlFor="nation-leader-bio"
        status={errors.leaderBio ? 'error' : 'default'}
        bottom={errors.leaderBio ?? hints?.leaderBio}
        data-testid="form-item-leader-bio"
      >
        <Textarea
          id="nation-leader-bio"
          value={form.leaderBio}
          maxLength={rules?.leader_bio_max_length}
          onChange={(e) => onFieldChange('leaderBio', e.currentTarget.value)}
          placeholder="Пара строк о жизни и характере лидера"
          afterAlign="start"
          after={
            rules ? (
              <span
                style={{
                  color: 'var(--vkui--color_text_secondary)',
                  whiteSpace: 'nowrap',
                }}
              >
                {form.leaderBio.length} / {rules.leader_bio_max_length}
              </span>
            ) : undefined
          }
        />
      </FormItem>

      <FormItem
        top="Способ смены лидера"
        status={errors.successionType ? 'error' : 'default'}
        bottom={errors.successionType}
        data-testid="form-item-succession"
      >
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
                  border: '1px solid var(--vkui--color_field_border)',
                  borderRadius: 8,
                  background: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                  position: 'relative',
                  color: 'var(--vkui--color_text_primary)',
                  ...(selected ? selectedTile : {}),
                }}
              >
                {Icon && (
                  <Icon
                    width={28}
                    height={28}
                    style={{
                      color: 'var(--vkui--color_accent)',
                      flexShrink: 0,
                      marginTop: 2,
                    }}
                    aria-hidden="true"
                  />
                )}
                <span>
                  <span style={{ display: 'block', fontWeight: 600 }}>
                    {label?.title ?? code}
                  </span>
                  <span
                    style={{
                      display: 'block',
                      marginTop: 2,
                      fontSize: 13,
                      color: 'var(--vkui--color_text_secondary)',
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
        <div
          style={{
            marginTop: 8,
            color: 'var(--vkui--color_text_secondary)',
          }}
        >
          Пока без последствий в игре
        </div>
      </FormItem>
    </>
  );
}

/** The selection badge on a picked tile/card: a check mark, not color alone. */
function PickCheck() {
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
