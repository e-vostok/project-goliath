/**
 * «Мне на отсуд» — the judge's queue in the headquarters block
 * (Spec 5.4).
 *
 * Covers: the list renders the assigned rows (number, nation mark,
 * title, deadline, the «срок вышел» mark on the overdue one), the
 * empty state, and «Написать вердикт» in a row opens the verdict
 * composer for that order.
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { OrdersBlock } from '../components/OrdersBlock';
import {
  registerAssignedHandler,
  registerRulesHandler,
  renderWithOrders,
} from './helpers';

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler();
});

describe('OrdersBlock — «Мне на отсуд»', () => {
  it('renders the assigned rows with nation, deadline and the overdue mark', async () => {
    renderWithOrders(<OrdersBlock />);

    const row7 = await screen.findByTestId('assigned-order-7');
    expect(within(row7).getByText('№7')).toBeInTheDocument();
    expect(within(row7).getByText('Автория')).toBeInTheDocument();
    expect(
      within(row7).getByText('Приказ о перебазировании'),
    ).toBeInTheDocument();
    expect(
      within(row7).getByText('до 18.10.2026 21:21'),
    ).toBeInTheDocument();
    expect(
      within(row7).queryByText('срок вышел'),
    ).not.toBeInTheDocument();

    const row3 = screen.getByTestId('assigned-order-3');
    expect(within(row3).getByText('Северия')).toBeInTheDocument();
    expect(within(row3).getByText('до 14.10.2026 09:00')).toBeInTheDocument();
    expect(within(row3).getByText('срок вышел')).toBeInTheDocument();
  });

  it('shows the empty state when nothing is assigned', async () => {
    registerAssignedHandler({ items: [] });
    renderWithOrders(<OrdersBlock />);

    await screen.findByText('Приказов на рассмотрении нет');
    expect(
      screen.queryByRole('button', { name: 'Написать вердикт' }),
    ).not.toBeInTheDocument();
  });

  it('opens the verdict composer for the row’s order on «Написать вердикт»', async () => {
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    const row3 = await screen.findByTestId('assigned-order-3');
    await user.click(
      within(row3).getByRole('button', { name: 'Написать вердикт' }),
    );

    await screen.findByText('Вердикт по приказу №3');
    expect(screen.getByLabelText('Название')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Краткая суть вердикта'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Ссылка на статью ВК'),
    ).toBeInTheDocument();
    // The disabled effects block is shown but inert.
    const effects = screen.getByTestId('verdict-effects-block');
    expect(within(effects).getByText('Раздел станет доступен позже'))
      .toBeInTheDocument();
    expect(effects).toHaveAttribute('aria-disabled', 'true');
    expect(
      screen.getByRole('button', { name: 'Отправить вердикт' }),
    ).toBeDisabled();
  });
});
