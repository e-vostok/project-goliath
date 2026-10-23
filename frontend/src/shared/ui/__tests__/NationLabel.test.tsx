/**
 * NationLabel (shared element, version 0.10.0 unit 6a): the flag
 * image when a URL is given, a same-size colour block when the URL is
 * missing or the image fails to load, and FlagStub when there is no
 * colour either.
 */

import { fireEvent, render, screen } from '@testing-library/react';

import { NationLabel } from '../NationLabel';

describe('NationLabel', () => {
  it('shows the flag image at the cell size next to the name', () => {
    const { container } = render(
      <NationLabel
        name="НВГ"
        flagUrl="/assets/nations/flags/f1.png"
        color="#C0392B"
        size="cell"
      />,
    );

    const img = container.querySelector('img')!;
    expect(img).toHaveAttribute('src', '/assets/nations/flags/f1.png');
    expect(img).toHaveAttribute('width', '22');
    expect(img).toHaveAttribute('height', '14');
    expect(screen.getByText('НВГ')).toBeInTheDocument();
  });

  it('a broken flag falls back to a colour block of the same size — not a dot', () => {
    const { container } = render(
      <NationLabel
        name="НВГ"
        flagUrl="/assets/nations/flags/broken.png"
        color="#C0392B"
        size="cell"
      />,
    );

    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();

    const block = container.querySelector('[aria-hidden]') as HTMLElement;
    expect(block.style.background).toBe('rgb(192, 57, 43)');
    expect(block.style.width).toBe('22px');
    expect(block.style.height).toBe('14px');
    expect(block.style.borderRadius).toBe('2px');
    expect(screen.getByText('НВГ')).toBeInTheDocument();
  });

  it('no flag and no colour shows the FlagStub', () => {
    render(<NationLabel name="Безвестная вотчина" size="cell" />);

    expect(
      screen.getByRole('img', { name: 'Заглушка флага' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Безвестная вотчина')).toBeInTheDocument();
  });
});
