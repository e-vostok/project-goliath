/**
 * NationStatsRow — the row of four stat tiles under the header
 * (UI Spec 9.1, mockup «Main»): «Провинции» (count), «Уровень» and
 * «Судейский рейтинг» (the Registry's players row for the owner —
 * «—» until it is found), «Неразрешённые приказы» («N» plus a muted
 * «из M» — the counter and the limit come from GET /orders/rules,
 * the same source the order composer reads; the client never
 * hard-codes the limit).
 */

import type { NationDTO } from '../../../../shared/types';
import {
  SPACING,
  StatTile,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { useOrderRules } from '../../../04_orders/hooks/useOrderRules';
import { useOwnStats } from './useOwnStats';

const DASH = '—';

function statValue(value: number | null): string | number {
  return value === null ? DASH : value;
}

export function NationStatsRow({ nation }: { nation: NationDTO }) {
  const own = useOwnStats(nation);
  const orderRules = useOrderRules();
  const rules = orderRules.status === 'ready' ? orderRules.rules : null;

  return (
    <div
      data-testid="nation-stats-row"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: SPACING['space-3'],
      }}
    >
      <StatTile label="Провинции" value={nation.province_ids.length} />
      <StatTile
        label="Уровень"
        value={statValue(own.stats?.level ?? null)}
      />
      <StatTile
        label="Судейский рейтинг"
        value={statValue(own.stats?.judgeRating ?? null)}
        accent
      />
      <StatTile
        label="Неразрешённые приказы"
        value={
          rules === null ? (
            DASH
          ) : (
            <>
              {rules.unresolved_orders}{' '}
              <span
                style={{
                  ...TEXT_STYLES['figure'],
                  color: tokenVar('ink-muted'),
                }}
              >
                из {rules.max_unresolved_orders}
              </span>
            </>
          )
        }
      />
    </div>
  );
}
