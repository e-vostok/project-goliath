/**
 * The pure form model of the registration window (Spec 1.3 Part 5,
 * UI Spec 9.6 — version 0.9.0 unit 8c).
 *
 * One `RegistrationForm` object carries every NationCreateRequest field
 * across the four tabs («Основные данные и символика», «Глава
 * государства», «История», «Территории»), so switching tabs never loses
 * or sends anything. `fieldToTab` places each field on its tab,
 * `mapErrorCodeToField` turns a server `ErrorResponse.code` into the
 * field that shows it inline, `missingRequired` lists the still-empty
 * mandatory fields (it gates the single submit button and feeds the
 * tab dots), and `toCreateRequest` builds the POST /nations body.
 * The anthem field is gone from the interface — `anthem_url` is never
 * sent (the server column stays unused).
 *
 * No React here — the container and the tests import the same logic.
 */

import { ErrorCodes } from '../../../shared/types';
import type {
  NationCreateRequest,
  NationDTO,
  NationRulesDTO,
  NationUpdateRequest,
} from '../../../shared/types';

export type RegistrationTab = 1 | 2 | 3 | 4;

/** A picked province shown as a named chip; order = selection order. */
export interface ChipOption {
  value: number;
  label: string;
}

/**
 * All create fields of Spec 1.3. Optional text fields hold '' (sent as
 * null), and `capitalProvinceId` is null unless
 * the player explicitly marked a capital — the server then defaults it
 * to the first selected province (INV-14). `capitalNameEdited` is the
 * «player typed the capital name by hand» flag: until it is set the
 * name field follows the effective capital's province name; after a
 * manual edit it is never auto-overwritten again (Spec Part 5, tab 4).
 */
export interface RegistrationForm {
  name: string;
  shortName: string;
  color: string;
  motto: string;
  description: string;
  leaderName: string;
  gender: string;
  leaderTitle: string;
  leaderBio: string;
  successionType: string;
  historyUrl: string;
  provinces: ChipOption[];
  capitalProvinceId: number | null;
  capitalName: string;
  /** Once true, the capital name input stops auto-following the mark. */
  capitalNameEdited: boolean;
}

/** Field keys shared by the wizard and the edit form error mapping. */
export type NationField = keyof RegistrationForm;

/** Session-draft key; v1 drafts under 'nation-create' are ignored. */
export const REGISTRATION_DRAFT_KEY = 'nation-create-v2';

/**
 * The server-side DTO format for `color_hex` (Spec Part 5): `#RRGGBB`
 * upper case. The HEX field tolerates a missing '#' and lower case —
 * `normalizeColorHex` canonicalizes for the validity check and the
 * request body, so the stored string is always upper-case on submit.
 */
export const HEX_COLOR_PATTERN = /^#[0-9A-F]{6}$/;

export function normalizeColorHex(raw: string): string {
  const trimmed = raw.trim().toUpperCase();
  return trimmed.startsWith('#') ? trimmed : `#${trimmed}`;
}

export function isValidColorHex(raw: string): boolean {
  return HEX_COLOR_PATTERN.test(normalizeColorHex(raw));
}

export function emptyRegistrationForm(): RegistrationForm {
  return {
    name: '',
    shortName: '',
    color: '',
    motto: '',
    description: '',
    leaderName: '',
    gender: '',
    leaderTitle: '',
    leaderBio: '',
    successionType: '',
    historyUrl: '',
    provinces: [],
    capitalProvinceId: null,
    capitalName: '',
    capitalNameEdited: false,
  };
}

/**
 * true when nothing player-authored was entered yet — used to drop the
 * session draft. `color` counts: its initial value is '' and any pick
 * is user content.
 */
