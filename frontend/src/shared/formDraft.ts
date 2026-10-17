/**
 * formDraft — the shared draft store for the app's input forms.
 *
 * A filled form keeps its field values for the browser session: the
 * in-memory map is the primary store and `sessionStorage` is the
 * mirrored copy (a full page reload inside the tab keeps the draft).
 * Every storage read and write sits inside try/catch — with storage
 * unavailable or broken the memory map alone keeps the form working.
 *
 * Contract: the draft is restored when the form is reopened; it is
 * deleted after a successful send and when the user presses the
 * explicit «Отмена» / «Сбросить» button; closing by click outside,
 * Esc or the cross keeps it. Drafts never hold passwords or tokens
 * and are keyed per form (per order number for verdicts).
 */

import { useCallback, useState } from 'react';

const STORAGE_PREFIX = 'form-draft:';

/** Session memory — the primary store (module state). */
const drafts = new Map<string, unknown>();

function storageRead(key: string): unknown {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_PREFIX + key);
    return raw === null ? undefined : (JSON.parse(raw) as unknown);
  } catch {
    return undefined;
  }
}

function storageWrite(key: string, value: unknown): void {
  try {
    window.sessionStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
  } catch {
    // No storage — the memory map still carries the draft.
  }
}

function storageRemove(key: string): void {
  try {
    window.sessionStorage.removeItem(STORAGE_PREFIX + key);
  } catch {
    // No storage — the memory map still carries the draft.
  }
}

/** Read the stored draft for `key` (null when absent). */
export function readFormDraft<T>(key: string): T | null {
  if (drafts.has(key)) {
    return drafts.get(key) as T;
  }
  const stored = storageRead(key);
  if (stored === undefined) {
    return null;
  }
  drafts.set(key, stored);
  return stored as T;
}

/** Write (or overwrite) the draft for `key`. */
export function writeFormDraft<T>(key: string, value: T): void {
  drafts.set(key, value);
  storageWrite(key, value);
}

/** Delete the draft for `key` — after a successful send or «Отмена». */
export function clearFormDraft(key: string): void {
  drafts.delete(key);
  storageRemove(key);
}

/** Drop every draft — test isolation hook. */
export function clearAllFormDrafts(): void {
  drafts.clear();
  try {
    const doomed: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key !== null && key.startsWith(STORAGE_PREFIX)) {
        doomed.push(key);
      }
    }
    doomed.forEach((key) => window.sessionStorage.removeItem(key));
  } catch {
    // No storage — nothing to remove.
  }
}

/**
 * useFormDraft(key) — the React face of the store. `draft` is the value
 * captured when the form mounts (its field states initialise from it);
 * `setDraft` writes through to memory + storage; `clearDraft` deletes.
 */
export function useFormDraft<T>(key: string): {
  draft: T | null;
  setDraft: (value: T) => void;
  clearDraft: () => void;
} {
  const [draft] = useState<T | null>(() => readFormDraft<T>(key));
  const setDraft = useCallback(
    (value: T) => writeFormDraft(key, value),
    [key],
  );
  const clearDraft = useCallback(() => clearFormDraft(key), [key]);
  return { draft, setDraft, clearDraft };
}
