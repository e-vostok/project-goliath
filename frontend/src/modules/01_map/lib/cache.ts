/**
 * ETag / conditional-request decisions for useMapManifest — pure.
 *
 * The manifest endpoint answers 304 when `If-None-Match` still matches.
 * A 304 is only usable while we hold a memory copy of the body; a 304
 * without one (should not happen, but must not lose the manifest) means
 * "refetch without the conditional header".
 */

export interface CachedBody<T> {
  etag: string | null;
  body: T;
}

export interface ConditionalAnswer<T> {
  status: number;
  etag: string | null;
  body: T | null;
}

export type ConditionalDecision<T> =
  | { action: 'use'; value: CachedBody<T> }
  | { action: 'refetch-unconditional' };

export function decideConditional<T>(
  answer: ConditionalAnswer<T>,
  cached: CachedBody<T> | null,
): ConditionalDecision<T> {
  if (answer.status === 304) {
    if (cached !== null) {
      return { action: 'use', value: cached };
    }
    return { action: 'refetch-unconditional' };
  }
  if (answer.body === null) {
    // A 200 without a body is a protocol violation — treat as refetchable.
    return { action: 'refetch-unconditional' };
  }
  return {
    action: 'use',
    value: { etag: answer.etag, body: answer.body },
  };
}
