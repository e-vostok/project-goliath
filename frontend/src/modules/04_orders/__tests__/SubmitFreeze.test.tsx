/**
 * Frozen-buttons regression (Track B): a confirm window must stay usable
 * after its previous send was abandoned — the window closed while the
 * request was still in flight. The confirm components stay mounted under
 * the provider while their window is hidden (the composer view returns),
 * so a `submitting` flag that survives the request must be released when
 * it settles, or the next window opens with «Да, отправить» spinning and
 * «Вернуться к правке» disabled forever.
 */

import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { runCellAction } from '../../03_registry/lib/cellActions';
import { OrdersBlock } from '../components/OrdersBlock';
import {
  ORDER,
  registerAssignedHandler,
  registerRulesHandler,
  renderWithOrders,
} from './helpers';
import type { OrderDetailDTO } from '../types';

const JUDGE_ORDER: OrderDetailDTO = {
  ...ORDER,
  distributed: true,
  can_write_verdict: true,
};

const JUDGED_ORDER: OrderDetailDTO = {
  ...JUDGE_ORDER,
  verdict: {
    title: 'Вердикт: исполнено',
    summary: 'Приказ исполнен в срок.',
    article_url: 'https://vk.com/@verdict-seven',
  },
  can_write_verdict: false,
};

/** Esc bubbles to the top Popup's document key handler — the same as pressing Esc. */
function escFrom(element: HTMLElement) {
  fireEvent.keyDown(element, { key: 'Escape' });
}

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler({ items: [] });
});

describe('ConfirmSubmitModal — abandoned send', () => {
  it('lets the next confirmation send after the window was closed mid-flight', async () => {
    let posts = 0;
    server.use(
      http.post('*/api/v1/orders', async () => {
        posts += 1;
        // Slow enough for the close below to land mid-flight.
        await delay(60);
        return HttpResponse.json(ORDER, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    // First pass: fill, reach the confirm window, send and abandon it.
    await user.click(
      screen.getByRole('button', { name: 'Подать приказ' }),
    );
    await screen.findByTestId('order-unresolved-counter');
    await user.type(screen.getByLabelText('Название'), 'Первый приказ');
    await user.type(
      screen.getByLabelText('Краткая суть приказа'),
      'Сводка первого приказа.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@first',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );
    escFrom(
      await screen.findByText(
        'Уверены ли вы, всё ли проверили: изменить приказ после подачи нельзя',
      ),
    );
    await screen.findByText('Приказ №7 подан');
    expect(posts).toBe(1);

    // Second pass: the confirm window must work again.
    await user.click(
      screen.getByRole('button', { name: 'Подать приказ' }),
    );
    await screen.findByTestId('order-unresolved-counter');
    await user.type(screen.getByLabelText('Название'), 'Второй приказ');
    await user.type(
      screen.getByLabelText('Краткая суть приказа'),
      'Сводка второго приказа.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@second',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );

    const send = await screen.findByRole('button', {
      name: 'Да, отправить',
    });
    expect(send).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Вернуться к правке' }),
    ).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(posts).toBe(2));
  });
});

describe('ConfirmVerdictModal — abandoned send', () => {
  it('lets the next verdict confirmation send after the window was closed mid-flight', async () => {
    let posts = 0;
    server.use(
      // The detail keeps can_write_verdict so the composer can reopen.
      http.get('*/api/v1/orders/7', () =>
        HttpResponse.json(JUDGE_ORDER),
      ),
      http.post('*/api/v1/orders/7/verdict', async () => {
        posts += 1;
        await delay(60);
        return HttpResponse.json(JUDGED_ORDER, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithOrders(<></>);

    // Open the order and write a verdict, send it, close mid-flight.
    runCellAction('order:7');
    await screen.findByText('Приказ №7');
    await user.click(
      await screen.findByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await user.type(screen.getByLabelText('Название'), 'Первый вердикт');
    await user.type(
      screen.getByLabelText('Краткая суть вердикта'),
      'Суть первого вердикта.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@verdict-one',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить вердикт' }),
    );
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );
    escFrom(
      await screen.findByText(
        'Уверены ли вы, всё ли проверили: изменить вердикт после отправки нельзя',
      ),
    );
    await screen.findByText('Вердикт по приказу №7 записан');
    expect(posts).toBe(1);

    // Back on the detail window: write another verdict — the confirm
    // window must work again.
    await user.click(
      await screen.findByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await user.type(screen.getByLabelText('Название'), 'Второй вердикт');
    await user.type(
      screen.getByLabelText('Краткая суть вердикта'),
      'Суть второго вердикта.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@verdict-two',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить вердикт' }),
    );

    const send = await screen.findByRole('button', {
      name: 'Да, отправить',
    });
    expect(send).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Вернуться к правке' }),
    ).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(posts).toBe(2));
  });
});
