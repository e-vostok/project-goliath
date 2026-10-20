/**
 * NationSubscreen — the nation subscreen of the «Реестр» (UI Spec
 * 9.3, version 0.9.0 unit 14c). Address: `#/registry/nation-<id>`.
 *
 * The window keeps «Реестр» as the active top-bar tab; the Registry
 * itself stays mounted behind it (hidden, state kept). One request —
 * `api.getNation` (the public card) — and the same building blocks as
 * the «Штаб» card (unit 8b): `NationCardHeader` with «Показать на
 * карте» in place of «Изменить», THREE `StatTile`s («Провинции»,
 * «Уровень», «Судейский рейтинг» — the «Приказы» tile is absent), the
 * «Глава государства» + «Территория» row (province chips by name,
 * capital first) and «Описание» with the history link. The public
 * DTO carries no gender / succession / anthem — nothing here shows
 * them.
 *
 * The path chain: opened from a table row — «Реестр / <вкладка> /
 * <название>» (the tab title arrives as router state `fromTab`);
 * opened by a bare link — «Реестр / Государство · <название>»
 * («Реестр / Государство» while the card loads). 404 shows
 * «Государство не найдено» with its own «← Реестр»; other failures
 * get the shared ErrorState + «Повторить».
 */

import { useEffect, useState } from 'react';
import { Button } from '@vkontakte/vkui';
import { Icon16ArrowLeftOutline } from '@vkontakte/icons';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type { NationPublicDTO } from '../../../shared/types';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  SPACING,
  StatTile,
  Subscreen,
} from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { DescriptionBlock } from './card/DescriptionBlock';
import { LeaderBlock } from './card/LeaderBlock';
import { NationCardHeader } from './card/NationCardHeader';
import { TerritoryBlock } from './card/TerritoryBlock';

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; nation: NationPublicDTO }
  | { status: 'notfound' }
  | { status: 'error'; error: unknown };

export function NationSubscreen({
  nationId,
  fromTab,
  onBack,
  onShowOnMap,
}: {
  /** Nation UUID — the `nation-<id>` route segment minus the prefix. */
  nationId: string;
  /**
   * Router state of the row click — the Registry tab the player came
   * from («Игроки», «Государства», …); null on a bare link.
   */
  fromTab: string | null;
  /** «← Реестр» — back to the Registry window (state kept). */
  onBack: () => void;
  /**
   * «Показать на карте» — opens `#/map`; a non-null argument is the
   * capital province id the map selects and centres on.
   */
  onShowOnMap: (capitalProvinceId: number | null) => void;
}) {
  const { token } = useSession();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let alive = true;
    setState({ status: 'loading' });
    api
      .getNation(token, nationId)
      .then((nation) => {
        if (alive) {
          setState({ status: 'ready', nation });
        }
      })
      .catch((error: unknown) => {
        if (!alive) {
          return;
        }
        setState(
          error instanceof ApiError &&
            (error.status === 404 || error.code === 'NATION_NOT_FOUND')
            ? { status: 'notfound' }
            : { status: 'error', error },
        );
      });
    return () => {
      alive = false;
    };
  }, [token, nationId, attempt]);

  const nation = state.status === 'ready' ? state.nation : null;
  // The chain: from a table row the Registry tab name is the middle
  // segment; on a bare link «Государство» takes that place, joined
  // with the name once it is known (UI Spec 9.3).
  const trail =
    nation === null
      ? fromTab !== null
        ? [fromTab]
        : ['Государство']
      : fromTab !== null
        ? [fromTab, nation.name]
        : [`Государство · ${nation.name}`];

  return (
    <Subscreen parentLabel="Реестр" trail={trail} onBack={onBack}>
      {state.status === 'loading' && <LoadingState height={200} />}

      {state.status === 'error' && (
        <ErrorState
          reason={errorText(state.error)}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}

      {state.status === 'notfound' && (
        <EmptyState
          text="Государство не найдено"
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

      {nation !== null && (
        <div
          data-testid="nation-subscreen"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: SPACING['space-3'],
          }}
        >
          <NationCardHeader
            nation={nation}
            action={
              <Button
                size="s"
                mode="secondary"
                onClick={() => onShowOnMap(nation.capital_province_id)}
              >
                Показать на карте
              </Button>
            }
          />
          <div
            data-testid="nation-subscreen-stats"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
              gap: SPACING['space-3'],
            }}
          >
            <StatTile label="Провинции" value={nation.province_ids.length} />
            <StatTile label="Уровень" value={nation.level} />
            <StatTile
              label="Судейский рейтинг"
              value={nation.judge_rating}
              accent
            />
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '3fr 2fr',
              gap: SPACING['space-3'],
              alignItems: 'start',
            }}
          >
            <LeaderBlock nation={nation} />
            <TerritoryBlock nation={nation} />
          </div>
          <DescriptionBlock nation={nation} />
        </div>
      )}
    </Subscreen>
  );
}
