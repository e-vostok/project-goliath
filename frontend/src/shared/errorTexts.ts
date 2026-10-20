/**
 * errorTexts.ts — `errorText` is the ONE function the interface uses to
 * turn a failure into player-facing text (UI Spec 7, version 0.9.0
 * unit 9). The English `detail` is never shown; the single exception is
 * the `SERVER_RU` marker — codes whose server detail is already Russian
 * by contract and carries the concrete reason (Spec 04_orders 5.3).
 *
 * Order of resolution:
 *   not an ApiError (transport failure, abort) → the shared network
 *   phrase from ErrorState; a nation field code → `nationErrorTexts.ts`
 *   (its limits come from GET /nations/rules via `ctx.rules`); a code
 *   in the table → its text; a 5xx with no entry → the server phrase;
 *   anything else → the «Код ошибки» fallback.
 */

import { ApiError } from './api-client';
import type { NationRulesDTO } from './types';
import { NETWORK_ERROR_TEXT } from './ui/ErrorState';
import { nationErrorText } from '../modules/00_core/components/nationErrorTexts';
import {
  ERRORS_RU,
  fallbackErrorRu,
  SERVER_ERROR_RU,
  SERVER_RU,
} from './texts/errors.ru';

// The one place a language is chosen — a second language file later
// means a second constant here, nothing else.
const messages = ERRORS_RU;

export function errorText(
  error: unknown,
  ctx?: { rules?: NationRulesDTO | null },
): string {
  if (!(error instanceof ApiError)) {
    return NETWORK_ERROR_TEXT;
  }
  const nationText = nationErrorText(error.code, ctx?.rules ?? null);
  if (nationText !== null) {
    return nationText;
  }
  const entry = messages[error.code];
  if (entry === SERVER_RU) {
    // The detail is Russian by contract — it carries the reason.
    return error.message;
  }
  if (typeof entry === 'string') {
    return entry;
  }
  if (error.status >= 500) {
    return SERVER_ERROR_RU;
  }
  return fallbackErrorRu(error.code);
}
