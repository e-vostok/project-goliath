/**
 * OrdersBlock — the «Приказы» mini-block in the headquarters
 * (PanelNationHome, Spec 5.4 / D12 — never in PanelCreateNation).
 * The «Мне на отсуд» list arrives with Issue 8.
 */

import { Button, Div, Group, Header } from '@vkontakte/vkui';

import { ORDERS_TEXTS } from '../texts';
import { useOrdersUi } from '../OrdersUiProvider';

export function OrdersBlock() {
  const { openComposer } = useOrdersUi();

  return (
    <Group header={<Header size="l">{ORDERS_TEXTS.blockTitle}</Header>}>
      <Div>
        <Button size="l" stretched mode="secondary" onClick={openComposer}>
          {ORDERS_TEXTS.submitButton}
        </Button>
      </Div>
    </Group>
  );
}
