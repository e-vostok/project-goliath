/**
 * Russian player-facing texts for the image upload failures
 * (Spec Part 5 «Русские тексты ошибок», version 0.12.0 unit 6).
 *
 * Sibling of `nationErrorTexts.ts` — separate because the texts need
 * the picture kind and `rules.images.max_upload_bytes` for the «N МБ»
 * number, which is computed here, never hardcoded. `imageErrorText`
 * answers the three IMAGE_* wordings and falls back to the shared
 * `errorText` for anything else (network, 401, 5xx, unknown code).
 */

import { ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { ErrorCodes } from '../../../shared/types';
import type { NationRulesDTO } from '../../../shared/types';

export type NationImageKind = 'flag' | 'portrait';

/**
 * «5 МБ» from `rules.images.max_upload_bytes` — the Spec's «{N} МБ»
 * is mebibytes rounded to the nearest integer (5242880 → 5).
 */
export function imageUploadMb(maxUploadBytes: number): number {
  return Math.max(1, Math.round(maxUploadBytes / 1048576));
}

export function imageErrorText(
  error: unknown,
  kind: NationImageKind,
  rules: NationRulesDTO | null,
): string {
  const code = error instanceof ApiError ? error.code : null;
  switch (code) {
    case ErrorCodes.IMAGE_UNSUPPORTED:
      return 'Это не картинка. Подойдут файлы JPEG, PNG и WebP.';
    case ErrorCodes.IMAGE_TOO_LARGE:
      return rules
        ? `Файл больше ${imageUploadMb(rules.images.max_upload_bytes)} МБ. Сожмите картинку или выберите другую.`
        : 'Файл слишком большой. Сожмите картинку или выберите другую.';
    case ErrorCodes.IMAGE_ORIENTATION_INVALID:
      return kind === 'flag'
        ? 'Флаг должен быть горизонтальным: ширина больше высоты. Выберите другую картинку.'
        : 'Портрет должен быть вертикальным: высота больше ширины. Выберите другую картинку.';
    default:
      return errorText(error, { rules });
  }
}
