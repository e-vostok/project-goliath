/**
 * AdminApp — the panel page's own root (0.11.0 unit 5a).
 *
 * Boot flow (the one-time-link entry, units 1+4):
 *  1. `#t=…` in the fragment is lifted out of the address bar at once
 *     (takeEntryToken) — the token never stays in the URL.
 *  2. POST /admin/session (no Bearer) exchanges it for a short Bearer
 *     session kept in sessionStorage (memory fallback if storage
 *     throws). A spent link is never retried.
 *  3. No fragment: a still-valid stored session is proven once via
 *     GET /admin/me; anything else shows «Ссылка устарела».
 *
 * Terminal states are the single-card gate screens of mockup 09:
 * «Ссылка устарела» (401 PANEL_LINK_INVALID), «Нет доступа» (403),
 * the network card, «Сеанс закончился» (expiry or a later 401) and
 * «Вы вышли из панели» («Выйти»). The token is never rendered or
 * logged.
 */

import { useEffect, useState } from 'react';

import { api, ApiError } from '../shared/api-client';
import { TEXT_STYLES } from '../shared/ui/tokens';
import { takeEntryToken } from './entryToken';
import type { GateCardKind } from './PanelGate';
import { PanelGate } from './PanelGate';
import { PanelFrame } from './PanelFrame';
import type { AdminSession } from './session';
import { clearSession, readSession, saveSession } from './session';

type PanelState =
  | { kind: 'boot' }
  | { kind: 'gate'; card: GateCardKind }
  | { kind: 'ready'; session: AdminSession };

export function AdminApp() {
  // Read once, on the very first render: the fragment is removed from
  // the address bar in the same step, before any request leaves.
  const [linkToken] = useState(() => takeEntryToken());
  const [state, setState] = useState<PanelState>({ kind: 'boot' });

  useEffect(() => {
    let cancelled = false;
    const settle = (next: PanelState) => {
      if (!cancelled) {
        setState(next);
      }
    };

    const boot = async () => {
      if (linkToken !== null) {
        try {
          const answer = await api.adminExchangeSession(linkToken);
          const session: AdminSession = {
            token: answer.access_token,
            expiresAtMs: Date.now() + answer.expires_in_seconds * 1000,
          };
          saveSession(session);
          settle({ kind: 'ready', session });
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            settle({ kind: 'gate', card: 'link-stale' });
          } else if (error instanceof ApiError && error.status === 403) {
            settle({ kind: 'gate', card: 'no-access' });
          } else {
            settle({ kind: 'gate', card: 'network' });
          }
        }
        return;
      }

      const stored = readSession();
      if (stored !== null && stored.expiresAtMs > Date.now()) {
        try {
          await api.adminMe(stored.token);
          settle({ kind: 'ready', session: stored });
        } catch {
          clearSession();
          settle({ kind: 'gate', card: 'link-stale' });
        }
      } else {
        if (stored !== null) {
          clearSession();
        }
        settle({ kind: 'gate', card: 'link-stale' });
      }
    };

    void boot();
    return () => {
      cancelled = true;
    };
  }, [linkToken]);

  const endToCard = (card: GateCardKind) => {
    clearSession();
    setState({ kind: 'gate', card });
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        ...TEXT_STYLES['body'],
      }}
    >
      {state.kind === 'ready' ? (
        <PanelFrame
          session={state.session}
          onLogout={() => endToCard('logged-out')}
          onSessionEnd={() => endToCard('session-ended')}
        />
      ) : (
        <PanelGate card={state.kind === 'gate' ? state.card : null} />
      )}
    </div>
  );
}
