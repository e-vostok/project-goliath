/**
 * Russian player-facing texts for the server `ErrorResponse.code` values
 * of nation create/update (Spec Part 5 «Русские тексти ошибок»).
 *
 * `nationErrorText` returns null for codes without a dictionary entry —
 * the caller then shows the English `detail` verbatim (e.g. the 01_map
 * PROVINCE_* codes, whose wording is owned by that module). Limits in
 * the *_INVALID texts are read from GET /nations/rules, never hardcoded;
 * when rules are unavailable a shorter fallback without numbers is used.
 */

import { ErrorCodes } from '../../../shared/types';
import type { ColorCheckDTO, NationRulesDTO } from '../../../shared/types';

/** «от N до M символов» when the bounds are known, else a numberless tail. */
function range(rules: NationRulesDTO | null, min?: number, max?: number): string {
  if (rules !== null && min !== undefined && max !== undefined) {
    return `от ${min} до ${max} символов, `;
  }
  return '';
}

export function nationErrorText(
  code: string,
  rules: NationRulesDTO | null,
): string | null {
  switch (code) {
    case ErrorCodes.NAME_TAKEN:
      return 'Это название уже занято';
    case ErrorCodes.SHORT_NAME_TAKEN:
      return 'Это краткое название уже занято';
    case ErrorCodes.COLOR_TAKEN:
      return 'Этот цвет уже занят другим государством';
    case ErrorCodes.COLOR_TOO_CLOSE:
      return 'Цвет слишком похож на цвет другого государства или карты. Выберите другой';
    case ErrorCodes.SHORT_NAME_INVALID:
      return `Краткое название: ${range(rules, rules?.short_name_min_length, rules?.short_name_max_length)}без служебных символов`;
    case ErrorCodes.MOTTO_INVALID:
      return rules
        ? `Девиз: не более ${rules.motto_max_length} символов, без служебных символов`
        : 'Недопустимый девиз';
    case ErrorCodes.DESCRIPTION_INVALID:
      return rules
        ? `Описание: не более ${rules.description_max_length} символов, без служебных символов`
        : 'Недопустимое описание';
    case ErrorCodes.LEADER_NAME_INVALID:
      return `Имя лидера: ${range(rules, rules?.leader_name_min_length, rules?.leader_name_max_length)}без служебных символов`;
    case ErrorCodes.GENDER_INVALID:
      return 'Выберите пол лидера';
    case ErrorCodes.LEADER_TITLE_INVALID:
      return `Должность лидера: ${range(rules, rules?.leader_title_min_length, rules?.leader_title_max_length)}без служебных символов`;
    case ErrorCodes.LEADER_BIO_INVALID:
      return rules
        ? `Биография лидера: не более ${rules.leader_bio_max_length} символов, без служебных символов`
        : 'Недопустимая биография лидера';
    case ErrorCodes.SUCCESSION_INVALID:
      return 'Выберите способ смены лидера';
    case ErrorCodes.HISTORY_URL_INVALID:
      return 'Ссылка должна вести на статью ВКонтакте вида https://vk.com/@название-статьи';
    case ErrorCodes.CAPITAL_NAME_INVALID:
      return `Название столицы: ${range(rules, rules?.capital_name_min_length, rules?.capital_name_max_length)}без служебных символов`;
    case ErrorCodes.CAPITAL_NOT_IN_PROVINCES:
      return 'Столица должна быть одной из выбранных провинций';
    default:
      return null;
  }
}

/**
 * The live color-check hint under the HEX field on tab 1 (Spec Part 5:
 * POST /nations/color-check is the unlocked preview of what POST
 * /nations would decide — the hint never blocks the submit button, the
 * server decides at submit). TAKEN/TOO_CLOSE reuse the dictionary
 * wording so the player sees the same phrase on submit.
 */
export function nationColorCheckText(status: ColorCheckDTO['status']): string {
  switch (status) {
    case 'OK':
      return 'Цвет свободен';
    case 'TAKEN':
      return nationErrorText(ErrorCodes.COLOR_TAKEN, null) as string;
    case 'TOO_CLOSE':
      return nationErrorText(ErrorCodes.COLOR_TOO_CLOSE, null) as string;
  }
}
