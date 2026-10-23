/**
 * NationStatsRow — the row of stat tiles under the header (UI Spec
 * 9.1, mockup «Main»): «Провинции» (count) and «Неразрешённые
 * приказы» («N» plus a muted «из M» — the counter and the limit come
 * from GET /orders/rules, the same source the order composer reads;
 * the client never hard-codes the limit). «Уровень» and «Судейский
 * рейтинг» are the PLAYER's numbers — they left the nation card in
 * 0.10.0 (unit 8b) and now live on the «Игрок» subscreen.
 */

import type { NationDTO } from '../../../../shared/types';
import {
  SPACING,
  StatTile,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { useOrderRules } from '../../../04_orders/hooks/useOrderRules';

const DASH = '—';

export function NationStatsRow({ nation }: { nation: NationDTO }) {
  const orderRules = useOrderRules();
  const rules = orderRules.status === 'ready' ? orderRules.rules : null;

  return (
    <div
      data-testid="nation-stats-row"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
        gap: SPACING['space-3'],
      }}
    >
      <StatTile label="Провинции" value={nation.province_ids.length} />
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
