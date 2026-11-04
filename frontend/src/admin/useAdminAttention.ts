/**
 * useAdminAttention — the «требует внимания» counter behind the lit
 * shield (0.13.0 unit 9b; Spec applications §7, §10; mockups
 * docs/06_DESIGN/0.13.0 screens 23/23b).
 *
 * While `active` — the probe said admin AND the home tab («Штаб» /
 * «Анкета») is open — it asks GET /admin/attention once on mount,
 * then every 60 s and on window focus. A poll fires only while the
 * page is visible (`document.visibilityState`); returning to a
 * visible page polls again through `visibilitychange`/focus, so a
 * hidden tab never burns requests.
 *
 * `total > 0` lights the shield; `0` or ANY failure resolves to the
 * quiet look with no error shown — the counter is a hint, never a
 * blocker (a stale/expired token simply keeps the shield dim until a
 * later poll succeeds). Deactivating clears the remembered answer,
 * so a stale count can't light the shield after the tab loses focus.
 */

import { useEffect, useState } from 'react';

import { api } from '../shared/api-client';
import type { AdminAttentionDTO } from '../shared/types';
import { useSession } from '../modules/00_core/hooks/useAuth';

/** The poll cadence of Spec applications §10 — once a minute. */
const ATTENTION_POLL_MS = 60_000;

export function useAdminAttention(active: boolean): AdminAttentionDTO | null {
  const { token } = useSession();
  const [attention, setAttention] = useState<AdminAttentionDTO | null>(null);

  useEffect(() => {
    if (!active) {
      setAttention(null);
      return;
    }
    let cancelled = false;
    const load = () => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      api
        .adminAttention(token)
        .then((answer) => {
          if (!cancelled) {
            setAttention(answer);
          }
        })
        .catch(() => {
          // Any failure — 401, 403, network — is the quiet look,
          // never an error surface (Spec §10).
          if (!cancelled) {
            setAttention(null);
          }
        });
    };
    load();
    const interval = window.setInterval(load, ATTENTION_POLL_MS);
    const onFocus = () => load();
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        load();
      }
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [active, token]);

  return active ? attention : null;
}
