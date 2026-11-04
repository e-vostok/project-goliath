/**
 * RatingScale (mockups 26/26б/26в, unit 11b): the five states of the
 * table scale — fill side and width, knob position, no fill at zero,
 * the aria-label with the real figure — plus a clamped out-of-range
 * value; the «Рейтинг» column header's «Подсказка» on hover AND on
 * keyboard focus; the tile variant's bigger geometry.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import type { ReactElement } from 'react';

import { TOOLTIP_DELAY_MS } from '../../../shared/ui';
import { EMPTY_VIEW } from '../lib/tableView';
import { RegistryTable } from '../components/RegistryTable';
import { RatingScale } from '../components/RatingScale';
import type { RegistryTableDTO } from '../types';
import { SESSION } from './helpers';
import { SessionProvider } from '../../00_core/hooks/useAuth';

// jsdom has no PointerEvent — MouseEvent carries clientX/Y, all the
// pointer handlers under test read.
if (window.PointerEvent === undefined) {
  vi.stubGlobal('PointerEvent', window.MouseEvent);
}

const PLAYERS_TABLE: RegistryTableDTO = {
  id: 'players',
  title: 'Игроки',
  icon: 'players',
  empty_text: 'Игроков пока нет',
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
      id: 'judge_rating',
      title: 'Рейтинг',
      type: 'gauge',
      width_px: 112,
      sortable: true,
      filters: ['number_range'],
      filter_label: null,
      header_icon: null,
      searchable: false,
      stub: true,
      scale_min: -100,
      scale_max: 100,
    },
  ],
};

function renderInRoot(ui: ReactElement) {
  return render(
    <SessionProvider session={SESSION}>
      <div data-testid="app-root" style={{ position: 'relative' }}>
        {ui}
      </div>
    </SessionProvider>,
  );
}

const tip = () => screen.queryByRole('tooltip');

afterEach(() => {
  vi.useRealTimers();
});

describe('RatingScale — geometry and label', () => {
  it('draws the five mockup states and clamps an out-of-range value', () => {
    const { rerender } = render(
      <RatingScale value={35} min={-100} max={100} />,
    );
    const scale = () => screen.getByTestId('rating-scale');
    const fill = () => screen.queryByTestId('rating-fill');
    const knob = () => screen.getByTestId('rating-knob');

    // +35 — green fill grows right of the centre (0.5 → 0.675).
    expect(scale()).toHaveAttribute('role', 'img');
    expect(scale()).toHaveAttribute(
      'aria-label',
      'Рейтинг +35 из диапазона −100…+100',
    );
    expect(fill()!.style.background).toBe('var(--pax-positive)');
    expect(fill()!.style.left).toBe('calc(5px + 0.5 * (100% - 10px))');
    expect(fill()!.style.width).toBe('calc(0.175 * (100% - 10px))');
    expect(knob().style.left).toBe('calc(5px + 0.675 * (100% - 10px))');

    // −64 — red fill grows left of the centre (0.18 → 0.5).
    rerender(<RatingScale value={-64} min={-100} max={100} />);
    expect(scale()).toHaveAttribute(
      'aria-label',
      'Рейтинг −64 из диапазона −100…+100',
    );
    expect(fill()!.style.background).toBe('var(--pax-danger)');
    expect(fill()!.style.left).toBe('calc(5px + 0.18 * (100% - 10px))');
    expect(fill()!.style.width).toBe('calc(0.32 * (100% - 10px))');
    expect(knob().style.left).toBe('calc(5px + 0.18 * (100% - 10px))');

    // 0 — no fill, the knob sits on the centre tick.
    rerender(<RatingScale value={0} min={-100} max={100} />);
    expect(scale()).toHaveAttribute(
      'aria-label',
      'Рейтинг 0 из диапазона −100…+100',
    );
    expect(fill()).toBeNull();
    expect(knob().style.left).toBe('calc(5px + 0.5 * (100% - 10px))');

    // The edges — the knob stays inside the track (inset = radius).
    rerender(<RatingScale value={-100} min={-100} max={100} />);
    expect(knob().style.left).toBe('calc(5px + 0 * (100% - 10px))');
    expect(fill()!.style.width).toBe('calc(0.5 * (100% - 10px))');
    rerender(<RatingScale value={100} min={-100} max={100} />);
    expect(knob().style.left).toBe('calc(5px + 1 * (100% - 10px))');
    expect(fill()!.style.width).toBe('calc(0.5 * (100% - 10px))');

    // +150 — drawing clamped to the edge, the label keeps the real
    // figure.
    rerender(<RatingScale value={150} min={-100} max={100} />);
    expect(scale()).toHaveAttribute(
      'aria-label',
      'Рейтинг +150 из диапазона −100…+100',
    );
    expect(knob().style.left).toBe('calc(5px + 1 * (100% - 10px))');
    expect(fill()!.style.background).toBe('var(--pax-positive)');
  });

  it('the tile variant is full-width with the 14 px knob', () => {
    render(<RatingScale value={35} min={-100} max={100} size="tile" />);
    const scale = screen.getByTestId('rating-scale');
    expect(scale.style.width).toBe('100%');
    expect(scale.style.height).toBe('8px');
    const knob = screen.getByTestId('rating-knob');
    expect(knob.style.width).toBe('14px');
    expect(knob.style.left).toBe('calc(7px + 0.675 * (100% - 14px))');
  });
});

describe('RegistryTable — the «Рейтинг» header tip', () => {
  it('opens on hover and on keyboard focus with title, text and legend scale', () => {
    vi.useFakeTimers();
    renderInRoot(
      <RegistryTable
        table={PLAYERS_TABLE}
        rows={[{ key: 'p1', cells: { number: 1, judge_rating: 35 } }]}
        view={EMPTY_VIEW}
        onSortClick={() => {}}
      />,
    );
    const header = screen.getByTestId('sort-btn-judge_rating');

    fireEvent.pointerOver(header, { clientX: 20, clientY: 20 });
    act(() => {
      vi.advanceTimersByTime(TOOLTIP_DELAY_MS);
    });
    const box = tip()!;
    expect(within(box).getByText('Судейский рейтинг')).toBeInTheDocument();
    expect(box.textContent).toContain(
      'От −100 до +100. Судьёй приказа назначают игрока с рейтингом не ниже порога.',
    );
    // The legend row: «−100», the sample scale, «+100».
    expect(
      within(box).getByRole('img', {
        name: 'Рейтинг +35 из диапазона −100…+100',
      }),
    ).toBeInTheDocument();
    expect(within(box).getByText('−100')).toBeInTheDocument();
    expect(within(box).getByText('+100')).toBeInTheDocument();

    fireEvent.pointerOut(header, { relatedTarget: document.body });
    expect(tip()).toBeNull();

    // Keyboard focus opens the same tip — no pointer needed.
    fireEvent.focusIn(header);
    expect(tip()).not.toBeNull();
    fireEvent.focusOut(header);
    expect(tip()).toBeNull();
  });
});
