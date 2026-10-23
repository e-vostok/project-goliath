/**
 * OrdersBlock — the «Приказы» block of the headquarters card
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation;
 * UI Spec 9.1, mockup board 08, version 0.10.0 units 7b + 13).
 *
 * A surface block with the shared BlockTitle («Приказы», document
 * icon) whose trailing slot carries the «Подать приказ» button.
 * Below it sit the two order cards — «Мои приказы» and «Приказы
 * других игроков» — that replaced the stat tiles and the «Ожидают
 * вердикт» list in 0.10.0: the judge path now runs through the
 * Registry (card → orders tab → row → order window).
 *
 * The card look is PNG 08: a `surface-raised` card with a `line`
 * frame, a 44 px `surface-inset` icon tile on the left carrying a
 * brass count circle on its top-right corner, the title in
 * `heading`, a `caption` subtitle in `ink-muted` («Ждут вердикта» /
 * «Нужно написать вердикт») and an `ink-faint` chevron on the right.
 *
 * «Мои приказы» counts the player's own submitted orders without a
 * verdict (`unresolved_orders` from GET /orders/rules — the same
 * route the composer reads); «Приказы других игроков» counts the
 * orders assigned to the player for judging (the GET /orders/assigned
 * list length — the endpoint is unpaginated and returns the whole
 * queue). A zero count gets no circle, counts of 100+ show «99+»;
 * a failed or in-flight fetch leaves the card numberless — never
 * «0», never an error popup. Both counts load on mount and refetch
 * when `ordersRefreshKey` bumps (an order submitted, a verdict
 * written or rejected).
 *
 * A card click hands the host an entry request for the Registry's
 * orders tab with the preset filter («Мои приказы» — the nation
 * dropdown set to my short name, «Приказы других игроков» — the
 * «Назначены мне» extension on «Да»); navigation itself lives in
 * AppShell, which stores the request and pushes '/registry'.
 */

import { useState } from 'react';
import { Button } from '@vkontakte/vkui';

import {
  BlockTitle,
  FONTS,
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

/** A count of 100 or more collapses to «99+» (PNG 08). */
const countText = (count: number) => (count >= 100 ? '99+' : String(count));

/** PNG 08 — the «Мои приказы» tile icon: a document with an up arrow. */
function MineIcon() {
  return (
    <svg
      width={24}
      height={24}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3.8 1.8h5.7l3 3.1v9.3H3.8z" />
      <path d="M9.5 1.8v3.1h3" />
      <path d="M8.1 11.6V7.2M6.2 9l1.9-1.9L10 9" />
    </svg>
  );
}

/** PNG 08 — the «Приказы других игроков» tile icon: a checked document. */
function OthersIcon() {
  return (
    <svg
      width={24}
      height={24}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3.8 1.8h5.7l3 3.1v9.3H3.8z" />
      <path d="M9.5 1.8v3.1h3" />
      <path d="M5.9 9.4l1.5 1.5 3-3.2" />
    </svg>
  );
}

/** PNG 08 — the `ink-faint` chevron on the card's right edge. */
function CardChevron() {
  return (
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
  );
}

export function OrdersBlock({
  nationShortName,
  onOpenRegistry,
}: {
  /** My nation's short name — the «Мои приказы» preset's dropdown value
   * (the Registry's nation options list short names, Spec 03_registry 3.3). */
  nationShortName: string;
  /** Hands the card's entry request to the host (AppShell stores it
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
          <Button size="m" mode="primary" onClick={openComposer}>
            {ORDERS_TEXTS.submitButton}
          </Button>
        }
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: SPACING['space-4'],
        }}
      >
        <OrderCard
          testId="orders-badge-mine"
          icon={<MineIcon />}
          label={ORDERS_TEXTS.badgeMine}
          hint={ORDERS_TEXTS.badgeMineHint}
          count={mineCount}
          onClick={() =>
            onOpenRegistry({
              tab: ORDERS_TABLE_ID,
              preset: { nation: nationShortName },
            })
          }
        />
        <OrderCard
          testId="orders-badge-assigned"
          icon={<OthersIcon />}
          label={ORDERS_TEXTS.badgeOthers}
          hint={ORDERS_TEXTS.badgeOthersHint}
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

function OrderCard({
  testId,
  icon,
  label,
  hint,
  count,
  onClick,
}: {
  testId: string;
  icon: React.ReactNode;
  label: string;
  hint: string;
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
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        gap: SPACING['space-3'],
        minWidth: 0,
        minHeight: 72,
        padding: '12px 16px',
        boxSizing: 'border-box',
        background: tokenVar('surface-raised'),
        border: `1px solid ${tokenVar(hot ? 'ink-faint' : 'line')}`,
        borderRadius: RADII['radius-lg'],
        cursor: 'pointer',
        textAlign: 'left',
        color: tokenVar('ink'),
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      <span
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 44,
          height: 44,
          flexShrink: 0,
          borderRadius: RADII['radius-md'],
          background: tokenVar('surface-inset'),
        }}
      >
        {icon}
        {count !== null && count > 0 && (
          <span
            data-testid={`${testId}-count`}
            aria-label={ORDERS_TEXTS.badgeAttention(count)}
            style={{
              position: 'absolute',
              top: -8,
              right: -8,
              minWidth: 20,
              height: 20,
              padding: '0 5px',
              boxSizing: 'border-box',
              borderRadius: RADII['radius-pill'],
              background: tokenVar('signal'),
              color: tokenVar('on-signal'),
              fontFamily: FONTS.mono,
              fontSize: 12,
              lineHeight: '20px',
              textAlign: 'center',
            }}
          >
            {countText(count)}
          </span>
        )}
      </span>
      <span style={{ flexGrow: 1, minWidth: 0 }}>
        <span
          style={{
            display: 'block',
            ...TEXT_STYLES['heading'],
            color: tokenVar('ink'),
          }}
        >
          {label}
        </span>
        <span
          style={{
            display: 'block',
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {hint}
        </span>
      </span>
      <CardChevron />
    </button>
  );
}
