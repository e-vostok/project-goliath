/**
 * OrdersBlock — the «Приказы» mini-block in the headquarters
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation).
 *
 * Below «Подать приказ» sits «Ожидают вердикт»: the orders assigned to
 * the player for judging. The list loads when the block mounts and on
 * «Обновить» — no polling; after a written or rejected verdict the
 * provider bumps `assignedRefreshKey` and the list refetches. A row
 * shows the number, the nation colour mark and name, the title (one
 * line with ellipsis, the full text as a tooltip), the deadline
 * «до DD.MM.YYYY HH:MM», the «срок вышел» mark when overdue, and the
 * «Написать вердикт» / «Открыть приказ» actions. A failed refresh
 * keeps the shown list under «Не удалось загрузить» and «Повторить».
 */

import {
  Button,
  Div,
  FormStatus,
  Group,
  Header,
  Spinner,
  Text,
} from '@vkontakte/vkui';

import { errorText } from '../../../shared/errorTexts';
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
    <Group header={<Header size="l">{ORDERS_TEXTS.blockTitle}</Header>}>
      <Div>
        <Button size="l" stretched mode="secondary" onClick={openComposer}>
          {ORDERS_TEXTS.submitButton}
        </Button>
      </Div>
      <Div style={{ paddingTop: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <Text weight="2">{ORDERS_TEXTS.assignedTitle}</Text>
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
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              padding: '24px 0',
            }}
          >
            <Spinner size="m" />
          </div>
        ) : assigned.items.length === 0 && assigned.status === 'ready' ? (
          <Text
            style={{
              display: 'block',
              padding: '8px 0',
              color: 'var(--vkui--color_text_secondary)',
            }}
          >
            {ORDERS_TEXTS.assignedEmpty}
          </Text>
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
      </Div>
    </Group>
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
      <span style={{ whiteSpace: 'nowrap' }}>№{item.number}</span>
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
          color: 'var(--vkui--color_text_secondary)',
        }}
      >
        {ORDERS_TEXTS.assignedDeadline(item.deadline_text)}
      </span>
      {item.overdue && (
        <span
          data-testid="assigned-overdue-mark"
          style={{
            whiteSpace: 'nowrap',
            color: 'var(--vkui--color_text_negative)',
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
