/**
 * OrdersBlock — the «Приказы» block of the headquarters card
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation;
 * UI Spec 9.1, mockup «Main», version 0.9.0 unit 8b).
 *
 * A surface block with the shared BlockTitle («Приказы», document
 * icon) whose trailing slot carries the «Подать приказ» button.
 * Below sits «Ожидают вердикт»: the orders assigned to the player
 * for judging. The list loads when the block mounts and on
 * «Обновить» — no polling; after a written or rejected verdict the
 * provider bumps `assignedRefreshKey` and the list refetches. A row
 * shows the number, the nation colour mark and name, the title (one
 * line with ellipsis, the full text as a tooltip), the deadline
 * «до DD.MM.YYYY HH:MM», the «срок вышел» mark when overdue, and the
 * «Написать вердикт» / «Открыть приказ» actions. A failed refresh
 * keeps the shown list under «Не удалось загрузить» and «Повторить».
 */

import { Button, FormStatus } from '@vkontakte/vkui';

import { errorText } from '../../../shared/errorTexts';
import {
  BlockTitle,
  EmptyState,
  LoadingState,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { useAssignedOrders } from '../hooks/useAssignedOrders';
import { ORDERS_TEXTS } from '../texts';
import type { AssignedOrderDTO } from '../types';
import { useOrdersUi } from '../OrdersUiProvider';
import { NationMark } from './NationMark';

export function OrdersBlock() {
  const {
    openComposer,
    openOrder,
    openVerdictComposer,
    assignedRefreshKey,
  } = useOrdersUi();
  const assigned = useAssignedOrders(assignedRefreshKey);

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
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <span
          style={{
            ...TEXT_STYLES['label'],
            color: tokenVar('ink-muted'),
          }}
        >
          {ORDERS_TEXTS.assignedTitle}
        </span>
        <Button
          size="s"
          mode="tertiary"
          loading={assigned.status === 'loading'}
          onClick={assigned.refresh}
        >
          {ORDERS_TEXTS.refreshButton}
        </Button>
      </div>

      {assigned.status === 'error' && (
        <>
          <FormStatus mode="error" title={ORDERS_TEXTS.assignedLoadError}>
            {errorText(assigned.error)}
          </FormStatus>
          <Button size="s" onClick={assigned.refresh}>
            {ORDERS_TEXTS.retry}
          </Button>
        </>
      )}

      {assigned.items.length === 0 && assigned.status === 'loading' ? (
        <LoadingState height={36} />
      ) : assigned.items.length === 0 && assigned.status === 'ready' ? (
        <EmptyState text={ORDERS_TEXTS.assignedEmpty} />
      ) : (
        assigned.items.map((item) => (
          <AssignedRow
            key={item.number}
            item={item}
            onVerdict={openVerdictComposer}
            onOpen={openOrder}
          />
        ))
      )}
    </section>
  );
}

function AssignedRow({
  item,
  onVerdict,
  onOpen,
}: {
  item: AssignedOrderDTO;
  onVerdict: (number: number) => void;
  onOpen: (number: number) => void;
}) {
  return (
    <div
      data-testid={`assigned-order-${item.number}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        minWidth: 0,
        padding: '8px 0',
      }}
    >
      <span
        style={{
          whiteSpace: 'nowrap',
          ...TEXT_STYLES['figure'],
          color: tokenVar('ink'),
        }}
      >
        №{item.number}
      </span>
      <NationMark name={item.nation.name} color={item.nation.color} />
      <span
        title={item.title}
        style={{
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {item.title}
      </span>
      <span
        style={{
          whiteSpace: 'nowrap',
          color: tokenVar('ink-muted'),
        }}
      >
        {ORDERS_TEXTS.assignedDeadline(item.deadline_text)}
      </span>
      {item.overdue && (
        <span
          data-testid="assigned-overdue-mark"
          style={{
            whiteSpace: 'nowrap',
            color: tokenVar('danger'),
          }}
        >
          {ORDERS_TEXTS.assignedOverdueMark}
        </span>
      )}
      <Button
        size="s"
        mode="primary"
        onClick={() => onVerdict(item.number)}
      >
        {ORDERS_TEXTS.writeVerdict}
      </Button>
      <Button size="s" mode="link" onClick={() => onOpen(item.number)}>
        {ORDERS_TEXTS.openOrderLink}
      </Button>
    </div>
  );
}
