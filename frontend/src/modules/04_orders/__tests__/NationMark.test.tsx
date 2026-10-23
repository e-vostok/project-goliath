/**
 * NationMark (unit 6a): the order's author-nation snapshot renders the
 * shared `NationLabel` — the submission-time SHORT name and the flag,
 * never the full name.
 */

import { render, screen } from '@testing-library/react';

import { NationMark } from '../components/NationMark';
import type { NationMarkDTO } from '../types';

const NATION: NationMarkDTO = {
  name: 'Новгородская республика',
  color: '#C0392B',
  short_name: 'НВГ',
  flag_url: '/assets/nations/flags/f1.png',
};

describe('NationMark', () => {
  it('shows the short name and the flag image, not the full name', () => {
    const { container } = render(<NationMark nation={NATION} />);

    expect(screen.getByText('НВГ')).toBeInTheDocument();
    expect(
      screen.queryByText('Новгородская республика'),
    ).not.toBeInTheDocument();
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      '/assets/nations/flags/f1.png',
    );
  });
});
