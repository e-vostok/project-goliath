/**
 * «Ожидают вердикт» — the judge's queue in the headquarters block
 * (Spec 5.4).
 *
 * Covers: the two-line rows (number, title on line one, nation and
 * deadline on line two — the inline «срок вышел …» mark on the
 * overdue one), the « · N» count next to the label, the empty
 * state, «Обновить» refetching the queue, the row itself opening
 * the order detail on click and on Enter, and «Написать вердикт»
 * opening the verdict composer only.
 */

import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { OrdersBlock } from '../components/OrdersBlock';
import {
  ASSIGNED,
  registerAssignedHandler,
  registerOrderDetailHandler,
  registerRulesHandler,
  renderWithOrders,
} from './helpers';

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler();
});

describe('OrdersBlock — «Ожидают вердикт»', () => {
  it('renders two-line rows: title, nation and deadline; the overdue one carries the inline mark', async () => {
    renderWithOrders(<OrdersBlock />);

    const row7 = await screen.findByTestId('assigned-order-7');
    expect(within(row7).getByText('№7')).toBeInTheDocument();
    expect(
      within(row7).getByText('Приказ о перебазировании'),
    ).toBeInTheDocument();
    // Unit 6a: the nation mark is the submission-time SHORT name.
    expect(row7).toHaveTextContent('Авт · до 18.10.2026 21:21');
    expect(
      within(row7).queryByTestId('assigned-overdue-mark'),
    ).not.toBeInTheDocument();

    const row3 = screen.getByTestId('assigned-order-3');
    const mark = within(row3).getByTestId('assigned-overdue-mark');
    expect(mark).toHaveTextContent('срок вышел 14.10.2026 09:00');
    expect(mark.parentElement).toHaveTextContent(
      'Сев · срок вышел 14.10.2026 09:00',
    );

    // The separate «Открыть приказ» link is gone — the row opens it.
    expect(screen.queryByText('Открыть приказ')).not.toBeInTheDocument();
  });

  it('appends « · N» to the label once the queue is loaded', async () => {
    renderWithOrders(<OrdersBlock />);

    // While the first fetch is in flight there is no count.
    expect(
      screen.queryByText(/Ожидают вердикт ·/),
    ).not.toBeInTheDocument();

    await screen.findByTestId('assigned-order-7');
    expect(screen.getByText('Ожидают вердикт · 2')).toBeInTheDocument();
  });

  it('shows the empty state when nothing is assigned', async () => {
    registerAssignedHandler({ items: [] });
    renderWithOrders(<OrdersBlock />);

    await screen.findByText('Приказов на рассмотрении нет');
    // An empty queue gets no « · 0» — the label stands alone.
    expect(screen.getByText('Ожидают вердикт')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Написать вердикт' }),
    ).not.toBeInTheDocument();
  });

  it('opens the order detail on a row click', async () => {
    registerOrderDetailHandler();
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    await user.click(await screen.findByTestId('assigned-order-7'));

    await screen.findByText('Приказ №7');
    await screen.findByText('Краткая суть приказа');
    expect(
      screen.getByText('Перевести вторую армию к северной границе.'),
    ).toBeInTheDocument();
  });

  it('opens the order detail on Enter on the focused row', async () => {
    registerOrderDetailHandler();
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    const row7 = await screen.findByTestId('assigned-order-7');
    act(() => row7.focus());
    await user.keyboard('{Enter}');

    await screen.findByText('Приказ №7');
  });

  it('opens the verdict composer for the row’s order on «Написать вердикт» — the row itself does not open', async () => {
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    const row3 = await screen.findByTestId('assigned-order-3');
    await user.click(
      within(row3).getByRole('button', { name: 'Написать вердикт' }),
    );

    await screen.findByText('Вердикт по приказу №3');
    // The click stopped at the button — no order detail window.
    expect(screen.queryByText('Приказ №3')).not.toBeInTheDocument();
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

  it('refetches the queue on «Обновить»', async () => {
    let calls = 0;
    server.use(
      http.get('*/api/v1/orders/assigned', () => {
        calls += 1;
        return HttpResponse.json(ASSIGNED);
      }),
    );
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    await screen.findByTestId('assigned-order-7');
    expect(calls).toBe(1);

    await user.click(screen.getByRole('button', { name: 'Обновить' }));
    await waitFor(() => expect(calls).toBe(2));
  });
});
