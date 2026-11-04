/**
 * AdminPanelButton — the «Пульт» entry in the top bar (0.11.0 unit
 * 5b; mockup docs/06_DESIGN/0.11.0, screen 01): a small, barely
 * visible shield left of the theme switch, rendered ONLY for
 * allowlisted admins — `useAdminProbe` answers false for 403, 401,
 * network errors and while loading, so the element never exists in
 * the page for anyone else. This is cosmetic gating only: the
 * server checks rights on every request.
 *
 * The control is a real link (research doc variant А+В): hovering
 * or focusing asks POST /admin/panel-link for a one-time token and
 * puts the ready address `/admin.html#t=<token>` into `href`, so a
 * click is a plain browser navigation no popup blocker can stop. A
 * click that arrives with no fresh token is held (preventDefault),
 * fetches one and calls `window.open` — the live probe showed the
 * browser allows that too.
 *
 * The token rides in the `#t=` fragment — never a query string —
 * so it stays out of the server log and Referer; it is never
 * logged and is dropped from `href` the moment its lifetime ends.
 *
 * The lit look (0.13.0 unit 9b; mockups docs/06_DESIGN/0.13.0
 * screens 23/23b): while the home tab is active and the page is
 * visible, `useAdminAttention` polls GET /admin/attention —
 * `total > 0` tints the square and adds the signal dot, and the
 * «Требует внимания» tooltip lists the counter items. A zero or a
 * failure keeps today's quiet look. The link/token logic is
 * unchanged by that.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';

import { api } from '../shared/api-client';
import type { AdminAttentionDTO } from '../shared/types';
import {
  FONTS,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
  Tooltip,
  useNotice,
} from '../shared/ui';
import { useSession } from '../modules/00_core/hooks/useAuth';
import { useAdminAttention } from './useAdminAttention';
import { useAdminProbe } from './useAdminProbe';

const TITLE = 'Панель администратора';
const OPEN_ERROR = 'Не удалось открыть панель. Попробуйте ещё раз.';
/** Re-issue the link this early before the server's expiry. */
const TOKEN_SAFETY_MARGIN_MS = 5000;
const EMPTY_HREF = '#';

interface IssuedLink {
  href: string;
  /** `Date.now()` timestamp after which the token counts as stale. */
  freshUntil: number;
}

/** The lit shield's «Требует внимания» tip (mockup 23). */
function AttentionTip({ attention }: { attention: AdminAttentionDTO }) {
  return (
    <div style={{ minWidth: 220 }}>
      <div style={{ ...TEXT_STYLES['heading'], fontSize: 14 }}>
        Требует внимания
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          marginTop: SPACING['space-2'] - 2,
        }}
      >
        {attention.items.map((item) => (
          <div
            key={item.key}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}
          >
            <span>{item.label}</span>
            <span style={{ fontFamily: FONTS.mono }}>{item.count}</span>
          </div>
        ))}
      </div>
      <div
        style={{
          ...TEXT_STYLES['caption'],
          color: tokenVar('ink-muted'),
          marginTop: SPACING['space-2'] - 2,
        }}
      >
        Нажмите, чтобы открыть панель администратора.
      </div>
    </div>
  );
}

