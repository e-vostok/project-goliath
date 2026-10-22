/**
 * Subscreen — the «Подэкран» return band (UI Spec 3.2, unit 14c):
 * the 48 px band with the 4 px `action` mark, the «← parent» button
 * and the path chain whose last segment is the current place.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { Subscreen } from '../Subscreen';

function renderSubscreen(
  props: Partial<Parameters<typeof Subscreen>[0]> = {},
) {
  return render(
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <Subscreen
            parentLabel="Реестр"
            trail={['Игроки', 'Новгород']}
            onBack={() => {}}
            {...props}
          >
            <div>Тело подэкрана</div>
          </Subscreen>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>,
  );
}

describe('Subscreen', () => {
  it('renders the return band with the «← parent» button and the path chain', () => {
    renderSubscreen();

    const band = screen.getByTestId('subscreen-band');
    expect(band).toBeInTheDocument();
    // 48 px band, 4 px accent mark on the left edge.
    expect(band.style.height).toBe('48px');
    expect(screen.getByTestId('subscreen-mark').style.width).toBe('4px');

    // The back button and the chain «Реестр / Игроки / Новгород».
    expect(
      screen.getByRole('button', { name: '← Реестр' }),
    ).toBeInTheDocument();
    const trail = screen.getByTestId('subscreen-trail');
    expect(trail.textContent).toBe('Реестр / Игроки / Новгород');
    // The last segment is the current place — rendered in `ink`.
    const last = trail.lastElementChild as HTMLElement;
    expect(last.style.color).toBe('var(--pax-ink)');
  });

  it('ellipsizes a long final segment and never wraps the band', () => {
    renderSubscreen({
      trail: ['Игроки', 'Очень длинное название государства, которое не помещается в полосу'],
    });
    const trail = screen.getByTestId('subscreen-trail');
    const last = trail.lastElementChild as HTMLElement;
    expect(last.style.textOverflow).toBe('ellipsis');
    expect(last.style.whiteSpace).toBe('nowrap');
    expect(
      (screen.getByTestId('subscreen-band') as HTMLElement).style
        .whiteSpace,
    ).toBe('nowrap');
  });

  it('calls onBack from the «← parent» button; Esc does not go back', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    renderSubscreen({ onBack });

    await user.keyboard('{Escape}');
    expect(onBack).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '← Реестр' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('never shows the word «Подэкран» on screen', () => {
    renderSubscreen();
    expect(screen.queryByText(/Подэкран/)).not.toBeInTheDocument();
    expect(screen.getByText('Тело подэкрана')).toBeInTheDocument();
  });
});
