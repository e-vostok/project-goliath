/**
 * errorText — the ONE function turning a failure into player-facing
 * Russian (UI Spec 7, version 0.9.0 unit 9).
 *
 * The code list is read straight out of `backend/src/main.py`
 * (`_ERROR_CODE_STATUS`), so a new server code without a Russian text
 * fails this test the day it ships — before it reaches a screen. The
 * English `detail` is never shown; the only pass-through is the
 * `SERVER_RU` marker (order field codes, whose server texts are
 * Russian by contract — Spec 04_orders 5.3).
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiError } from '../api-client';
import { errorText } from '../errorTexts';
import { ERRORS_RU, SERVER_RU } from '../texts/errors.ru';
import { NETWORK_ERROR_TEXT } from '../ui/ErrorState';

const CYRILLIC = /[А-Яа-яЁё]/;
const ENGLISH_DETAIL = 'Something broke in English';

// The path is relative to this file: shared/__tests__ → repo root.
const MAIN_PY = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../backend/src/main.py',
);

/** The `_ERROR_CODE_STATUS` keys of backend/src/main.py. */
const serverCodes = (() => {
  const source = readFileSync(MAIN_PY, 'utf8');
  const block = source.match(/_ERROR_CODE_STATUS\s*=\s*\{([\s\S]*?)\}/);
  if (block === null) {
    throw new Error('_ERROR_CODE_STATUS not found in backend/src/main.py');
  }
  return [...block[1].matchAll(/"([A-Z_]+)"\s*:/g)].map((m) => m[1]);
})();

describe('errorText — one Russian text per server code', () => {
  it('every _ERROR_CODE_STATUS code resolves to Russian, never to the English detail', () => {
    expect(serverCodes.length).toBeGreaterThan(0);
    for (const code of serverCodes) {
      const text = errorText(new ApiError(500, code, ENGLISH_DETAIL));
      if (ERRORS_RU[code] === SERVER_RU) {
        // The detail is Russian by contract — it is returned verbatim.
        expect(text).toBe(ENGLISH_DETAIL);
      } else {
        expect(text).toMatch(CYRILLIC);
        expect(text).not.toBe(ENGLISH_DETAIL);
      }
    }
  });

  it('the three SERVER_RU order codes pass the Russian detail through', () => {
    const detail = 'Краткая суть приказа не подходит: слишком короткая';
    for (const code of [
      'ORDER_TITLE_INVALID',
      'ORDER_SUMMARY_INVALID',
      'ORDER_URL_INVALID',
    ]) {
      expect(ERRORS_RU[code]).toBe(SERVER_RU);
      expect(errorText(new ApiError(422, code, detail))).toBe(detail);
    }
  });

  it('a code missing from the table gets the «Код ошибки» fallback', () => {
    expect(
      errorText(new ApiError(400, 'SOME_FUTURE_CODE', ENGLISH_DETAIL)),
    ).toBe('Не удалось выполнить действие. Код ошибки: SOME_FUTURE_CODE.');
  });

  it('a 5xx without a table entry gets the server phrase', () => {
    expect(errorText(new ApiError(500, 'INTERNAL', ENGLISH_DETAIL))).toBe(
      'Ошибка сервера — попробуйте ещё раз позже.',
    );
  });

  it('a non-ApiError (network failure, abort) gets the shared network phrase', () => {
    expect(errorText(new Error('fetch failed'))).toBe(NETWORK_ERROR_TEXT);
    expect(errorText(new DOMException('Aborted', 'AbortError'))).toBe(
      NETWORK_ERROR_TEXT,
    );
  });
});
