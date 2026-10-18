/**
 * The pure form model of the registration window (Spec 1.3 Part 5).
 *
 * One `RegistrationForm` object carries every NationCreateRequest field
 * across the four tabs, so switching tabs never loses or sends anything.
 * `fieldToTab` places each field on its tab, `mapErrorCodeToField` turns
 * a server `ErrorResponse.code` into the field that shows it inline,
 * `missingRequired` lists the still-empty mandatory fields (it gates the
 * single submit button and feeds the tab badges), and `toCreateRequest`
 * builds the POST /nations body.
 *
 * No React here — the container and the tests import the same logic.
 */

import { ErrorCodes } from '../../../shared/types';
import type {
  NationCreateRequest,
  NationRulesDTO,
} from '../../../shared/types';

export type RegistrationTab = 1 | 2 | 3 | 4;

/** A picked province shown as a named chip; order = selection order. */
export interface ChipOption {
  value: number;
  label: string;
}

/**
 * All create fields of Spec 1.3. Optional text fields hold '' (sent as
 * null), catalog picks hold null, and `capitalProvinceId` is null unless
 * the player explicitly marked a capital — the server then defaults it
 * to the first selected province (INV-14).
 */
export interface RegistrationForm {
  name: string;
  shortName: string;
  color: string;
  motto: string;
  description: string;
  flagId: string | null;
  leaderName: string;
  gender: string;
  leaderTitle: string;
  leaderBio: string;
  portraitId: string | null;
  successionType: string;
  historyUrl: string;
  anthemUrl: string;
  provinces: ChipOption[];
  capitalProvinceId: number | null;
  capitalName: string;
}

/** Field keys shared by the wizard and the edit form error mapping. */
export type NationField = keyof RegistrationForm;

/** Session-draft key; v1 drafts under 'nation-create' are ignored. */
export const REGISTRATION_DRAFT_KEY = 'nation-create-v2';

export function emptyRegistrationForm(): RegistrationForm {
  return {
    name: '',
    shortName: '',
    color: '#e64545',
    motto: '',
    description: '',
    flagId: null,
    leaderName: '',
    gender: '',
    leaderTitle: '',
    leaderBio: '',
    portraitId: null,
    successionType: '',
    historyUrl: '',
    anthemUrl: '',
    provinces: [],
    capitalProvinceId: null,
    capitalName: '',
  };
}

/**
 * true when nothing player-authored was entered yet — used to drop the
 * session draft. `color` is excluded: it always holds a pickable default,
 * not user content.
 */
export function registrationFormIsEmpty(form: RegistrationForm): boolean {
  return (
    form.name === '' &&
    form.shortName === '' &&
    form.motto === '' &&
    form.description === '' &&
    form.flagId === null &&
    form.leaderName === '' &&
    form.gender === '' &&
    form.leaderTitle === '' &&
    form.leaderBio === '' &&
    form.portraitId === null &&
    form.successionType === '' &&
    form.historyUrl === '' &&
    form.anthemUrl === '' &&
    form.provinces.length === 0 &&
    form.capitalProvinceId === null &&
    form.capitalName === ''
  );
}

/**
 * Defensive draft restore: anything that is not a plausible v2 form falls
 * back to the empty form (a corrupted sessionStorage entry must not
 * break the panel).
 */
export function registrationFormFromDraft(
  draft: RegistrationForm | null,
): RegistrationForm {
  if (draft === null || typeof draft !== 'object') {
    return emptyRegistrationForm();
  }
  const form = { ...emptyRegistrationForm(), ...draft };
  if (!Array.isArray(form.provinces)) {
    form.provinces = [];
  }
  return form;
}

/** Which tab of the window owns the field (Spec Part 5 tab layout). */
export function fieldToTab(field: NationField): RegistrationTab {
  switch (field) {
    case 'name':
    case 'shortName':
    case 'color':
    case 'motto':
    case 'description':
    case 'flagId':
      return 1;
    case 'leaderName':
    case 'gender':
    case 'leaderTitle':
    case 'leaderBio':
    case 'portraitId':
    case 'successionType':
      return 2;
    case 'historyUrl':
    case 'anthemUrl':
      return 3;
    case 'provinces':
    case 'capitalProvinceId':
    case 'capitalName':
      return 4;
  }
}

