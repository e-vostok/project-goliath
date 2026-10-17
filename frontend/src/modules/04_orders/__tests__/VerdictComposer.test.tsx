/**
 * VerdictComposer + ConfirmVerdictModal — the judge's verdict flow
 * (Spec 5.4, 5.5).
 *
 * Covers: «Написать вердикт» in the detail window appears only with
 * `can_write_verdict` and opens the composer; field errors land at
 * the right field; a double click on «Да, отправить» sends a single
 * request; ORDER_VERDICT_EXISTS closes the composer, reloads the
 * detail window and the assigned list; and a judge without a nation
 * writes a verdict from the detail window (the `#registry/order-N`
 * entry path — no headquarters block).
 */

import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { runCellAction } from '../../03_registry/lib/cellActions';
import { OrdersBlock } from '../components/OrdersBlock';
import {
  ORDER,
  registerAssignedHandler,
  registerOrderDetailHandler,
  registerRulesHandler,
  renderWithOrders,
} from './helpers';
import type { OrderDetailDTO } from '../types';

/** The order the test judge is assigned to. */
const JUDGE_ORDER: OrderDetailDTO = {
  ...ORDER,
  distributed: true,
  can_write_verdict: true,
};

/** The order after the verdict is recorded. */
const JUDGED_ORDER: OrderDetailDTO = {
  ...JUDGE_ORDER,
  verdict: {
    title: 'Вердикт: исполнено',
    summary: 'Приказ исполнен в срок.',
    article_url: 'https://vk.com/@verdict-seven',
  },
  can_write_verdict: false,
};

async function openDetail() {
  // The Registry `order:<n>` action — what a title click or the
  // `#registry/order-N` entry request runs.
  act(() => runCellAction('order:7'));
  await screen.findByText('Приказ №7');
  await screen.findByText('Перевести вторую армию к северной границе.');
}

async function fillVerdict(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Название'), 'Вердикт: исполнено');
  await user.type(
    screen.getByLabelText('Краткая суть вердикта'),
    'Приказ исполнен в срок.',
  );
  await user.type(
    screen.getByLabelText('Ссылка на статью ВК'),
    'https://vk.com/@verdict-seven',
  );
}

async function toConfirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole('button', { name: 'Отправить вердикт' }),
  );
  await screen.findByText(
    'Уверены ли вы, всё ли проверили: изменить вердикт после отправки нельзя',
  );
}

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler();
  registerOrderDetailHandler(JUDGE_ORDER);
});

describe('OrderDetailModal — verdict entry', () => {
  it('shows «Написать вердикт» when can_write_verdict and opens the composer for that order', async () => {
    const user = userEvent.setup();
    renderWithOrders(<></>);
    await openDetail();

    await user.click(
      screen.getByRole('button', { name: 'Написать вердикт' }),
    );

    await screen.findByText('Вердикт по приказу №7');
    expect(
      screen.getByRole('button', { name: 'Отправить вердикт' }),
    ).toBeInTheDocument();
  });
});

describe('ConfirmVerdictModal — submit', () => {
  it('bounces back to the composer with the field error at the right field', async () => {
    server.use(
      http.post('*/api/v1/orders/7/verdict', () =>
        HttpResponse.json(
          {
            detail: 'Краткая суть не подходит: слишком короткая',
            code: 'ORDER_SUMMARY_INVALID',
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithOrders(<></>);
    await openDetail();
    await user.click(
      screen.getByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await fillVerdict(user);
    await toConfirm(user);
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    const summaryItem = await screen.findByTestId(
      'form-item-verdict-summary',
    );
    await within(summaryItem).findByText(/слишком короткая/);
    const titleItem = screen.getByTestId('form-item-verdict-title');
    expect(
      within(titleItem).queryByText(/слишком короткая/),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Название')).toHaveValue(
      'Вердикт: исполнено',
    );
  });

  it('sends a single POST verdict even when «Да, отправить» is clicked twice', async () => {
    let posts = 0;
    server.use(
      http.post('*/api/v1/orders/7/verdict', async () => {
        posts += 1;
        await delay(30);
        return HttpResponse.json(JUDGED_ORDER, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithOrders(<></>);
    await openDetail();
    await user.click(
      screen.getByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await fillVerdict(user);
    await toConfirm(user);

    const send = await screen.findByRole('button', {
      name: 'Да, отправить',
    });
    await user.click(send);
    await user.click(send);

    await screen.findByText('Вердикт по приказу №7 записан');
    expect(posts).toBe(1);
  });
});

describe('ConfirmVerdictModal — verdict already exists', () => {
  it('closes the composer, shows the message and reloads the detail window and the assigned list', async () => {
    let detailGets = 0;
    let assignedGets = 0;
    server.use(
      http.get('*/api/v1/orders/7', () => {
        detailGets += 1;
        return HttpResponse.json(
          detailGets === 1 ? JUDGE_ORDER : JUDGED_ORDER,
        );
      }),
      http.get('*/api/v1/orders/assigned', () => {
        assignedGets += 1;
        return HttpResponse.json({ items: [] });
      }),
      http.post('*/api/v1/orders/7/verdict', () =>
        HttpResponse.json(
          {
            detail: 'По приказу №7 уже записан вердикт',
            code: 'ORDER_VERDICT_EXISTS',
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    // OrdersBlock is mounted with an empty queue — its refetch is
    // what `assignedGets` counts.
    renderWithOrders(<OrdersBlock />);
    await screen.findByText('Приказов на рассмотрении нет');
    await openDetail();
    await user.click(
      screen.getByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await fillVerdict(user);
    await toConfirm(user);
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    // The server message is shown, the composer is closed and the
    // detail window (now with the recorded verdict) plus the
    // assigned list were reloaded.
    await screen.findByText('По приказу №7 уже записан вердикт');
    await screen.findByText('Вердикт');
    expect(
      screen.queryByRole('button', { name: 'Отправить вердикт' }),
    ).not.toBeInTheDocument();
    expect(detailGets).toBeGreaterThanOrEqual(2);
    expect(assignedGets).toBeGreaterThanOrEqual(2);
  });
});

describe('VerdictComposer — judge without a nation', () => {
  it('writes a verdict from the detail window with no headquarters block', async () => {
    let detailGets = 0;
    server.use(
      http.get('*/api/v1/orders/7', () => {
        detailGets += 1;
        return HttpResponse.json(
          detailGets === 1 ? JUDGE_ORDER : JUDGED_ORDER,
        );
      }),
      http.post('*/api/v1/orders/7/verdict', () =>
        HttpResponse.json(JUDGED_ORDER, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    // No OrdersBlock, no nation panel — the harness itself is what a
    // player without a nation gets from the bot link.
    renderWithOrders(<></>);
    await openDetail();
    await user.click(
      screen.getByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await fillVerdict(user);
    await toConfirm(user);
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    await screen.findByText('Вердикт по приказу №7 записан');
    // Back on the detail window, the recorded verdict is visible.
    await screen.findByText('Вердикт: исполнено');
    expect(detailGets).toBeGreaterThanOrEqual(2);
  });
});
