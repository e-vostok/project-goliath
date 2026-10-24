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
 * players table's row carries: the 96 px avatar (VK photo or the
 * neutral silhouette when `avatar_url` is null / `is_fallback`), the
 * «ИГРОК» caption, the name (the fallback name when `is_fallback`),
 * then three tiles — «РЕГИСТРАЦИЯ», «УРОВЕНЬ», «РЕЙТИНГ» (the rating
 * number in `signal-ink`, no gauge) — then the «ГОСУДАРСТВО» card:
 * the flag and the short name as a link row with a chevron when the
 * cell id is set, «Государства нет» for a nation-less player (12b).
 *
 * The path chain is «Реестр / Игроки / <имя>» — a person cell exists
 * only in the players table, so the middle segment is its tab (the
 * router-state `fromTab` of a row click, «Игроки» on a bare link).
 * 404 shows «Игрок не найден» with its own «← Реестр»; other
 * failures get the shared ErrorState + «Повторить».
 */

import { Button } from '@vkontakte/vkui';
import { Icon16ArrowLeftOutline } from '@vkontakte/icons';

import { errorText } from '../../../shared/errorTexts';
import {
  BlockTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  NationLabel,
  SPACING,
  StatTile,
  Subscreen,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { CardBlock } from '../../00_core/components/card/CardBlock';
import { usePlayerProfile } from '../hooks/usePlayerProfile';
import type { RegistryPlayerDTO } from '../types';
import { NationOpenLink } from './cells/NationCell';
import { PlayerAvatar } from './PlayerAvatar';

const PLAYER_TEXTS = {
  defaultTab: 'Игроки',
  notFound: 'Игрок не найден',
  caption: 'Игрок',
  joined: 'Регистрация',
  level: 'Уровень',
  judgeRating: 'Рейтинг',
  nation: 'Государство',
  noNation: 'Государства нет',
};

/** «Государство» — the 48×32 flag and the short name as a link row. */
function PlayerNation({
  nation,
  onOpenNation,
}: {
  nation: RegistryPlayerDTO['nation'];
  onOpenNation: (nationId: string) => void;
}) {
  if (nation === null) {
    return (
      <div style={{ color: tokenVar('ink-muted') }}>
        {PLAYER_TEXTS.noNation}
      </div>
    );
  }
  const label = (
    <NationLabel
      name={nation.name}
      flagUrl={nation.flag_url}
      color={nation.color}
      size="sub"
    />
  );
  // An `id: null` snapshot stays a plain row — nothing to open.
  if (nation.id === null) {
    return label;
  }
  const nationId = nation.id;
  return (
    <NationOpenLink onOpen={() => onOpenNation(nationId)}>
      <span
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        {label}
        <span style={{ flexGrow: 1 }} />
        <svg
          width={16}
          height={16}
          viewBox="0 0 16 16"
          fill="none"
          stroke={tokenVar('ink-faint')}
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ flexShrink: 0 }}
        >
          <path d="M6 3l5 5-5 5" />
        </svg>
      </span>
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
        <>
          <CardBlock testId="player-subscreen">
            <div
              data-testid="player-subscreen-header"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: SPACING['space-4'],
              }}
            >
              <PlayerAvatar person={player.person} size={96} />
              <div style={{ flexGrow: 1, minWidth: 0 }}>
                <div
                  style={{
                    ...TEXT_STYLES['label'],
                    color: tokenVar('ink-muted'),
                  }}
                >
                  {PLAYER_TEXTS.caption}
                </div>
                <h1
                  style={{
                    margin: '2px 0 0',
                    ...TEXT_STYLES['display-lg'],
                    color: tokenVar('ink'),
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {player.person.name}
                </h1>
              </div>
            </div>
          </CardBlock>

          <div
            data-testid="player-subscreen-stats"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
              gap: SPACING['space-3'],
            }}
          >
            <StatTile
              label={PLAYER_TEXTS.joined}
              value={
                <span style={{ fontSize: 20 }}>{player.joined.text}</span>
              }
            />
            <StatTile label={PLAYER_TEXTS.level} value={player.level} />
            <StatTile
              label={PLAYER_TEXTS.judgeRating}
              accent
              value={player.judge_rating}
            />
          </div>

          <CardBlock testId="player-subscreen-nation">
            <BlockTitle icon="flag" title={PLAYER_TEXTS.nation} />
            <PlayerNation
              nation={player.nation}
              onOpenNation={onOpenNation}
            />
          </CardBlock>
        </>
      )}
    </Subscreen>
  );
}
