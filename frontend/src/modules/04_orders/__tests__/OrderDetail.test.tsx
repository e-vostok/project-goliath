/**
 * OrderDetailModal — the «Приказ №N» window (Spec 5.4, 5.5).
 *
 * Covers: the window opens from a Registry title click and from the
 * `#registry/order-N` entry request (the same cell-action path),
 * «Написать вердикт» stays hidden while `can_write_verdict` is false,
 * and a 404 renders «Приказ не найден».
 */

import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createHashRouter, RouterProvider } from '@vkontakte/vk-mini-apps-router';
import { useState } from 'react';

import { server } from '../../../../vitest.setup';
import { PanelRegistry } from '../../03_registry/components/PanelRegistry';
import { runCellAction } from '../../03_registry/lib/cellActions';
import { OrdersBlock } from '../components/OrdersBlock';
import {
  ORDERS_ROWS,
  ORDERS_TABLE,
  registerAssignedHandler,
  registerOrderDetailHandler,
  registerRulesHandler,
  renderWithOrders,
} from './helpers';
import type { RegistryEntryRequest } from '../../03_registry/lib/entryRequest';

vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

function registerRegistryHandlers() {
  server.use(
    http.get('*/api/v1/registry/tables', () =>
      HttpResponse.json({
        layout: { tabs_position: 'top' },
        tables: [ORDERS_TABLE],
      }),
    ),
    http.get('*/api/v1/registry/tables/orders', () =>
      HttpResponse.json(ORDERS_ROWS),
    ),
  );
}

/** PanelRegistry needs the hash router's route navigator. */
function RegistryWithRouter({
  entryRequest = null,
}: {
  entryRequest?: RegistryEntryRequest | null;
}) {
  const [router] = useState(() =>
    createHashRouter([{ path: '/', panel: 'registry', view: 'main' }]),
  );
  return (
    <RouterProvider router={router}>
      <PanelRegistry entryRequest={entryRequest} />
    </RouterProvider>
  );
}

beforeEach(() => {
  registerRulesHandler();
  registerOrderDetailHandler();
  registerAssignedHandler({ items: [] });
});

describe('OrderDetailModal — open and content', () => {
  it('opens on a Registry title click and hides «Написать вердикт» while can_write_verdict is false', async () => {
    registerRegistryHandlers();
    const user = userEvent.setup();
    renderWithOrders(
      <>
        <OrdersBlock nationShortName="Тест" onOpenRegistry={() => {}} />
        <RegistryWithRouter />
      </>,
    );

    // The order title is an action_text cell — a button-looking link.
    await user.click(
      await screen.findByRole('button', {
        name: 'Приказ о перебазировании',
      }),
    );

    // The detail window opens: number + nation mark in the header,
    // the order's blocks below.
    await screen.findByText('Приказ №7');
    expect(screen.getAllByText('Автория').length).toBeGreaterThan(0);
    await screen.findByText('Краткая суть приказа');
    expect(
      screen.getByText('Перевести вторую армию к северной границе.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Статья приказа ↗' }),
    ).toHaveAttribute('href', 'https://vk.com/@order-seven');
    expect(
      screen.queryByRole('button', { name: 'Написать вердикт' }),
    ).not.toBeInTheDocument();
  });

  it('opens from the #registry/order-N entry request (tab + action)', async () => {
    registerRegistryHandlers();
    renderWithOrders(
      <RegistryWithRouter
        entryRequest={{ tab: 'orders', action: 'order:7' }}
      />,
    );

    // The request selects the «Приказы» tab and opens the window once
    // its rows are loaded — exactly what a title click does.
    await screen.findByText('Приказ №7');
    await screen.findByText('Перевести вторую армию к северной границе.');
  });
});

describe('OrderDetailModal — cell action edge cases', () => {
  it('shows «Приказ не найден» when the server answers 404', async () => {
    server.use(
      http.get('*/api/v1/orders/99', () =>
        HttpResponse.json(
          { detail: 'Приказ №99 не найден', code: 'ORDER_NOT_FOUND' },
          { status: 404 },
        ),
      ),
    );
    renderWithOrders(<OrdersBlock nationShortName="Тест" onOpenRegistry={() => {}} />);

    // The provider registered `order` on mount — a click (or the
    // entry request) calls it; the state update needs act().
    act(() => runCellAction('order:99'));
    await screen.findByText('Приказ №99');
    await screen.findByText('Приказ не найден');
    expect(
      screen.queryByRole('button', { name: 'Написать вердикт' }),
    ).not.toBeInTheDocument();
  });
});
