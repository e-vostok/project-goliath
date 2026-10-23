/**
 * NationCard — the «Штаб» state card (UI Spec 9.1, mockup «Main»,
 * boards 8/10): the header (flag, names, motto, colour, «Изменить»),
 * «Глава государства» and «Территория» side by side 3 : 2, then
 * «Описание». The stat-tiles row left the card in 0.10.0 (unit 7b —
 * the order badges inside «Приказы» carry its counts; the spot stays
 * empty for future mechanics). Every block is `surface`/`radius-lg`/
 * `space-4`; the screen width stays inside `win-screen` (910 px).
 */

import type { NationDTO } from '../../../../shared/types';
import { SPACING } from '../../../../shared/ui';
import { DescriptionBlock } from './DescriptionBlock';
import { LeaderBlock } from './LeaderBlock';
import { NationCardHeader } from './NationCardHeader';
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
