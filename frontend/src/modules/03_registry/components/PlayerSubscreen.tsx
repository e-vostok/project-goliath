/**
 * PlayerSubscreen — the «Игрок» subscreen of the «Реестр» (UI Spec
 * 9.7, version 0.10.0 unit 8b, boards 12 and 12b). Address:
 * `#/registry/player-<N>` — the player's public Registry number (the
 * players-table row key `p<N>` without `p`; INV-R2 — no `player_id`,
 * no `vk_user_id` anywhere).
 *
 * The window keeps «Реестр» as the active top-bar tab; the Registry
 * itself stays mounted behind it (hidden, state kept). One request —
 * `registryApi.getPlayer` — and the card shows exactly what the
 * players table's row carries: the avatar (VK photo or the neutral
 * circle when `avatar_url` is null / `is_fallback`), the name (the
 * fallback name when `is_fallback`), «Дата регистрации», «Уровень»,
 * «Судейский рейтинг» as the table's gauge (zero-centred bar, −100…
 * +100) and «Государство» (small flag + short name — a link to the
 * nation subscreen when the cell id is set; «Государства нет» for a
 * nation-less player).
 *
 * The path chain is «Реестр / Игроки / <имя>» — a person cell exists
 * only in the players table, so the middle segment is its tab (the
 * router-state `fromTab` of a row click, «Игроки» on a bare link).
 * 404 shows «Игрок не найден» with its own «← Реестр»; other
 * failures get the shared ErrorState + «Повторить».
 */

import type { ReactNode } from 'react';
import { Button } from '@vkontakte/vkui';
import { Icon16ArrowLeftOutline } from '@vkontakte/icons';

import { errorText } from '../../../shared/errorTexts';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  NationLabel,
  SPACING,
  Subscreen,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { CardBlock } from '../../00_core/components/card/CardBlock';
import { usePlayerProfile } from '../hooks/usePlayerProfile';
import type { RegistryPlayerDTO } from '../types';
import { GaugeCell } from './cells/GaugeCell';
import { NationOpenLink } from './cells/NationCell';
import { PlayerAvatar } from './PlayerAvatar';

const PLAYER_TEXTS = {
  defaultTab: 'Игроки',
  notFound: 'Игрок не найден',
  joined: 'Дата регистрации',
  level: 'Уровень',
  judgeRating: 'Судейский рейтинг',
  nation: 'Государство',
  noNation: 'Государства нет',
};

/** A «label : value» line of the card — `div`s, so the gauge fits. */
function PlayerRow({
  label,
  value,
  valueWidth,
}: {
  label: string;
  value: ReactNode;
  /** Fixed width of the value side — the gauge bar needs room. */
  valueWidth?: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: SPACING['space-3'],
      }}
    >
      <div style={{ color: tokenVar('ink-muted'), flexShrink: 0 }}>
        {label}
      </div>
      <div
        style={{
          ...TEXT_STYLES['body'],
          color: tokenVar('ink'),
          textAlign: 'right',
          minWidth: 0,
          width: valueWidth,
        }}
      >
        {value}
      </div>
    </div>
  );
}

/** «Государство»: flag + short name, a link when the cell has an id. */
function PlayerNation({
  nation,
  onOpenNation,
}: {
  nation: RegistryPlayerDTO['nation'];
  onOpenNation: (nationId: string) => void;
}) {
  if (nation === null) {
    return <>{PLAYER_TEXTS.noNation}</>;
  }
  const label = (
    <NationLabel
      name={nation.name}
      flagUrl={nation.flag_url}
      color={nation.color}
      size="cell"
    />
  );
  // An `id: null` snapshot stays plain text — nothing to open.
  const nationId = nation.id;
  if (nationId === null) {
    return label;
  }
  return (
    <NationOpenLink onOpen={() => onOpenNation(nationId)}>
      {label}
    </NationOpenLink>
  );
}

export function PlayerSubscreen({
  number,
  fromTab,
  onBack,
  onOpenNation,
}: {
  /** The player's public Registry number — `player-<N>` minus the prefix. */
  number: number;
  /**
   * Router state of the row click — the Registry tab the player came
   * from («Игроки»); null on a bare link.
   */
  fromTab: string | null;
  /** «← Реестр» — back to the Registry window (state kept). */
  onBack: () => void;
  /** The nation line opens the nation subscreen by its id. */
  onOpenNation: (nationId: string) => void;
}) {
  const { state, reload } = usePlayerProfile(number);

  const player = state.status === 'ready' ? state.player : null;
  // A person cell exists only in the players table — the middle
  // segment is always its tab («Игроки» also on a bare link).
  const trail =
    player === null
      ? [fromTab ?? PLAYER_TEXTS.defaultTab]
      : [fromTab ?? PLAYER_TEXTS.defaultTab, player.person.name];

  return (
    <Subscreen parentLabel="Реестр" trail={trail} onBack={onBack}>
      {state.status === 'loading' && <LoadingState height={200} />}

      {state.status === 'error' && (
        <ErrorState
          reason={errorText(state.error)}
          onRetry={reload}
        />
      )}

      {state.status === 'notfound' && (
        <EmptyState
          text={PLAYER_TEXTS.notFound}
          action={
            <Button
              size="s"
              mode="secondary"
              before={<Icon16ArrowLeftOutline width={16} height={16} />}
              onClick={onBack}
              aria-label="← Реестр"
            >
              Реестр
            </Button>
          }
        />
      )}

      {player !== null && (
        <CardBlock testId="player-subscreen">
          <div
            data-testid="player-subscreen-header"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: SPACING['space-4'],
            }}
          >
            <PlayerAvatar person={player.person} size={64} />
            <div
              style={{
                ...TEXT_STYLES['display-lg'],
                color: tokenVar('ink'),
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {player.person.name}
            </div>
          </div>
          <div
            data-testid="player-subscreen-rows"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: SPACING['space-2'],
              marginTop: SPACING['space-4'],
            }}
          >
            <PlayerRow
              label={PLAYER_TEXTS.joined}
              value={player.joined.text}
            />
            <PlayerRow label={PLAYER_TEXTS.level} value={player.level} />
            <PlayerRow
              label={PLAYER_TEXTS.judgeRating}
              valueWidth={200}
              value={
                <GaugeCell
                  value={player.judge_rating}
                  scaleMin={null}
                  scaleMax={null}
                />
              }
            />
            <PlayerRow
              label={PLAYER_TEXTS.nation}
              value={
                <PlayerNation
                  nation={player.nation}
                  onOpenNation={onOpenNation}
                />
              }
            />
          </div>
        </CardBlock>
      )}
    </Subscreen>
  );
}
