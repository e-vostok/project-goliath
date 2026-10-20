/**
 * NationCard — the «Штаб» state card (UI Spec 9.1, mockup «Main»):
 * the header (flag, names, motto, colour, «Изменить»), the row of
 * four stat tiles, «Глава государства» and «Территория» side by side
 * 3 : 2, then «Описание». Every block is `surface`/`radius-lg`/
 * `space-4`; the screen width stays inside `win-screen` (910 px).
 */

import type { NationDTO } from '../../../../shared/types';
import { SPACING } from '../../../../shared/ui';
import { DescriptionBlock } from './DescriptionBlock';
import { LeaderBlock } from './LeaderBlock';
import { NationCardHeader } from './NationCardHeader';
import { NationStatsRow } from './NationStatsRow';
import { TerritoryBlock } from './TerritoryBlock';

export function NationCard({
  nation,
  onEdit,
}: {
  nation: NationDTO;
  onEdit: () => void;
}) {
  return (
    <>
      <NationCardHeader nation={nation} onEdit={onEdit} />
      <NationStatsRow nation={nation} />
      <div
        data-testid="nation-card-row"
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
    </>
  );
}
