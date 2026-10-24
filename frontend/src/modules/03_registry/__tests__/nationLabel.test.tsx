/**
 * Unit 6a registry wiring: `NationCell` renders the shared
 * `NationLabel` (the flag image when the cell carries `flag_url`),
 * a nations-table row whose «name» cell is a `nation` cell links to
 * the subscreen by the CELL id — the row-key special case stays for
 * string cells only — and `nationNamesOfTable` reads names from
 * string and nation cells alike (the future 6b shape).
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NationCell } from '../components/cells/NationCell';
import { RegistryTable } from '../components/RegistryTable';
import { nationNamesOfTable } from '../lib/nationOptions';
import { EMPTY_VIEW } from '../lib/tableView';
import type {
  RegistryCell,
  RegistryRowDTO,
  RegistryRowsDTO,
  RegistryTableDTO,
} from '../types';

const NATIONS_TABLE: RegistryTableDTO = {
  id: 'nations',
  title: 'Государства',
  icon: 'nations',
  empty_text: 'Государств пока нет',
  default_sort: { column: 'number', direction: 'asc' },
  columns: [
    {
      id: 'number',
      title: '№',
      type: 'index',
      width_px: 48,
      sortable: true,
      filters: [],
      filter_label: null,
      header_icon: null,
      searchable: false,
      stub: false,
      scale_min: null,
      scale_max: null,
    },
    {
      id: 'name',
      title: 'Название',
      type: 'text',
      width_px: 430,
      sortable: true,
      filters: ['text'],
      filter_label: null,
      header_icon: null,
      searchable: true,
      stub: false,
      scale_min: null,
      scale_max: null,
    },
  ],
};

function rowsOf(cells: Record<string, RegistryCell>): RegistryRowsDTO {
  return {
    table_id: 'nations',
    total: 1,
    truncated: false,
    generated_at: '2026-10-23T10:00:00Z',
    rows: [{ key: 'row-1', cells }],
  };
}

describe('NationCell — unit 6a look', () => {
  it('renders the flag image when the cell carries flag_url', () => {
    const { container } = render(
      <NationCell
        value={{
          id: 'n1',
          name: 'НВГ',
          color: '#C0392B',
          flag_url: '/assets/nations/flags/f1.png',
        }}
      />,
    );

    const img = container.querySelector('img')!;
    expect(img).toHaveAttribute('src', '/assets/nations/flags/f1.png');
    expect(img).toHaveAttribute('width', '22');
    expect(img).toHaveAttribute('height', '14');
    expect(screen.getByText('НВГ')).toBeInTheDocument();
  });
});

describe('RegistryTable — a nation cell in the «name» column (6b shape)', () => {
  it('links to the subscreen by the cell id, not the row key', async () => {
    const user = userEvent.setup();
    const onOpenNation = vi.fn();
    const nationCellValue: RegistryCell = {
      id: 'nation-uuid-9',
      name: 'НВГ',
      color: '#C0392B',
      flag_url: null,
    };
    render(
      <RegistryTable
        table={NATIONS_TABLE}
        rows={rowsOf({ number: 1, name: nationCellValue }).rows}
        view={EMPTY_VIEW}
        onSortClick={() => {}}
        onOpenNation={onOpenNation}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'НВГ' }));
    expect(onOpenNation).toHaveBeenCalledTimes(1);
    expect(onOpenNation).toHaveBeenCalledWith('nation-uuid-9');
  });
});

describe('nationNamesOfTable — both cell shapes', () => {
  const rows = (names: RegistryCell[]): RegistryRowDTO[] =>
    names.map((name, i) => ({
      key: `n${i}`,
      cells: { number: i + 1, name },
    }));

  it('reads names from plain string cells (today)', () => {
    const dto = nationNamesOfTable(NATIONS_TABLE, {
      table_id: 'nations',
      total: 2,
      truncated: false,
      generated_at: '2026-10-23T10:00:00Z',
      rows: rows(['Рязань', 'Новгород']),
    });
    expect(dto).toEqual(['Новгород', 'Рязань']);
  });

  it('reads names from nation cells (the 6b shape)', () => {
    const cell = (name: string): RegistryCell => ({
      id: `id-${name}`,
      name,
      color: '#336699',
      flag_url: null,
    });
    const dto = nationNamesOfTable(NATIONS_TABLE, {
      table_id: 'nations',
      total: 2,
      truncated: false,
      generated_at: '2026-10-23T10:00:00Z',
      rows: rows([cell('Рязань'), cell('Новгород')]),
    });
    expect(dto).toEqual(['Новгород', 'Рязань']);
  });
});
