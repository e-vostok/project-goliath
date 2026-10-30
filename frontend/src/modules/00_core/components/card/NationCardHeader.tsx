/**
 * NationCardHeader — the screen title of the «Штаб» card (UI Spec
 * 9.1, mockup «PAX ATOMICA — макеты окон» board 8): flag 96×64
 * (`FlagStub` when the nation has no uploaded flag), the short name as the
 * small label line above the name — always shown, no «Кратко:» words —
 * the name in `display-lg`, the motto in italics when set, the colour
 * swatch with HEX, and the «Изменить» button on the right (the pencil
 * icon; the edit behaviour itself lives in PanelNationHome). An
 * `action` node replaces that button — the nation subscreen shows
 * «Показать на карте» there (unit 14c).
 */

import { useState, type ReactNode } from 'react';

import type { NationDTO, NationPublicDTO } from '../../../../shared/types';
import {
  ColorSwatch,
  ImageSlot,
  PencilIcon,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import {
  imageSlotHint,
  type NationImageEditor,
} from '../imageEditor';
import { CardBlock } from './CardBlock';

export function NationCardHeader({
  nation,
  onEdit,
  action,
  imageEditor,
}: {
  nation: NationDTO | NationPublicDTO;
  onEdit?: () => void;
  /**
   * Custom header button in place of «Изменить» — the nation
   * subscreen's «Показать на карте» (unit 14c).
   */
  action?: ReactNode;
  /**
   * Present on the own «Штаб» card only: the flag becomes an upload
   * control. Absent (Registry subscreen) — the flag is read-only.
   */
  imageEditor?: NationImageEditor;
}) {
  return (
    <CardBlock testId="nation-card-header">
      <div
        style={{
          display: 'flex',
          gap: SPACING['space-4'],
          alignItems: 'center',
        }}
      >
        <ImageSlot
          kind="flag"
          size="shtab"
          src={nation.flag_url}
          stubColor={nation.color_hex}
          alt={`Флаг ${nation.name}`}
          interactive={imageEditor !== undefined}
          hintLines={
            imageEditor !== undefined
              ? imageSlotHint(
                  'flag',
                  nation.flag_url !== null,
                  imageEditor.rules,
                )
              : undefined
          }
          onPick={
            imageEditor !== undefined
              ? (file) => imageEditor.onUpload('flag', file)
              : undefined
          }
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              ...TEXT_STYLES['label'],
              color: tokenVar('ink-muted'),
            }}
          >
            {nation.short_name}
          </div>
          <div
            style={{
              ...TEXT_STYLES['display-lg'],
              color: tokenVar('ink'),
              marginTop: 2,
            }}
          >
            {nation.name}
          </div>
          {/* PNG 08 — motto in «» and the colour swatch share one line. */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: SPACING['space-3'],
              marginTop: 4,
              ...TEXT_STYLES['body'],
            }}
          >
            {nation.motto && (
              <span
                style={{ fontStyle: 'italic', color: tokenVar('ink-muted') }}
              >
                «{nation.motto}»
              </span>
            )}
            <ColorSwatch hex={nation.color_hex} />
          </div>
        </div>
        <div style={{ flexShrink: 0 }}>
          {action ?? (onEdit && <EditButton onClick={onEdit} />)}
        </div>
      </div>
    </CardBlock>
  );
}

/** PNG 08 — the header button: 36 px `surface-inset`, ink pencil. */
function EditButton({ onClick }: { onClick: () => void }) {
  const [focused, setFocused] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: SPACING['space-2'],
        height: SIZES['button-h'],
        padding: '0 16px',
        boxSizing: 'border-box',
        border: 'none',
        borderRadius: RADII['radius-md'],
        background: tokenVar('surface-inset'),
        color: tokenVar('ink'),
        ...TEXT_STYLES['body'],
        cursor: 'pointer',
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      <PencilIcon />
      Изменить
    </button>
  );
}
