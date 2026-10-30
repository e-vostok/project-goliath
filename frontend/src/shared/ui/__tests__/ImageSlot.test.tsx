/**
 * ImageSlot (shared element, version 0.12.0 unit 6; UI Spec 6,
 * элемент 13): a non-interactive slot is a plain picture/stub with no
 * button; an interactive one is ONE <button> that opens the hidden
 * file input and reports the picked File; only the registration size
 * shows the «Загрузить» pill; a broken picture falls back to the stub.
 * Plus FlagStub's nation-colour fill (UI Spec 6, элемент 8).
 */

import { fireEvent, render, screen } from '@testing-library/react';

import { FlagStub } from '../FlagStub';
import { ImageSlot } from '../ImageSlot';

describe('ImageSlot', () => {
  it('non-interactive renders no button — just the stub', () => {
    render(
      <ImageSlot
        kind="flag"
        size="shtab"
        src={null}
        alt="Флаг"
        interactive={false}
      />,
    );

    expect(screen.queryByRole('button')).toBeNull();
    expect(
      screen.getByRole('img', { name: 'Заглушка флага' }),
    ).toBeInTheDocument();
  });

  it('interactive click opens the file input and passes the chosen file', () => {
    const onPick = vi.fn();
    const { container } = render(
      <ImageSlot
        kind="flag"
        size="shtab"
        src={null}
        alt="Флаг"
        interactive
        onPick={onPick}
      />,
    );

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input).toHaveAttribute(
      'accept',
      'image/jpeg,image/png,image/webp',
    );
    const clickSpy = vi.spyOn(input, 'click');

    fireEvent.click(screen.getByRole('button', { name: 'Загрузить флаг' }));
    expect(clickSpy).toHaveBeenCalledTimes(1);

    const file = new File(['xx'], 'flag.png', { type: 'image/png' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onPick).toHaveBeenCalledWith(file);
  });

  it('the registration size shows the «Загрузить» pill; «Штаб» shows none', () => {
    const { unmount } = render(
      <ImageSlot
        kind="flag"
        size="registration"
        src={null}
        stubColor="#2b2db0"
        alt="Флаг"
        interactive
      />,
    );
    expect(screen.getByText('Загрузить')).toBeInTheDocument();
    expect(
      screen.getByText('Нажмите на заглушку, чтобы выбрать картинку флага.'),
    ).toBeInTheDocument();

    unmount();
    render(
      <ImageSlot
        kind="flag"
        size="shtab"
        src={null}
        stubColor="#2b2db0"
        alt="Флаг"
        interactive
      />,
    );
    expect(screen.queryByText('Загрузить')).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Нажмите на заглушку/),
    ).not.toBeInTheDocument();
  });

  it('a picture that fails to load falls back to the stub', () => {
    const { container } = render(
      <ImageSlot
        kind="portrait"
        size="shtab"
        src="/broken/portrait.webp"
        alt="Портрет"
        interactive={false}
      />,
    );

    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(
      screen.getByRole('img', { name: 'Заглушка портрета' }),
    ).toBeInTheDocument();
  });

  it('the focus ring is keyboard-only: a pointer-focus shows none, Tab focus does', () => {
    render(
      <ImageSlot
        kind="flag"
        size="shtab"
        src={null}
        alt="Флаг"
        interactive
      />,
    );
    const button = screen.getByRole('button', { name: 'Загрузить флаг' });
    // jsdom cannot tell a click-focus from a Tab-focus — emulate the
    // browser's :focus-visible answer on the button itself.
    const matches = vi
      .spyOn(button, 'matches')
      .mockImplementation(() => false);
    fireEvent.focus(button);
    expect(button.style.outline).toBe('none');
    fireEvent.blur(button);
    matches.mockImplementation(() => true);
    fireEvent.focus(button);
    expect(button.style.outline).toContain('2px');
  });

  it('busy keeps the block and ignores clicks', () => {
    const onPick = vi.fn();
    const { container } = render(
      <ImageSlot
        kind="flag"
        size="shtab"
        src="/img/f.webp"
        alt="Флаг"
        interactive
        busy
        onPick={onPick}
      />,
    );

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(
      screen.getByRole('button', { name: 'Загрузить другой флаг' }),
    );
    expect(clickSpy).not.toHaveBeenCalled();
    expect(screen.getByText('Обработка…')).toBeInTheDocument();
  });
});

describe('FlagStub', () => {
  it('fills the given nation colour instead of surface-inset', () => {
    const { container } = render(
      <FlagStub variant="card" color="#2b2db0" />,
    );
    expect(container.querySelector('rect')).toHaveAttribute(
      'fill',
      '#2b2db0',
    );
  });
});
