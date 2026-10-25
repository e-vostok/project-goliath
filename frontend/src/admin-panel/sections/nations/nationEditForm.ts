/**
 * nationEdit.ts — the pure form model of the «Правка государства»
 * page (0.11.0 unit 8b, mockup screen 03b). The panel's own diff
 * helper: it builds a PATCH /admin/nations/{id} body that carries
 * only the fields whose value differs from the nation's — the
 * Mini App's `toUpdateRequest` is deliberately NOT imported (the
 * panel owns its copy, per the unit's scope).
 *
 * Semantics mirror the server's PATCH: an absent key means "do not
 * change", '' clears an optional text to NULL, and `capital_name`
 * is emitted only for a nation that has a capital province (the
 * server refuses the field for pre-0.8.0 nations, INV-14).
 */

import type {
  AdminNationDetailDTO,
  AdminNationUpdateRequest,
} from '../../../shared/types';
import {
  mapErrorCodeToField,
  normalizeColorHex,
} from '../../../modules/00_core/components/registrationForm';

/** The twelve editable fields, as strings (null becomes ''). */
export interface NationEditForm {
  name: string;
  shortName: string;
  color: string;
  motto: string;
  description: string;
  leaderName: string;
  leaderTitle: string;
  gender: string;
  successionType: string;
  leaderBio: string;
  historyUrl: string;
  capitalName: string;
}

/** Seeds the form from GET /admin/nations/{id}. */
export function formFromNation(nation: AdminNationDetailDTO): NationEditForm {
  return {
    name: nation.name,
    shortName: nation.short_name,
    color: nation.color_hex,
    motto: nation.motto ?? '',
    description: nation.description ?? '',
    leaderName: nation.leader_name ?? '',
    leaderTitle: nation.leader_title ?? '',
    gender: nation.gender ?? '',
    successionType: nation.succession_type ?? '',
    leaderBio: nation.leader_bio ?? '',
    historyUrl: nation.history_url ?? '',
    capitalName: nation.capital_name ?? '',
  };
}

/** Field keys that can hold a server refusal on this page. */
export type EditFieldKey = keyof NationEditForm;

/**
 * The PATCH body: only changed fields. An optional text cleared to
 * '' is sent as '' (the server stores NULL); `capital_name` goes
 * only when the nation owns a capital province.
 */
export function toAdminUpdateRequest(
  form: NationEditForm,
  nation: AdminNationDetailDTO,
): AdminNationUpdateRequest {
  const request: AdminNationUpdateRequest = {};
  const diffText = (edited: string, stored: string | null) => {
    const value = edited.trim();
    return value === (stored ?? '') ? undefined : value;
  };
  const put = <K extends keyof AdminNationUpdateRequest>(
    key: K,
    value: string | undefined,
  ) => {
    if (value !== undefined) {
      request[key] = value;
    }
  };

  put('name', diffText(form.name, nation.name));
  put('short_name', diffText(form.shortName, nation.short_name));
  const color = normalizeColorHex(form.color);
  if (color !== nation.color_hex.toUpperCase()) {
    request.color_hex = color;
  }
  put('motto', diffText(form.motto, nation.motto));
  put('description', diffText(form.description, nation.description));
  put('leader_name', diffText(form.leaderName, nation.leader_name));
  put('leader_title', diffText(form.leaderTitle, nation.leader_title));
  if (form.gender !== (nation.gender ?? '')) {
    request.gender = form.gender;
  }
  if (form.successionType !== (nation.succession_type ?? '')) {
    request.succession_type = form.successionType;
  }
  put('leader_bio', diffText(form.leaderBio, nation.leader_bio));
  put('history_url', diffText(form.historyUrl, nation.history_url));
  if (nation.capital_province_id !== null) {
    put('capital_name', diffText(form.capitalName, nation.capital_name));
  }
  return request;
}

/**
 * Turns a server `ErrorResponse.code` into the edit field that shows
 * it inline — the player's wizard mapping, with capital codes landing
 * on the «Столица» field (there are no province chips on this page).
 */
export function editFieldForError(code: string): EditFieldKey | null {
  const mapped = mapErrorCodeToField(code);
  switch (mapped) {
    case 'capitalProvinceId':
    case 'capitalName':
      return 'capitalName';
    case null:
      return null;
    default:
      // Every other NationField key exists on this page except the
      // create-only ones (flag/portrait/provinces) — guard them out.
      if (
        mapped === 'flagId' ||
        mapped === 'portraitId' ||
        mapped === 'provinces' ||
        mapped === 'capitalNameEdited'
      ) {
        return null;
      }
      return mapped as EditFieldKey;
  }
}
