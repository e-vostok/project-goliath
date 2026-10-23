/**
 * OrdersBlock — the «Приказы» block of the headquarters card
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation;
 * UI Spec 9.1, mockup «Main», version 0.9.0 unit 12d).
 *
 * A surface block with the shared BlockTitle («Приказы», document
 * icon) whose trailing slot carries the «Подать приказ» button.
 * Below sits «Ожидают вердикт · N» (the count appears once the
 * queue is loaded and non-empty): the orders assigned to the
 * player for judging. The list loads when the block mounts and on
 * «Обновить» — no polling; after a written or rejected verdict the
 * provider bumps `assignedRefreshKey` and the list refetches. A row
 * is a calm two-line card: the order title (one line with
 * ellipsis, the full text as a tooltip) over the nation and the
 * deadline — «до DD.MM.YYYY HH:MM», or the inline danger mark
 * «срок вышел …» when overdue — with the single «Написать
 * вердикт» action on the right; a click or Enter/Space on the row
 * itself opens the order's detail window. A failed refresh keeps
 * the shown list under «Не удалось загрузить» and «Повторить».
 */

import { useState } from 'react';
import { Icon16Replay } from '@vkontakte/icons';
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
import { NationMark } from './NationMark';
import { ORDERS_TEXTS } from '../texts';
import type { AssignedOrderDTO } from '../types';
import { useOrdersUi } from '../OrdersUiProvider';

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
          marginBottom: SPACING['space-2'],
        }}
      >
        <span
          style={{
            ...TEXT_STYLES['label'],
            color: tokenVar('ink-muted'),
          }}
        >
          {ORDERS_TEXTS.assignedTitle}
          {assigned.status === 'ready' && assigned.items.length > 0
            ? ` · ${assigned.items.length}`
            : ''}
        </span>
        <Button
          size="s"
          mode="tertiary"
          before={<Icon16Replay />}
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
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          {assigned.items.map((item) => (
            <AssignedRow
              key={item.number}
              item={item}
              onVerdict={openVerdictComposer}
              onOpen={openOrder}
            />
          ))}
        </div>
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
  // `hot` paints the hover state, `focused` the keyboard focus ring.
  const [hot, setHot] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <div
      data-testid={`assigned-order-${item.number}`}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(item.number)}
      onKeyDown={(e) => {
        // Keys bubbled from the inner «Написать вердикт» button are
        // its own — the row activates only on its own focus.
        if (e.target !== e.currentTarget) {
          return;
        }
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen(item.number);
        }
      }}
      onMouseEnter={() => setHot(true)}
      onMouseLeave={() => setHot(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        minWidth: 0,
        padding: '10px 12px',
        background: tokenVar(hot ? 'surface-raised' : 'surface-inset'),
        borderRadius: RADII['radius-md'],
        cursor: 'pointer',
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      <span
        style={{
          width: 36,
          flexShrink: 0,
          whiteSpace: 'nowrap',
          ...TEXT_STYLES['figure'],
          color: tokenVar('ink-muted'),
        }}
      >
        №{item.number}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          title={item.title}
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: tokenVar('ink'),
          }}
        >
          {item.title}
        </div>
        <div
          style={{
            ...TEXT_STYLES['caption'],
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: tokenVar('ink-muted'),
          }}
        >
          {item.overdue ? (
            <>
              <NationMark nation={item.nation} />
              {' · '}
              <span
                data-testid="assigned-overdue-mark"
                style={{ color: tokenVar('danger') }}
              >
                {ORDERS_TEXTS.assignedOverdue(item.deadline_text)}
              </span>
            </>
          ) : (
            <>
              <NationMark nation={item.nation} />
              {` · ${ORDERS_TEXTS.assignedDeadline(item.deadline_text)}`}
            </>
          )}
        </div>
      </div>
      <Button
        size="s"
        mode="secondary"
        style={{ flexShrink: 0 }}
        onClick={(e) => {
          e.stopPropagation();
          onVerdict(item.number);
        }}
      >
        {ORDERS_TEXTS.writeVerdict}
      </Button>
    </div>
  );
}
