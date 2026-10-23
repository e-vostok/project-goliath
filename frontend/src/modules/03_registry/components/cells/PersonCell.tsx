/**
 * PersonCell — `person` column: round 24px avatar with a neutral round
 * fallback when `avatar_url` is null or fails to load; name truncated
 * (Spec 5.5).
 *
 * Since unit 11 the cell carries the «Подсказка» (UI Spec 3.4, board
 * 9b): the small avatar and the player name and the rows «Дата
 * регистрации», «Уровень», «Судейский рейтинг», «Государство» — all
 * read from the row's own cells (`cells` prop, fed by RegistryTable),
 * so the tip makes NO request.
 *
 * Since version 0.10.0 (unit 8b) a cell whose row key resolves to a
 * players-table number (`p<N>`) is a button — same look as the plain
 * cell, `action` text colour, underline on hover/focus — that opens
 * the «Игрок» subscreen, and the tip ends with the «Нажмите на имя…»
 * line like the nation tip. A cell without a resolvable number stays
 * plain text; its tip carries no hint.
 */

import type { ReactNode } from 'react';

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
import { PlayerAvatar } from '../PlayerAvatar';
import { NationOpenLink } from './NationCell';

const PLAYER_TIP_TEXTS = {
  joined: 'Дата регистрации',
  level: 'Уровень',
  judgeRating: 'Судейский рейтинг',
  nation: 'Государство',
  noNation: 'нет государства',
  openHint: 'Нажмите на имя, чтобы открыть игрока',
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
  openable,
}: {
  person: RegistryPersonCell;
  cells: Record<string, RegistryCell> | undefined;
  /** The cell opens the subscreen — the tip gets the «Нажмите…» line. */
  openable: boolean;
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
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-2'],
        }}
      >
        <PlayerAvatar person={person} size={32} />
        <div style={{ ...TEXT_STYLES['heading'], color: tokenVar('ink') }}>
          {person.name}
        </div>
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
      {openable && (
        <>
          <div
            aria-hidden
            style={{ height: 1, background: tokenVar('line') }}
          />
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            {PLAYER_TIP_TEXTS.openHint}
          </div>
        </>
      )}
    </div>
  );
}

export function PersonCell({
  value,
  cells,
  onOpen,
}: {
  value: RegistryCell;
  /** The whole row's cells — the player tip reads them, no request. */
  cells?: Record<string, RegistryCell>;
  /**
   * Opens the «Игрок» subscreen (0.10.0 unit 8b) — set by RegistryTable
   * only when the row key resolves to a players-table number `p<N>`.
   */
  onOpen?: () => void;
}) {
  const person = isPersonCell(value) ? value : null;

  if (!person) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

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
      <PlayerAvatar person={person} size={24} />
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

  const body =
    onOpen === undefined ? (
      face
    ) : (
      <NationOpenLink onOpen={onOpen}>{face}</NationOpenLink>
    );

  return (
    <Tooltip
      content={
        <PlayerTip
          person={person}
          cells={cells}
          openable={onOpen !== undefined}
        />
      }
    >
      {body}
    </Tooltip>
  );
}
