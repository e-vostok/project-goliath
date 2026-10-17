/**
 * RegistryTable — the Spec 1.2 additions (Spec 04_orders Appendix B3):
 * an `action_text` cell is a link that runs the registered cell action,
 * and a `header_icon` column shows an icon whose tooltip / accessible
 * label is the column title.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  clearCellActions,
  registerCellAction,
} from '../lib/cellActions';
import { EMPTY_VIEW } from '../lib/tableView';
import { RegistryTable } from '../components/RegistryTable';
import type { RegistryTableDTO } from '../types';

const ORDERS_TABLE: RegistryTableDTO = {
  id: 'orders',
  title: 'Приказы',
  icon: 'orders',
  empty_text: 'Приказов пока нет',
  default_sort: { column: 'number', direction: 'desc' },
  columns: [
    {
      id: 'number', title: '№', type: 'index', width_px: 56,
      sortable: true, filters: [], filter_label: null, header_icon: null,
      searchable: false, stub: false, scale_min: null, scale_max: null,
    },
    {
      id: 'title', title: 'Название', type: 'action_text', width_px: 236,
      sortable: true, filters: ['text'], filter_label: null,
      header_icon: null, searchable: true, stub: false,
      scale_min: null, scale_max: null,
    },
    {
      id: 'submitted', title: 'Подача', type: 'datetime', width_px: 136,
      sortable: true, filters: ['date_range', 'presence'],
      filter_label: null, header_icon: 'stage_submitted',
      searchable: false, stub: false, scale_min: null, scale_max: null,
    },
  ],
};

const ROWS = [
  {
    key: 'o12',
    cells: {
      number: 12,
      title: { text: 'Мобилизация резерва', action: 'order:12' },
      submitted: {
        date: '15.10.2026', time: '21:21', key: 1, day: 1, mark: null,
      },
    },
  },
];

function renderTable() {
  return render(
    <RegistryTable
      table={ORDERS_TABLE}
      rows={ROWS}
      view={EMPTY_VIEW}
      onSortClick={() => {}}
    />,
  );
}

afterEach(clearCellActions);

describe('RegistryTable — action_text cells', () => {
  it('a click on the cell calls the handler registered under the action prefix', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    registerCellAction('order', spy);
    renderTable();

    await user.click(
      screen.getByRole('button', { name: 'Мобилизация резерва' }),
    );
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('12');

    // No handler registered — the click does nothing (and throws not).
    clearCellActions();
    await user.click(
      screen.getByRole('button', { name: 'Мобилизация резерва' }),
    );
  });
});

describe('RegistryTable — header icon', () => {
  it('shows the icon with the column title as tooltip and accessible label', () => {
    renderTable();

    // The title text is not rendered — the icon replaces it — but it
    // stays the tooltip and the accessible name of the header.
    const icon = screen.getByTestId('header-icon-stage_submitted');
    expect(icon).toHaveAttribute('title', 'Подача');
    expect(icon).toHaveAttribute('role', 'img');
    expect(icon).toHaveAttribute('aria-label', 'Подача');
    expect(
      screen.getByTestId('header-icon-stage_submitted'),
    ).toBeInTheDocument();
  });
});
