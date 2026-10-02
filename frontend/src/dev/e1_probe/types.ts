/**
 * Shared types for the E1 «big window» probe panel (temporary experiment).
 * Everything in dev/e1_probe is self-contained: removal is one `git rm`
 * of this directory plus the registration line in AdminBlock and the
 * branch line in main.tsx.
 */

import type { ErrorInfo } from './helpers';

/** Hash fragment that routes the app entry to the standalone child page. */
export const E1_PROBE_CHILD_HASH = '#e1-probe-child';

/**
 * One probe run appended to the report log.
 * `ok:false` + `error` means the probed call threw/rejected; `result` may
 * still be present when the probe collected data before/around the failure.
 */
export interface ProbeBlock {
  /** Probe id: 'A'…'F', 'COPY' for the clipboard-path record. */
  probe: string;
  /** Human-readable label (Russian), as shown on the button. */
  label: string;
  /** Client time, ISO 8601. */
  at: string;
  ok: boolean;
  result?: unknown;
  error?: ErrorInfo;
}
