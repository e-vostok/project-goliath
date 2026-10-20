/**
 * Form draft memory (useFormDraft): typed values survive a dismissal —
 * the cross routes through closeWindow (Esc and the scrim no longer
 * close a dirty form, UI Spec 3.3) — and are restored when the form is
 * reopened. A successful send deletes the draft, verdict drafts are
 * keyed per order number, and a broken sessionStorage must not break
 * the form (memory mirror only).
 */

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

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

const JUDGE_ORDER_THREE: OrderDetailDTO = {
  ...JUDGE_ORDER,
  number: 3,
  nation: { name: 'Северия', color: '#993366' },
  title: 'Приказ №3',
};

/** The header «×» of the open popup — the close path that keeps the draft. */
async function dismissByCross(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Закрыть' }));
}

async function openComposer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole('button', { name: 'Подать приказ' }),
  );
  await screen.findByTestId('order-unresolved-counter');
}

async function openVerdictComposer(
  user: ReturnType<typeof userEvent.setup>,
  orderNumber: number,
) {
  runCellAction(`order:${orderNumber}`);
  await screen.findByText(`Приказ №${orderNumber}`);
  await user.click(
    await screen.findByRole('button', { name: 'Написать вердикт' }),
  );
  await screen.findByText(`Вердикт по приказу №${orderNumber}`);
}

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler({ items: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('OrderComposer — draft memory', () => {
  it('restores the typed values after a dismissed window reopens', async () => {
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    await openComposer(user);
    await user.type(screen.getByLabelText('Название'), 'Черновик приказа');
    await user.type(
      screen.getByLabelText('Краткая суть приказа'),
      'Черновая суть.',
    );
    await dismissByCross(user);
    await waitFor(() =>
      expect(screen.queryByLabelText('Название')).not.toBeInTheDocument(),
    );

    await openComposer(user);
    expect(screen.getByLabelText('Название')).toHaveValue(
      'Черновик приказа',
    );
    expect(screen.getByLabelText('Краткая суть приказа')).toHaveValue(
      'Черновая суть.',
    );
    expect(screen.getByLabelText('Ссылка на статью ВК')).toHaveValue('');
  });

  it('deletes the draft after a successful send', async () => {
    server.use(
      http.post('*/api/v1/orders', () =>
        HttpResponse.json(ORDER, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    await openComposer(user);
    await user.type(screen.getByLabelText('Название'), 'Отправленный');
    await user.type(
      screen.getByLabelText('Краткая суть приказа'),
      'Этот приказ уходит.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@sent',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );
    await screen.findByText('Приказ №7 подан');

    await openComposer(user);
    expect(screen.getByLabelText('Название')).toHaveValue('');
    expect(screen.getByLabelText('Краткая суть приказа')).toHaveValue('');
    expect(screen.getByLabelText('Ссылка на статью ВК')).toHaveValue('');
  });

  it('still works when sessionStorage throws on every access', async () => {
    const denied = () => {
      throw new Error('sessionStorage denied');
    };
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(denied);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(denied);
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(denied);
    vi.spyOn(Storage.prototype, 'key').mockImplementation(denied);

    const user = userEvent.setup();
    renderWithOrders(<OrdersBlock />);

    await openComposer(user);
    await user.type(screen.getByLabelText('Название'), 'Без хранилища');
    await dismissByCross(user);
    await waitFor(() =>
      expect(screen.queryByLabelText('Название')).not.toBeInTheDocument(),
    );

    // The in-memory mirror alone keeps the draft — the form reopens
    // with the typed value.
    await openComposer(user);
    expect(screen.getByLabelText('Название')).toHaveValue('Без хранилища');
  });
});

describe('VerdictComposer — draft memory keyed per order', () => {
  it('keeps each order its own draft', async () => {
    server.use(
      http.get('*/api/v1/orders/7', () => HttpResponse.json(JUDGE_ORDER)),
      http.get('*/api/v1/orders/3', () =>
        HttpResponse.json(JUDGE_ORDER_THREE),
      ),
    );
    const user = userEvent.setup();
    renderWithOrders(<></>);

    // Order 7: type a verdict and dismiss the window.
    await openVerdictComposer(user, 7);
    await user.type(
      screen.getByLabelText('Название'),
      'Вердикт по седьмому',
    );
    await dismissByCross(user);
    await waitFor(() =>
      expect(
        screen.queryByText('Вердикт по приказу №7'),
      ).not.toBeInTheDocument(),
    );

    // Order 3: its composer starts empty — order 7's draft must not
    // leak under a different key. Type its own and dismiss.
    await openVerdictComposer(user, 3);
    expect(screen.getByLabelText('Название')).toHaveValue('');
    await user.type(
      screen.getByLabelText('Название'),
      'Вердикт по третьему',
    );
    await dismissByCross(user);
    await waitFor(() =>
      expect(
        screen.queryByText('Вердикт по приказу №3'),
      ).not.toBeInTheDocument(),
    );

    // Order 7 again: its own draft is back.
    await openVerdictComposer(user, 7);
    expect(screen.getByLabelText('Название')).toHaveValue(
      'Вердикт по седьмому',
    );
  });
});
