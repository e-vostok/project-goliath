/**
 * ETag decisions (Spec Part 5): a 304 reuses the memory copy; a 304
 * without one triggers an unconditional refetch; a 200 stores the body
 * with its fresh ETag.
 */

import { decideConditional } from '../lib/cache';

const MANIFEST = { tag: 'manifest-body' };

describe('decideConditional', () => {
  it('304 + memory copy → reuse it', () => {
    const cached = { etag: '"e1"', body: MANIFEST };
    const decision = decideConditional(
      { status: 304, etag: '"e1"', body: null },
      cached,
    );
    expect(decision).toEqual({ action: 'use', value: cached });
  });

  it('304 without memory copy → refetch unconditionally', () => {
    const decision = decideConditional(
      { status: 304, etag: '"e1"', body: null },
      null,
    );
    expect(decision.action).toBe('refetch-unconditional');
  });

  it('200 → adopt the new body and etag', () => {
    const decision = decideConditional(
      { status: 200, etag: '"e2"', body: MANIFEST },
      { etag: '"e1"', body: { tag: 'old' } },
    );
    expect(decision).toEqual({
      action: 'use',
      value: { etag: '"e2"', body: MANIFEST },
    });
  });
});
