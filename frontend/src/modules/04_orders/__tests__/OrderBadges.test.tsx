/**
 * «Штаб» order badges — «Мои приказы» and «Приказы других игроков»
 * (UI Spec 9.1 boards 10/10b, Spec 5.4, version 0.10.0 unit 7b; they
 * replaced the stat tiles and the «Ожидают вердикт» list).
 *
 * Covers: both badges with their counts (unresolved_orders from
 * GET /orders/rules, the GET /orders/assigned list length), a zero
 * count gets no circle, 100+ collapses to «99+», each click hands the
 * host the right 7a entry request (nation preset / «Назначены мне»),
 * a failed count fetch leaves the badge numberless with no error,
 * and a submitted order plus a written verdict both bump the shared
 * refresh key so the counts refetch.
 */

import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import { runCellAction } from '../../03_registry/lib/cellActions';
import { OrdersBlock } from '../components/OrdersBlock';
import type { OrderDetailDTO } from '../types';
import {
  ASSIGNED,
  ORDER,
  registerAssignedHandler,
  registerOrderDetailHandler,
  registerRulesHandler,
  renderWithOrders,
  RULES,
} from './helpers';

/** The order the test judge writes a verdict for. */
const JUDGE_ORDER: OrderDetailDTO = {
  ...ORDER,
  distributed: true,
  can_write_verdict: true,
};

function renderBlock() {
  const onOpenRegistry = vi.fn();
  renderWithOrders(
    <OrdersBlock nationShortName="Тест" onOpenRegistry={onOpenRegistry} />,
  );
  return { onOpenRegistry };
}

/** Counts requests to the two count routes; returns the counters. */
function countRequests(rules: object = RULES, assignedItems = ASSIGNED.items) {
  const calls = { rules: 0, assigned: 0 };
  server.use(
    http.get('*/api/v1/orders/rules', () => {
      calls.rules += 1;
      return HttpResponse.json(rules);
    }),
    http.get('*/api/v1/orders/assigned', () => {
      calls.assigned += 1;
      return HttpResponse.json({ items: assignedItems });
    }),
  );
  return calls;
}

beforeEach(() => {
  registerRulesHandler();
  registerAssignedHandler();
});

describe('OrdersBlock — the two badges', () => {
  it('renders both badges with the counts from the two GETs — and nothing of the old queue', async () => {
    registerRulesHandler({ ...RULES, unresolved_orders: 2 });
    // ASSIGNED holds two items — the badge counts the list length.
    renderBlock();

    expect(
      await screen.findByTestId('orders-badge-mine-count'),
    ).toHaveTextContent('2');
    expect(
      await screen.findByTestId('orders-badge-assigned-count'),
    ).toHaveTextContent('2');

    // The old «Ожидают вердикт» list is gone: no rows, no retry, no
    // per-row «Написать вердикт». «Подать приказ» stays.
    expect(screen.queryByText('Ожидают вердикт')).toBeNull();
    expect(screen.queryByText('Приказ о перебазировании')).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Написать вердикт' }),
    ).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Подать приказ' }),
    ).toBeInTheDocument();
  });

  it('a zero count gets no circle (board 10b)', async () => {
    const calls = countRequests(
      { ...RULES, unresolved_orders: 0 },
      [],
    );
    renderBlock();

    await waitFor(() => {
      expect(calls.rules).toBe(1);
      expect(calls.assigned).toBe(1);
    });
    expect(screen.queryByTestId('orders-badge-mine-count')).toBeNull();
    expect(
      screen.queryByTestId('orders-badge-assigned-count'),
    ).toBeNull();
    // The badges themselves render — only the circles are absent.
    expect(
      screen.getByRole('button', { name: 'Мои приказы' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Приказы других игроков' }),
    ).toBeInTheDocument();
  });

  it('counts of 100 and more collapse to «99+»', async () => {
    registerRulesHandler({ ...RULES, unresolved_orders: 120 });
    registerAssignedHandler({
      items: Array.from({ length: 104 }, (_, i) => ({
        ...ASSIGNED.items[0],
        number: i + 1,
      })),
    });
    renderBlock();

    expect(
      await screen.findByTestId('orders-badge-mine-count'),
    ).toHaveTextContent('99+');
    expect(
      await screen.findByTestId('orders-badge-assigned-count'),
    ).toHaveTextContent('99+');
  });

  it('«Мои приказы» hands the host the 7a nation preset for the orders tab', async () => {
    const { onOpenRegistry } = renderBlock();
    await userEvent.click(
      await screen.findByRole('button', { name: 'Мои приказы' }),
    );

    expect(onOpenRegistry).toHaveBeenCalledWith({
      tab: 'orders',
      preset: { nation: 'Тест' },
    });
  });

  it('«Приказы других игроков» hands the host the «Назначены мне» preset', async () => {
    const { onOpenRegistry } = renderBlock();
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Приказы других игроков',
      }),
    );

    expect(onOpenRegistry).toHaveBeenCalledWith({
      tab: 'orders',
      preset: { assignedToMe: true },
    });
  });

  it('a failed count fetch leaves the badge numberless — no error, no crash', async () => {
    const calls = { rules: 0, assigned: 0 };
    server.use(
      http.get('*/api/v1/orders/rules', () => {
        calls.rules += 1;
        return HttpResponse.json({ detail: 'boom' }, { status: 500 });
      }),
      http.get('*/api/v1/orders/assigned', () => {
        calls.assigned += 1;
        return HttpResponse.json({ detail: 'boom' }, { status: 500 });
      }),
    );
    renderBlock();

    await waitFor(() => {
      expect(calls.rules).toBe(1);
      expect(calls.assigned).toBe(1);
    });
    expect(screen.queryByTestId('orders-badge-mine-count')).toBeNull();
    expect(
      screen.queryByTestId('orders-badge-assigned-count'),
    ).toBeNull();
    // No «Не удалось загрузить», no retry button, no error text.
    expect(screen.queryByText(/Не удалось/)).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Мои приказы' }),
    ).toBeInTheDocument();
  });
});

