/**
 * PersonCell — `person` column: round 24px avatar with a neutral round
 * fallback when `avatar_url` is null or fails to load; name truncated
 * (Spec 5.5).
 *
 * Since unit 11 the cell carries the «Подсказка» (UI Spec 3.4): the
 * player name and the rows «Дата регистрации», «Уровень», «Судейский
 * рейтинг», «Государство» — all read from the row's own cells
 * (`cells` prop, fed by RegistryTable), so the tip makes NO request.
 * No «click to open» line: a player cannot be opened yet.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Icon16User } from '@vkontakte/icons';

import {
  SPACING,
  TEXT_STYLES,
  Tooltip,
  TooltipRow,
  tokenVar,
} from '../../../../shared/ui';
import {
  isDateCell,
  isNationCell,
  isPersonCell,
  type RegistryCell,
  type RegistryPersonCell,
} from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

const PLAYER_TIP_TEXTS = {
  joined: 'Дата регистрации',
  level: 'Уровень',
  judgeRating: 'Судейский рейтинг',
  nation: 'Государство',
  noNation: 'нет государства',
};

/** Cell → display string: the date cell's text or a plain number. */
function tipCellText(cell: RegistryCell | undefined): string | null {
  const value = cell ?? null;
  if (isDateCell(value)) {
    return value.text;
  }
  if (typeof value === 'number') {
    return String(value);
  }
  return null;
}

function PlayerTip({
  person,
  cells,
}: {
  person: RegistryPersonCell;
  cells: Record<string, RegistryCell> | undefined;
}) {
  const nation = cells?.nation ?? null;
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-2'],
      }}
    >
      <div style={{ ...TEXT_STYLES['heading'], color: tokenVar('ink') }}>
        {person.name}
      </div>
      <TooltipRow
        label={PLAYER_TIP_TEXTS.joined}
        value={tipCellText(cells?.joined) ?? REGISTRY_TEXTS.emptyValue}
      />
      <TooltipRow
        label={PLAYER_TIP_TEXTS.level}
        value={tipCellText(cells?.level) ?? REGISTRY_TEXTS.emptyValue}
      />
      <TooltipRow
        label={PLAYER_TIP_TEXTS.judgeRating}
        value={tipCellText(cells?.judge_rating) ?? REGISTRY_TEXTS.emptyValue}
      />
      <TooltipRow
        label={PLAYER_TIP_TEXTS.nation}
        value={
          isNationCell(nation) ? nation.name : PLAYER_TIP_TEXTS.noNation
        }
      />
    </div>
  );
}

export function PersonCell({
  value,
  cells,
}: {
  value: RegistryCell;
  /** The whole row's cells — the player tip reads them, no request. */
  cells?: Record<string, RegistryCell>;
}) {
  const [failed, setFailed] = useState(false);
  const person = isPersonCell(value) ? value : null;

  if (!person) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  const showImage = person.avatar_url !== null && !failed;

  const face: ReactNode = (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0,
        maxWidth: '100%',
      }}
    >
      {showImage ? (
        <img
          src={person.avatar_url ?? ''}
          alt=""
          width={24}
          height={24}
          style={{ borderRadius: '50%', flexShrink: 0 }}
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          aria-hidden
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--vkui--color_background_secondary)',
            border: '1px solid var(--vkui--color_separator_primary)',
          }}
        >
          <Icon16User fill="var(--vkui--color_icon_secondary)" />
        </span>
      )}
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {person.name}
      </span>
    </span>
  );

  return (
    <Tooltip content={<PlayerTip person={person} cells={cells} />}>
      {face}
    </Tooltip>
  );
}
