/**
 * OrdersBlock — the «Приказы» block of the headquarters card
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation;
 * UI Spec 9.1, mockup «Main», boards 10/10b, version 0.10.0 unit 7b).
 *
 * A surface block with the shared BlockTitle («Приказы», document
 * icon) whose trailing slot carries the «Подать приказ» button.
 * Below it sit the two order badges — «Мои приказы» and «Приказы
 * других игроков» — that replaced the stat tiles and the «Ожидают
 * вердикт» list in 0.10.0: the judge path now runs through the
 * Registry (badge → orders tab → row → order window).
 *
 * «Мои приказы» counts the player's own submitted orders without a
 * verdict (`unresolved_orders` from GET /orders/rules — the same
 * route the composer reads); «Приказы других игроков» counts the
 * orders assigned to the player for judging (the GET /orders/assigned
 * list length — the endpoint is unpaginated and returns the whole
 * queue). A zero count gets no circle, counts of 100+ show «99+»;
 * a failed or in-flight fetch leaves the badge numberless — never
 * «0», never an error popup. Both counts load on mount and refetch
 * when `ordersRefreshKey` bumps (an order submitted, a verdict
 * written or rejected).
 *
 * A badge click hands the host an entry request for the Registry's
 * orders tab with the preset filter («Мои приказы» — the nation
 * dropdown set to my short name, «Приказы других игроков» — the
 * «Назначены мне» extension on «Да»); navigation itself lives in
 * AppShell, which stores the request and pushes '/registry'.
 */

import { useState } from 'react';
import { Button } from '@vkontakte/vkui';

import {
  BlockTitle,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import type { RegistryEntryRequest } from '../../03_registry/lib/entryRequest';
import { useAssignedOrders } from '../hooks/useAssignedOrders';
import { useOrderRules } from '../hooks/useOrderRules';
import { ORDERS_TABLE_ID } from '../registryFilters';
import { ORDERS_TEXTS } from '../texts';
import { useOrdersUi } from '../OrdersUiProvider';

/** A count of 100 or more collapses to «99+» (board 10b). */
const countText = (count: number) => (count >= 100 ? '99+' : String(count));

export function OrdersBlock({
  nationShortName,
  onOpenRegistry,
}: {
  /** My nation's short name — the «Мои приказы» preset's dropdown value
   * (the Registry's nation options list short names, Spec 03_registry 3.3). */
  nationShortName: string;
  /** Hands the badge's entry request to the host (AppShell stores it
   * and navigates to the Registry). */
  onOpenRegistry: (request: RegistryEntryRequest) => void;
}) {
  const { openComposer, ordersRefreshKey } = useOrdersUi();
  const rulesState = useOrderRules(ordersRefreshKey);
  const assigned = useAssignedOrders(ordersRefreshKey);

  const mineCount =
    rulesState.status === 'ready' ? rulesState.rules.unresolved_orders : null;
  const assignedCount =
    assigned.status === 'ready' ? assigned.items.length : null;

  return (
    <section
      data-testid="orders-block"
      style={{
        background: tokenVar('surface'),
        borderRadius: RADII['radius-lg'],
        padding: SPACING['space-4'],
      }}
    >
      <BlockTitle
        icon="document"
        title={ORDERS_TEXTS.blockTitle}
        trailing={
          <Button size="s" mode="secondary" onClick={openComposer}>
            {ORDERS_TEXTS.submitButton}
          </Button>
        }
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: SPACING['space-2'],
        }}
      >
        <OrderBadge
          testId="orders-badge-mine"
          label={ORDERS_TEXTS.badgeMine}
          count={mineCount}
          onClick={() =>
            onOpenRegistry({
              tab: ORDERS_TABLE_ID,
              preset: { nation: nationShortName },
            })
          }
        />
        <OrderBadge
          testId="orders-badge-assigned"
          label={ORDERS_TEXTS.badgeOthers}
          count={assignedCount}
          onClick={() =>
            onOpenRegistry({
              tab: ORDERS_TABLE_ID,
              preset: { assignedToMe: true },
            })
          }
        />
      </div>
    </section>
  );
}

function OrderBadge({
  testId,
  label,
  count,
  onClick,
}: {
  testId: string;
  label: string;
  /** null — the count is not loaded (in-flight or failed): no circle. */
  count: number | null;
  onClick: () => void;
}) {
  // `hot` paints the hover state, `focused` the keyboard focus ring.
  const [hot, setHot] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <button
      type="button"
      // The count circle must not leak into the accessible name.
      aria-label={label}
      data-testid={testId}
      onClick={onClick}
      onMouseEnter={() => setHot(true)}
      onMouseLeave={() => setHot(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        minWidth: 0,
        padding: '10px 12px',
        background: tokenVar(hot ? 'surface-raised' : 'surface-inset'),
        border: 'none',
        borderRadius: RADII['radius-md'],
        cursor: 'pointer',
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      <span
        style={{
          ...TEXT_STYLES['body'],
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          color: tokenVar('ink'),
        }}
      >
        {label}
      </span>
      {count !== null && count > 0 && (
        <span
          data-testid={`${testId}-count`}
          style={{
            ...TEXT_STYLES['figure'],
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: 22,
            height: 22,
            padding: '0 6px',
            boxSizing: 'border-box',
            flexShrink: 0,
            fontSize: 12,
            lineHeight: '16px',
            background: tokenVar('signal'),
            color: tokenVar('on-signal'),
            borderRadius: RADII['radius-pill'],
          }}
        >
          {countText(count)}
        </span>
      )}
    </button>
  );
}
