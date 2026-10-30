/**
 * ImageUploadPreview (version 0.12.0 unit 6; boards 15/15б/16): local
 * checks replace the preview with the error block (too large,
 * undecodable, wrong orientation per kind), a happy file shows the
 * size line and `onConfirm` gets the ORIGINAL File, server IMAGE_*
 * codes reuse the same texts, a network failure offers «Повторить»
 * which re-runs `onConfirm`.
 *
 * jsdom has no `createImageBitmap` and no canvas — both are stubbed
 * narrowly here (the canvas ctx stays absent; drawing is skipped).
 */

import { useMemo, useState, type ReactNode } from 'react';
import {
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { ApiError } from '../../../../shared/api-client';
import { PopupHost } from '../../../../shared/ui';
import { ImageUploadPreview } from '../ImageUploadPreview';
import type { ImageUploadPreviewProps } from '../ImageUploadPreview';
import { RULES } from './helpers';

const noop = () => Promise.resolve();

function renderPreview(props: Partial<ImageUploadPreviewProps> = {}) {
  function Harness({ children }: { children?: ReactNode }) {
    const [el, setEl] = useState<HTMLDivElement | null>(null);
    const container = useMemo(() => ({ current: el }), [el]);
    return (
      <ConfigProvider platform={Platform.VKCOM}>
        <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
          <AppRoot>
            <div ref={setEl}>
              <PopupHost container={container}>{children}</PopupHost>
            </div>
          </AppRoot>
        </AdaptivityProvider>
      </ConfigProvider>
    );
  }
  return render(
    <Harness>
      <ImageUploadPreview
        kind="flag"
        mode="replace"
        file={new File(['x'], 'severny.jpg', { type: 'image/jpeg' })}
        rules={RULES}
        onConfirm={noop}
        onPickAnother={noop}
        onClose={noop}
        {...props}
      />
    </Harness>,
  );
}

/** Tells the stubbed decoder the bitmap size to answer. */
function stubBitmap(width: number, height: number) {
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(async () => ({ width, height, close: () => {} }) as ImageBitmap),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ImageUploadPreview', () => {
  it('a file above the limit shows «Файл больше N МБ…» and no confirm', async () => {
    const big = new File([new Uint8Array(6_400_000)], 'big.png', {
      type: 'image/png',
    });
    renderPreview({ file: big });

    expect(
      await screen.findByText(
        'Файл больше 6 МБ. Сожмите картинку или выберите другую.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Файл слишком большой')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Загрузить флаг' }),
    ).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Выбрать другой файл' }),
    ).toBeInTheDocument();
  });

  it('an undecodable file shows the IMAGE_UNSUPPORTED text', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => {
        throw new Error('nope');
      }),
    );
    renderPreview({
      file: new File(['not image'], 'fake.jpg', { type: 'image/jpeg' }),
    });

    expect(
      await screen.findByText(
        'Это не картинка. Подойдут файлы JPEG, PNG и WebP.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Загрузить флаг' }),
    ).toBeNull();
  });

  it('a square flag shows the flag orientation text', async () => {
    stubBitmap(800, 800);
    renderPreview();

    expect(
      await screen.findByText(
        'Флаг должен быть горизонтальным: ширина больше высоты. Выберите другую картинку.',
      ),
    ).toBeInTheDocument();
  });

  it('a horizontal portrait shows the portrait orientation text', async () => {
    stubBitmap(1200, 800);
    renderPreview({
      kind: 'portrait',
      file: new File(['x'], 'portret.png', { type: 'image/png' }),
    });

    expect(
      await screen.findByText(
        'Портрет должен быть вертикальным: высота больше ширины. Выберите другую картинку.',
      ),
    ).toBeInTheDocument();
  });

  it('a happy file shows the size line and sends the ORIGINAL file', async () => {
    stubBitmap(1920, 1080);
    const file = new File(['x'], 'severny.jpg', { type: 'image/jpeg' });
    const onConfirm = vi.fn(noop);
    const user = userEvent.setup();
    renderPreview({ file, onConfirm });

    expect(
      await screen.findByText(/severny\.jpg · 1920×1080 → 610×410/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Прежний флаг заменится новым и будет удалён с сервера.',
      ),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Загрузить флаг' }),
    );
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(file));
  });

  it('a server IMAGE_ORIENTATION_INVALID lands in the same block', async () => {
    stubBitmap(1920, 1080);
    const onConfirm = vi.fn(async () => {
      throw new ApiError(422, 'IMAGE_ORIENTATION_INVALID', 'orient');
    });
    const user = userEvent.setup();
    renderPreview({ onConfirm });

    await screen.findByText(/severny\.jpg · 1920×1080/);
    await user.click(
      screen.getByRole('button', { name: 'Загрузить флаг' }),
    );
    expect(
      await screen.findByText(
        'Флаг должен быть горизонтальным: ширина больше высоты. Выберите другую картинку.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Выбрать другой файл' }),
    ).toBeInTheDocument();
  });

  it('a network failure shows «Повторить», which re-runs onConfirm', async () => {
    stubBitmap(1920, 1080);
    const onConfirm = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const user = userEvent.setup();
    renderPreview({ onConfirm });

    await screen.findByText(/severny\.jpg · 1920×1080/);
    await user.click(
      screen.getByRole('button', { name: 'Загрузить флаг' }),
    );
    expect(
      await screen.findByText('Ошибка сети — попробуйте ещё раз.'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(2));
  });
});
