/**
 * BlockTitle (UI Spec 5.3 / 6, элемент 2): the filling `line` renders
 * by default and is dropped by `line={false}` (the screen title that
 * shares its row with content — mockup «Registry»).
 */

import { render, screen } from '@testing-library/react';

import { BlockTitle } from '../BlockTitle';

describe('BlockTitle', () => {
  it('renders the filling line by default and drops it with line={false}', () => {
    const { rerender } = render(
      <BlockTitle icon="list" title="Реестр" />,
    );
    const title = screen.getByRole('heading', { name: 'Реестр' });
    expect(
      screen.getByTestId('block-title-line'),
    ).toBeInTheDocument();
    expect(title).toContainElement(screen.getByTestId('block-title-line'));

    rerender(<BlockTitle icon="list" title="Реестр" line={false} />);
    expect(
      screen.queryByTestId('block-title-line'),
    ).not.toBeInTheDocument();
    // Icon and text are unaffected.
    expect(
      screen.getByRole('heading', { name: 'Реестр' }),
    ).toBeInTheDocument();
  });
});
