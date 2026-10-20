/**
 * NationCardHeader — the screen title of the «Штаб» card (UI Spec
 * 9.1, mockup «Main»): flag 96×64 (`FlagStub` for a legacy nation
 * without one), the «ГОСУДАРСТВО · краткое название» label line, the
 * name in `display-lg`, the motto in italics when set, the colour
 * swatch with HEX, and the «Изменить» button on the right (the pencil
 * icon; the edit behaviour itself lives in PanelNationHome). An
 * `action` node replaces that button — the nation subscreen shows
 * «Показать на карте» there (unit 14c).
 */

import type { ReactNode } from 'react';
import { Button } from '@vkontakte/vkui';

import type { NationDTO, NationPublicDTO } from '../../../../shared/types';
import {
  ColorSwatch,
  FlagStub,
  PencilIcon,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { CardBlock } from './CardBlock';

export function NationCardHeader({
  nation,
  onEdit,
  action,
}: {
  nation: NationDTO | NationPublicDTO;
  onEdit?: () => void;
  /**
   * Custom header button in place of «Изменить» — the nation
   * subscreen's «Показать на карте» (unit 14c).
   */
  action?: ReactNode;
}) {
  return (
    <CardBlock testId="nation-card-header">
      <div style={{ display: 'flex', gap: SPACING['space-4'] }}>
        {nation.flag_url ? (
          <img
            src={nation.flag_url}
            alt={`Флаг ${nation.name}`}
            width={96}
            height={64}
            style={{
              borderRadius: RADII['radius-sm'],
              objectFit: 'cover',
              flexShrink: 0,
              display: 'block',
            }}
          />
        ) : (
          <FlagStub variant="card" />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{ ...TEXT_STYLES['label'], color: tokenVar('ink-muted') }}
          >
            Государство{nation.short_name ? ` · ${nation.short_name}` : ''}
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
          {nation.motto && (
            <div
              style={{
                ...TEXT_STYLES['body'],
                fontStyle: 'italic',
                color: tokenVar('ink-muted'),
                marginTop: 4,
              }}
            >
              {nation.motto}
            </div>
          )}
          <div style={{ marginTop: SPACING['space-2'] }}>
            <ColorSwatch hex={nation.color_hex} />
          </div>
        </div>
        <div style={{ flexShrink: 0 }}>
          {action ??
            (onEdit && (
              <Button
                size="s"
                mode="secondary"
                before={<PencilIcon />}
                onClick={onEdit}
              >
                Изменить
              </Button>
            ))}
        </div>
      </div>
    </CardBlock>
  );
}
