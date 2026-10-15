/**
 * OrderComposer + ConfirmSubmitModal — order submission (Spec 5.4).
 *
 * Covers: field errors land at the right field by server code, the
 * «Да, отправить» button sends a single request on a double click,
 * the confirmation window shows the entered values in full, and the
 * send button is disabled at the author limit with the Spec text.
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { OrdersBlock } from '../components/OrdersBlock';
import {
  ORDER,
  registerRulesHandler,
  renderWithOrders,
  RULES,
} from './helpers';

async function openComposer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole('button', { name: 'Подать приказ' }),
  );
  // The composer's counter lands with GET /orders/rules.
  await screen.findByTestId('order-unresolved-counter');
}

async function fillComposer(
  user: ReturnType<typeof userEvent.setup>,
  values = {
    title: 'Приказ о наступлении',
    summary: 'Все армии выступают на рассвете.',
    url: 'https://vk.com/@nastuplenie',
  },
) {
  await user.type(screen.getByLabelText('Название'), values.title);
  await user.type(
    screen.getByLabelText('Краткая суть приказа'),
    values.summary,
  );
  await user.type(
    screen.getByLabelText('Ссылка на статью ВК'),
    values.url,
  );
}

beforeEach(() => registerRulesHandler());

describe('OrderComposer — author limit', () => {
  it('disables «Отправить приказ» at the author limit with the Spec explanation', async () => {
    registerRulesHandler({
      ...RULES,
      unresolved_orders: RULES.max_unresolved_orders,
    });
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);
    await openComposer(user);

    await screen.findByText('Неразрешённых приказов: 5 из 5');
    expect(
      screen.getByText(
        'Достигнут предел: дождитесь вердикта по одному из ваших приказов',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    ).toBeDisabled();
  });
});

describe('OrderComposer → ConfirmSubmitModal', () => {
  it('shows every entered value in full in the confirmation window', async () => {
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);
    await openComposer(user);
    await fillComposer(user);
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );

    await screen.findByText(
      'Уверены ли вы, всё ли проверили: изменить приказ после подачи нельзя',
    );
    expect(
      screen.getByText('Приказ о наступлении'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Все армии выступают на рассвете.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('https://vk.com/@nastuplenie'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Открыть ссылку' }),
    ).toHaveAttribute('href', 'https://vk.com/@nastuplenie');
    expect(
      screen.getByRole('button', { name: 'Вернуться к правке' }),
    ).toBeInTheDocument();
  });

  it('sends a single POST /orders even when «Да, отправить» is clicked twice', async () => {
    let posts = 0;
    server.use(
      http.post('*/api/v1/orders', async () => {
        posts += 1;
        // Leave time for the second click to land mid-flight.
        await delay(30);
        return HttpResponse.json(ORDER, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);
    await openComposer(user);
    await fillComposer(user);
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );

    const send = await screen.findByRole('button', {
      name: 'Да, отправить',
    });
    await user.click(send);
    await user.click(send);

    await screen.findByText('Приказ №7 подан');
    expect(posts).toBe(1);
  });

  it('bounces back to the composer with the field error at the right field', async () => {
    server.use(
      http.post('*/api/v1/orders', () =>
        HttpResponse.json(
          {
            detail:
              'Краткая суть приказа не подходит: слишком короткая',
            code: 'ORDER_SUMMARY_INVALID',
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);
    await openComposer(user);
    await fillComposer(user);
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    // Back in the composer: the summary field carries the server's
    // reason; the other fields stay clean.
    const summaryItem = await screen.findByTestId(
      'form-item-order-summary',
    );
    await within(summaryItem).findByText(/слишком короткая/);
    const titleItem = screen.getByTestId('form-item-order-title');
    expect(
      within(titleItem).queryByText(/слишком короткая/),
    ).not.toBeInTheDocument();
    // The entered values survived the round trip.
    expect(screen.getByLabelText('Название')).toHaveValue(
      'Приказ о наступлении',
    );
  });
});