export function AdminPanelButton({
  active = true,
}: {
  /** False outside the home tab — the counter sleeps (Spec §10). */
  active?: boolean;
}) {
  const isAdmin = useAdminProbe();
  const attention = useAdminAttention(isAdmin && active);
  const lit = attention !== null && attention.total > 0;
  const { token } = useSession();
  const notify = useNotice();

  const [href, setHref] = useState(EMPTY_HREF);
  const [focused, setFocused] = useState(false);
  const linkRef = useRef<IssuedLink | null>(null);
  const flightRef = useRef<Promise<string | null> | null>(null);

  /**
   * Resolve a usable panel URL: the cached one while it is fresh
   * (younger than `expires_in_seconds` minus the safety margin),
   * otherwise a newly issued one. Concurrent callers share a single
   * in-flight request — pointerenter and focus arriving together
   * still issue exactly one token.
   */
  const issueLink = useCallback(async (): Promise<string | null> => {
    const cached = linkRef.current;
    if (cached !== null && Date.now() < cached.freshUntil) {
      return cached.href;
    }
    if (flightRef.current !== null) {
      return flightRef.current;
    }
    const flight = (async () => {
      try {
        const answer = await api.adminPanelLink(token);
        const url = `${window.location.origin}/admin.html#t=${answer.token}`;
        linkRef.current = {
          href: url,
          freshUntil:
            Date.now() +
            answer.expires_in_seconds * 1000 -
            TOKEN_SAFETY_MARGIN_MS,
        };
        setHref(url);
        return url;
      } catch {
        return null;
      } finally {
        flightRef.current = null;
      }
    })();
    flightRef.current = flight;
    return flight;
  }, [token]);

  // The one-time token is never kept past its lifetime: once the
  // freshness window ends, `href` falls back to «#» and the next
  // interaction issues a new link.
  useEffect(() => {
    const link = linkRef.current;
    if (link === null) {
      return;
    }
    const timer = window.setTimeout(
      () => {
        if (linkRef.current === link) {
          linkRef.current = null;
          setHref(EMPTY_HREF);
        }
      },
      Math.max(link.freshUntil - Date.now(), 0),
    );
    return () => window.clearTimeout(timer);
  }, [href]);

  /**
   * Forget the held link once the browser has taken it — the token
   * is one-time and the panel tab spends it on arrival, so it must
   * never be opened twice. Deferred by a task: the navigation still
   * has to read the armed `href` of this very click.
   */
  const dropLink = () => {
    window.setTimeout(() => {
      linkRef.current = null;
      setHref(EMPTY_HREF);
    }, 0);
  };

  const prefetch = () => {
    void issueLink();
  };

  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const cached = linkRef.current;
    if (cached !== null && Date.now() < cached.freshUntil) {
      // Ready link — a plain navigation, never blocked; the token
      // is spent by the arriving panel tab.
      dropLink();
      return;
    }
    event.preventDefault();
    void issueLink().then((url) => {
      if (url === null) {
        notify(OPEN_ERROR);
        return;
      }
      window.open(url, '_blank', 'noopener,noreferrer');
      dropLink();
    });
  };

  if (!isAdmin) {
    return null;
  }

  const link = (
    <a
      data-testid="admin-panel-button"
      data-attention={lit ? 'lit' : undefined}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={TITLE}
      aria-label={TITLE}
      onPointerEnter={prefetch}
      onFocus={() => {
        setFocused(true);
        prefetch();
      }}
      onBlur={() => setFocused(false)}
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        borderRadius: RADII['radius-md'],
        color: tokenVar(lit ? 'signal-ink' : 'ink-faint'),
        background: lit ? tokenVar('warning-bg') : 'transparent',
        opacity: lit ? 1 : 0.55,
        flexShrink: 0,
        position: 'relative',
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      <svg
        width={16}
        height={16}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        style={{ display: 'block' }}
      >
        <path d="M8 1.8l5 1.8v4.2c0 3-2.2 5-5 6.4-2.8-1.4-5-3.4-5-6.4V3.6z" />
        <path d="M5.8 8l1.7 1.7L10.5 6.4" />
      </svg>
      {lit && (
        <span
          data-testid="admin-attention-dot"
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 3,
            right: 3,
            width: 7,
            height: 7,
            borderRadius: RADII['radius-pill'],
            background: tokenVar('signal'),
            boxShadow: `0 0 0 2px ${tokenVar('surface')}`,
          }}
        />
      )}
    </a>
  );

  return lit && attention !== null ? (
    <Tooltip content={() => <AttentionTip attention={attention} />}>
      {link}
    </Tooltip>
  ) : (
    link
  );
}
