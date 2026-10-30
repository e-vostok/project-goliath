/**
 * NationImageEditor (version 0.12.0 unit 6b): what a nation card
 * block needs to turn its image slot into an upload control — the
 * loaded rules (for the tooltip numbers) and the callback that hands
 * the picked file to the owner of the preview window. Without it the
 * slot renders read-only — that is the other players' nation on the
 * Registry subscreen, where nothing is clickable.
 */

import type { NationRulesDTO } from '../../../shared/types';
import type { ImageSlotKind } from '../../../shared/ui';
import { imageUploadMb } from './imageErrorTexts';

export interface NationImageEditor {
  rules: NationRulesDTO | null;
  onUpload: (kind: ImageSlotKind, file: File) => void;
}

/** The hover tooltip of an interactive slot (UI Spec 6, element 13):
 * first line always, the «Лучше …» line once the rules are known. */
export function imageSlotHint(
  kind: ImageSlotKind,
  loaded: boolean,
  rules: NationRulesDTO | null,
): { first: string; second?: string } {
  const word = kind === 'flag' ? 'флаг' : 'портрет';
  const first = loaded
    ? `Нажмите, чтобы загрузить другой ${word}`
    : `Нажмите, чтобы загрузить ${word}`;
  if (rules === null) {
    return { first };
  }
  const images = rules.images;
  const dims =
    kind === 'flag'
      ? `${images.flag_width}×${images.flag_height}`
      : `${images.portrait_width}×${images.portrait_height}`;
  const mb = imageUploadMb(images.max_upload_bytes);
  return {
    first,
    second: `Лучше ${dims} · JPEG, PNG, WebP · до ${mb} МБ`,
  };
}

/** Tail of the registration failure notice — the nation exists, the
 * picture can be uploaded later in «Штаб» (Spec «Порядок в окне
 * регистрации»; board 16 carries no exact sentence — TZ fallback). */
export function imageUploadLaterText(kind: ImageSlotKind): string {
  return kind === 'flag'
    ? 'Государство создано, но флаг не загрузился. Загрузите его позже в «Штабе» — щелчком по флагу.'
    : 'Государство создано, но портрет не загрузился. Загрузите его позже в «Штабе» — щелчком по портрету.';
}

/** Tail of the registration failure notice when BOTH pictures failed —
 * the one danger notice ends with this sentence after the two reasons
 * (0.12.0 unit 7; the notice slot shows a single message). */
export const imageUploadLaterBothText =
  'Государство создано, но флаг и портрет не загрузились. Загрузите их позже в «Штабе» — щелчком по флагу и по портрету.';
