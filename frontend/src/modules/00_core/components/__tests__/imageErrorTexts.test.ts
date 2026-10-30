/**
 * imageErrorTexts (version 0.12.0 unit 6): the three Spec wordings
 * for IMAGE_* codes — the «N МБ» computed from
 * `rules.images.max_upload_bytes`, the orientation wording per kind —
 * and the shared fallback for anything else.
 */

import { ApiError } from '../../../../shared/api-client';
import { NETWORK_ERROR_TEXT } from '../../../../shared/ui';
import { imageErrorText, imageUploadMb } from '../imageErrorTexts';
import { RULES } from './helpers';

describe('imageErrorText', () => {
  it('computes «N МБ» from rules.images.max_upload_bytes', () => {
    expect(imageUploadMb(RULES.images.max_upload_bytes)).toBe(6);
    expect(
      imageErrorText(
        new ApiError(413, 'IMAGE_TOO_LARGE', 'too large'),
        'flag',
        RULES,
      ),
    ).toBe('Файл больше 6 МБ. Сожмите картинку или выберите другую.');
    // No rules — the number is not invented.
    expect(
      imageErrorText(
        new ApiError(413, 'IMAGE_TOO_LARGE', 'too large'),
        'flag',
        null,
      ),
    ).toBe('Файл слишком большой. Сожмите картинку или выберите другую.');
  });

  it('the orientation wording differs per kind', () => {
    const err = new ApiError(422, 'IMAGE_ORIENTATION_INVALID', 'orient');
    expect(imageErrorText(err, 'flag', RULES)).toBe(
      'Флаг должен быть горизонтальным: ширина больше высоты. Выберите другую картинку.',
    );
    expect(imageErrorText(err, 'portrait', RULES)).toBe(
      'Портрет должен быть вертикальным: высота больше ширины. Выберите другую картинку.',
    );
    expect(
      imageErrorText(
        new ApiError(415, 'IMAGE_UNSUPPORTED', 'bad'),
        'portrait',
        RULES,
      ),
    ).toBe('Это не картинка. Подойдут файлы JPEG, PNG и WebP.');
  });

  it('anything else falls back to the shared errorText', () => {
    expect(imageErrorText(new TypeError('Failed to fetch'), 'flag', RULES)).toBe(
      NETWORK_ERROR_TEXT,
    );
    expect(
      imageErrorText(new ApiError(401, 'UNAUTHORIZED', 'x'), 'flag', RULES),
    ).toBe('Сессия устарела — откройте приложение заново.');
  });
});
