/**
 * TerritoryBlock — «Территория» on the nation card (UI Spec 9.1,
 * mockup «Main»): one `ProvinceChip` per province BY NAME — numbers
 * are never shown (Spec 8). The capital goes first with «★», in the
 * «★ Столица (Провинция)» form when its name differs from the
 * province name.
 *
 * Names come from the map manifest via `useProvinceNames` (shared
 * session cache — no second download after the map/picker). While
 * they load, same-size neutral placeholders stand in; a province
 * absent from the manifest shows «Провинция» without its number.
 */

import type { NationDTO, NationPublicDTO } from '../../../../shared/types';
import {
  BlockTitle,
  ProvinceChip,
  RADII,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { useProvinceNames } from '../../../01_map/hooks/useProvinceNames';
import { CardBlock } from './CardBlock';

/** Same-size neutral placeholder — stands in for a name still loading. */
function ProvinceChipPlaceholder() {
  return (
    <span
      data-testid="province-chip-placeholder"
      aria-hidden="true"
      style={{
        ...TEXT_STYLES['body'],
        display: 'inline-flex',
        alignItems: 'center',
        height: 24,
        lineHeight: '16px',
        padding: '0 8px',
        boxSizing: 'border-box',
        background: tokenVar('surface-inset'),
        borderRadius: RADII['radius-sm'],
        color: 'transparent',
      }}
    >
      Провинция
    </span>
  );
}

export function TerritoryBlock({
  nation,
}: {
  nation: NationDTO | NationPublicDTO;
}) {
  const { loading, names } = useProvinceNames();
  const capitalId = nation.capital_province_id;

  // Capital first (INV of Spec 8), the rest in the nation's own order.
  const ordered = [
    ...(capitalId !== null && nation.province_ids.includes(capitalId)
      ? [capitalId]
      : []),
    ...nation.province_ids.filter((id) => id !== capitalId),
  ];

  return (
    <CardBlock testId="nation-territory-block">
      <BlockTitle icon="map" title="Территория" />
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '6px 6px',
          alignItems: 'center',
        }}
      >
        {ordered.length === 0 ? (
          <span
            style={{ ...TEXT_STYLES['body'], color: tokenVar('ink-muted') }}
          >
            Нет
          </span>
        ) : loading ? (
          ordered.map((id) => <ProvinceChipPlaceholder key={id} />)
        ) : (
          ordered.map((id) => (
            <ProvinceChip
              key={id}
              name={names.get(id) ?? 'Провинция'}
              capital={id === capitalId}
              capitalName={nation.capital_name ?? undefined}
            />
          ))
        )}
      </div>
    </CardBlock>
  );
}