export function registrationFormIsEmpty(form: RegistrationForm): boolean {
  return (
    form.name === '' &&
    form.shortName === '' &&
    form.color === '' &&
    form.motto === '' &&
    form.description === '' &&
    form.leaderName === '' &&
    form.gender === '' &&
    form.leaderTitle === '' &&
    form.leaderBio === '' &&
    form.successionType === '' &&
    form.historyUrl === '' &&
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
  form.capitalNameEdited = form.capitalNameEdited === true;
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
      return 1;
    case 'leaderName':
    case 'gender':
    case 'leaderTitle':
    case 'leaderBio':
    case 'successionType':
      return 2;
    case 'historyUrl':
      return 3;
    case 'provinces':
    case 'capitalProvinceId':
    case 'capitalName':
    case 'capitalNameEdited':
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
    case ErrorCodes.LEADER_NAME_INVALID:
      return 'leaderName';
    case ErrorCodes.GENDER_INVALID:
      return 'gender';
    case ErrorCodes.LEADER_TITLE_INVALID:
      return 'leaderTitle';
    case ErrorCodes.LEADER_BIO_INVALID:
      return 'leaderBio';
    case ErrorCodes.SUCCESSION_INVALID:
      return 'successionType';
    case ErrorCodes.HISTORY_URL_INVALID:
      return 'historyUrl';
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
 * a valid #RRGGBB color, leader name, gender, leader title, succession
 * type, history link, exactly rules.max_provinces provinces, capital
 * name). The color counts as filled only when it normalizes to the DTO
 * format — a half-typed HEX keeps the submit gated. With no rules
 * loaded the province check degrades to "at least one" and the name
 * check to "non-empty", matching the pre-rules fallback gating.
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
  if (!isValidColorHex(form.color)) {
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
 * null unless the player marked a capital. `anthem_url` is deliberately
 * absent — the interface dropped the anthem field (0.9.0, unit 8c) while
 * `NationCreateRequest` keeps the key because shared types mirror the
 * server DTO field-for-field.
 */
export function toCreateRequest(form: RegistrationForm): NationCreateRequest {
  const optionalText = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed === '' ? null : trimmed;
  };
  return {
    name: form.name.trim(),
    short_name: form.shortName.trim(),
    color_hex: normalizeColorHex(form.color),
    motto: optionalText(form.motto),
    description: optionalText(form.description),
    province_ids: form.provinces.map((chip) => chip.value),
    capital_province_id: form.capitalProvinceId,
    capital_name: form.capitalName.trim(),
    leader_name: form.leaderName.trim(),
    gender: form.gender,
    leader_title: form.leaderTitle.trim(),
    leader_bio: optionalText(form.leaderBio),
    succession_type: form.successionType,
    history_url: form.historyUrl.trim(),
  } as NationCreateRequest;
}

/**
 * Seeds the edit form (PanelNationHome) from an existing nation: the
 * same RegistrationForm model, every missing value as the field's empty
 * state. Provinces are display-only chips labelled «Провинция» — the
 * server never returns province names and numbers are never shown;
 * `useProvinceNames` resolves the real names on screen (UI Spec 9.6).
 * `capitalNameEdited` starts true: the stored capital name is the
 * player's own and must never be auto-overwritten.
 */
export function registrationFormFromNation(
  nation: NationDTO,
): RegistrationForm {
  return {
    name: nation.name,
    shortName: nation.short_name,
    color: nation.color_hex,
    motto: nation.motto ?? '',
    description: nation.description ?? '',
    leaderName: nation.leader_name ?? '',
    gender: nation.gender ?? '',
    leaderTitle: nation.leader_title ?? '',
    leaderBio: nation.leader_bio ?? '',
    successionType: nation.succession_type ?? '',
    historyUrl: nation.history_url ?? '',
    provinces: nation.province_ids.map((id) => ({
      value: id,
      label: 'Провинция',
    })),
    capitalProvinceId: nation.capital_province_id,
    capitalName: nation.capital_name ?? '',
    capitalNameEdited: true,
  };
}

/**
 * Builds the PATCH /nations/me body (Spec Part 3, INV-8): only fields
 * whose normalized value differs from the nation's. An optional field
 * cleared by the player goes as '' (the server stores NULL). An
 * emptied value equal to the nation's own (a NULL mandatory field the
 * player typed into and cleared) is omitted — nothing to change.
 * `capital_name` is emitted only for a nation that has a capital: the
 * server refuses the field for pre-0.8.0 nations (INV-14).
 */
export function toUpdateRequest(
  form: RegistrationForm,
  nation: NationDTO,
): NationUpdateRequest {
  const request: NationUpdateRequest = {};
  const diffText = (
    edited: string,
    stored: string | null,
  ): string | undefined => {
    const value = edited.trim();
    return value === (stored ?? '') ? undefined : value;
  };

  const name = diffText(form.name, nation.name);
  if (name !== undefined) {
    request.name = name;
  }
  const shortName = diffText(form.shortName, nation.short_name);
  if (shortName !== undefined) {
    request.short_name = shortName;
  }
  const color = normalizeColorHex(form.color);
  if (color !== nation.color_hex.toUpperCase()) {
    request.color_hex = color;
  }
  const motto = diffText(form.motto, nation.motto);
  if (motto !== undefined) {
    request.motto = motto;
  }
  const description = diffText(form.description, nation.description);
  if (description !== undefined) {
    request.description = description;
  }
  const leaderName = diffText(form.leaderName, nation.leader_name);
  if (leaderName !== undefined) {
    request.leader_name = leaderName;
  }
  if (form.gender !== (nation.gender ?? '')) {
    request.gender = form.gender;
  }
  const leaderTitle = diffText(form.leaderTitle, nation.leader_title);
  if (leaderTitle !== undefined) {
    request.leader_title = leaderTitle;
  }
  const leaderBio = diffText(form.leaderBio, nation.leader_bio);
  if (leaderBio !== undefined) {
    request.leader_bio = leaderBio;
  }
  if (form.successionType !== (nation.succession_type ?? '')) {
    request.succession_type = form.successionType;
  }
  const historyUrl = diffText(form.historyUrl, nation.history_url);
  if (historyUrl !== undefined) {
    request.history_url = historyUrl;
  }
  if (nation.capital_province_id !== null) {
    const capitalName = diffText(form.capitalName, nation.capital_name);
    if (capitalName !== undefined) {
      request.capital_name = capitalName;
    }
  }
  return request;
}