describe('OrdersBlock — shared refresh', () => {
  it('a submitted order bumps ordersRefreshKey — both counts refetch', async () => {
    const calls = countRequests({ ...RULES, unresolved_orders: 0 }, []);
    server.use(
      http.post('*/api/v1/orders', () =>
        HttpResponse.json(ORDER, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    renderBlock();
    await waitFor(() => {
      expect(calls.rules).toBe(1);
      expect(calls.assigned).toBe(1);
    });

    await user.click(
      screen.getByRole('button', { name: 'Подать приказ' }),
    );
    await user.type(
      await screen.findByLabelText('Название'),
      'Приказ о наступлении',
    );
    await user.type(
      screen.getByLabelText('Краткая суть приказа'),
      'Все армии выступают на рассвете.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@nastuplenie',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    // The open composer fetched the rules for its own counter — the
    // badge's refetch is the NEXT rules call after the send.
    const rulesBefore = calls.rules;
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    await screen.findByText('Приказ №7 подан');
    await waitFor(() => {
      expect(calls.rules).toBe(rulesBefore + 1);
      expect(calls.assigned).toBe(2);
    });
  });

  it('a written verdict bumps ordersRefreshKey — the assigned count refetches', async () => {
    const calls = countRequests();
    registerOrderDetailHandler(JUDGE_ORDER);
    server.use(
      http.post('*/api/v1/orders/7/verdict', () =>
        HttpResponse.json(
          { ...JUDGE_ORDER, can_write_verdict: false },
          { status: 201 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderBlock();
    await waitFor(() => {
      expect(calls.rules).toBe(1);
      expect(calls.assigned).toBe(1);
    });

    // The judge path: Registry `order:<n>` action → detail →
    // «Написать вердикт» → composer → confirmation.
    act(() => runCellAction('order:7'));
    await screen.findByText('Приказ №7');
    await user.click(
      await screen.findByRole('button', { name: 'Написать вердикт' }),
    );
    await screen.findByText('Вердикт по приказу №7');
    await user.type(
      screen.getByLabelText('Название'),
      'Вердикт: исполнено',
    );
    await user.type(
      screen.getByLabelText('Краткая суть вердикта'),
      'Приказ исполнен в срок.',
    );
    await user.type(
      screen.getByLabelText('Ссылка на статью ВК'),
      'https://vk.com/@verdict-seven',
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить вердикт' }),
    );
    // The open verdict composer fetched the rules for its own
    // counters — the badge's refetch is the NEXT rules call.
    const rulesBefore = calls.rules;
    await user.click(
      await screen.findByRole('button', { name: 'Да, отправить' }),
    );

    await screen.findByText('Вердикт по приказу №7 записан');
    await waitFor(() => {
      expect(calls.rules).toBe(rulesBefore + 1);
      expect(calls.assigned).toBe(2);
    });
  });
});
