/**
 * Entry branch for the E1 child tab.
 *
 * main.tsx calls `e1ChildEntry(window.location.hash)` before rendering the
 * normal app: for '#e1-probe-child' it returns the standalone child page,
 * so App (and its VKWebAppInit / auth / API traffic) never mounts.
 * Kept in a separate module so the branch is unit-testable — importing
 * main.tsx would run createRoot() as a side effect.
 */

import type { ReactElement } from 'react';

import { E1ProbeChildPage } from './E1ProbeChildPage';
import { E1_PROBE_CHILD_HASH } from './types';

export { E1_PROBE_CHILD_HASH };

export function isE1ProbeChildHash(hash: string): boolean {
  return hash === E1_PROBE_CHILD_HASH;
}

/** Child page element for the probe hash, null → render the normal app. */
export function e1ChildEntry(hash: string): ReactElement | null {
  return isE1ProbeChildHash(hash) ? <E1ProbeChildPage /> : null;
}