/** Maps ErrorResponse.code to the field that displays it inline. */
export function mapErrorCodeToField(code: string): NationField | null {
  switch (code) {
    case ErrorCodes.NAME_TAKEN:
      return 'name';
    case ErrorCodes.SHORT_NAME_TAKEN:
    case ErrorCodes.SHORT_NAME_INVALID:
      return 'shortName';
    case ErrorCodes.MOTTO_INVALID:
      return 'motto';
    case ErrorCodes.DESCRIPTION_INVALID:
      return 'description';
    case ErrorCodes.COLOR_TAKEN:
    case ErrorCodes.COLOR_TOO_CLOSE:
      return 'color';
    case ErrorCodes.FLAG_INVALID:
      return 'flagId';
    case ErrorCodes.LEADER_NAME_INVALID:
      return 'leaderName';
    case ErrorCodes.GENDER_INVALID:
      return 'gender';
    case ErrorCodes.LEADER_TITLE_INVALID:
      return 'leaderTitle';
    case ErrorCodes.LEADER_BIO_INVALID:
      return 'leaderBio';
    case ErrorCodes.PORTRAIT_INVALID:
      return 'portraitId';
    case ErrorCodes.SUCCESSION_INVALID:
      return 'successionType';
    case ErrorCodes.HISTORY_URL_INVALID:
      return 'historyUrl';
    case ErrorCodes.ANTHEM_URL_INVALID:
      return 'anthemUrl';
    case ErrorCodes.PROVINCE_TAKEN:
    case ErrorCodes.PROVINCE_NOT_FOUND:
    case ErrorCodes.PROVINCE_COUNT_OUT_OF_RANGE:
    // Emitted by the 01_map registration checks (land-only, connectivity).
    case 'PROVINCE_NOT_LAND':
    case 'STARTING_GROUP_NOT_CONNECTED':
      return 'provinces';
    case ErrorCodes.CAPITAL_NAME_INVALID:
      return 'capitalName';
    case ErrorCodes.CAPITAL_NOT_IN_PROVINCES:
      return 'capitalProvinceId';
    default:
      return null;
  }
}

/**
 * The required fields still missing (Spec Part 5: name, short name,
 * color, leader name, gender, leader title, succession type, history
 * link, exactly rules.max_provinces provinces, capital name). With no
 * rules loaded the province check degrades to "at least one" and the
 * name check to "non-empty", matching the pre-rules fallback gating.
 */
export function missingRequired(
  form: RegistrationForm,
  rules: NationRulesDTO | null,
): NationField[] {
  const missing: NationField[] = [];
  const empty = (value: string) => value.trim() === '';
  if (form.name.trim().length < (rules?.name_min_length ?? 1)) {
    missing.push('name');
  }
  if (empty(form.shortName)) {
    missing.push('shortName');
  }
  if (empty(form.color)) {
    missing.push('color');
  }
  if (empty(form.leaderName)) {
    missing.push('leaderName');
  }
  if (empty(form.gender)) {
    missing.push('gender');
  }
  if (empty(form.leaderTitle)) {
    missing.push('leaderTitle');
  }
  if (empty(form.successionType)) {
    missing.push('successionType');
  }
  if (empty(form.historyUrl)) {
    missing.push('historyUrl');
  }
  if (
    rules === null
      ? form.provinces.length < 1
      : form.provinces.length !== rules.max_provinces
  ) {
    missing.push('provinces');
  }
  if (empty(form.capitalName)) {
    missing.push('capitalName');
  }
  return missing;
}

/**
 * Builds the POST /nations body: texts are trimmed, empty optional texts
 * become null (INV-12 stores them as NULL), `capital_province_id` stays
 * null unless the player marked a capital.
 */
export function toCreateRequest(form: RegistrationForm): NationCreateRequest {
  const optionalText = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed === '' ? null : trimmed;
  };
  return {
    name: form.name.trim(),
    short_name: form.shortName.trim(),
    color_hex: form.color,
    motto: optionalText(form.motto),
    description: optionalText(form.description),
    flag_id: form.flagId,
    province_ids: form.provinces.map((chip) => chip.value),
    capital_province_id: form.capitalProvinceId,
    capital_name: form.capitalName.trim(),
    leader_name: form.leaderName.trim(),
    gender: form.gender,
    leader_title: form.leaderTitle.trim(),
    leader_bio: optionalText(form.leaderBio),
    portrait_id: form.portraitId,
    succession_type: form.successionType,
    history_url: form.historyUrl.trim(),
    anthem_url: optionalText(form.anthemUrl),
  };
}
