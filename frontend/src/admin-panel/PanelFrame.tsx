/**
 * PanelFrame — the admin panel shell (0.11.0 unit 5a), approved
 * mockup docs/06_DESIGN/0.11.0 screen 02.
 *
 * Top bar: panel brand + «Пульт · панель администратора», the session
 * countdown «Сеанс: ещё N мин» (refreshed every 30 s), the turn badge
 * fed by GET /game-clock, the theme toggle, «Выйти». Left menu: the
 * seven registered sections as `#/<slug>` hash links. The main area
 * renders the active section's component.
 *
 * The frame ends the visible session on two triggers: the session
 * clock runs out, or an API call answers 401 — both surface the
 * «Сеанс закончился» gate card. «Выйти» forgets the token and shows
 * «Вы вышли из панели».
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
} from 'react';

import { api, ApiError } from '../shared/api-client';
import type { GameClockDTO } from '../shared/types';
import { ThemeToggle } from '../shared/ui/theme';
import {
  RADII,
  SIZES,
  TEXT_STYLES,
  tokenVar,
} from '../shared/ui/tokens';
import { TurnBadge } from '../shared/ui/TurnBadge';
import { PanelBrand } from './PanelBrand';
import { PanelIcon } from './panelIcons';
import type { AdminSession } from './session';
import {
  DEFAULT_SECTION_SLUG,
  PANEL_SECTIONS,
  sectionBySlug,
  sectionSlugFromHash,
} from './sections';

/** «Сеанс: ещё N мин» refresh cadence. */
const SESSION_LABEL_TICK_MS = 30_000;

/** What sections (units 6–11) use for every admin API call. */
export interface AdminSessionContextValue {
  token: string;
  expiresAtMs: number;
  /** A 401 from any admin endpoint ends the visible session. */
  reportUnauthorized: () => void;
}

const AdminSessionContext = createContext<AdminSessionContextValue | null>(
  null,
);

export function useAdminSession(): AdminSessionContextValue {
  const value = useContext(AdminSessionContext);
  if (value === null) {
    throw new Error('useAdminSession must be used inside PanelFrame');
  }
  return value;
}

/** Current `#/<slug>` — normalized against the registry. */
function useSectionSlug(): string {
  const [slug, setSlug] = useState<string>(
    () => sectionSlugFromHash(window.location.hash) ?? DEFAULT_SECTION_SLUG,
  );
  useEffect(() => {
    const onHashChange = () =>
      setSlug(sectionSlugFromHash(window.location.hash) ?? DEFAULT_SECTION_SLUG);
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  return slug;
}

export function PanelFrame({
  session,
  onLogout,
  onSessionEnd,
}: {
  session: AdminSession;
  /** Forget the token and show the «Вы вышли из панели» card. */
  onLogout: () => void;
  /** Session expired or a 401 — show «Сеанс закончился». */
  onSessionEnd: () => void;
}) {
  const activeSlug = useSectionSlug();
  const active = sectionBySlug(activeSlug);
  const ActiveSection = active.component;

  // Canonicalize the address once inside the frame: an empty or
  // non-section fragment becomes the default `#/turn`.
  useEffect(() => {
    const hash = window.location.hash;
    if (sectionSlugFromHash(hash) === null) {
      try {
        window.history.replaceState(null, '', `#/${DEFAULT_SECTION_SLUG}`);
      } catch {
        // Locked-down history — routing still works internally.
      }
    }
  }, []);

  const [clock, setClock] = useState<GameClockDTO | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api
      .getGameClock(session.token, controller.signal)
      .then(setClock)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          onSessionEnd();
        }
      });
    return () => controller.abort();
  }, [session.token, onSessionEnd]);

  // The countdown label: «Сеанс: ещё N мин», refreshed every 30 s.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(
      () => setNowMs(Date.now()),
      SESSION_LABEL_TICK_MS,
    );
    return () => clearInterval(id);
  }, []);

  // The session ends exactly when its time runs out.
  useEffect(() => {
    const delay = session.expiresAtMs - Date.now();
    if (delay <= 0) {
      onSessionEnd();
      return;
    }
    const id = setTimeout(onSessionEnd, delay);
    return () => clearTimeout(id);
  }, [session.expiresAtMs, onSessionEnd]);

  const minutesLeft = Math.max(
    0,
    Math.ceil((session.expiresAtMs - nowMs) / 60_000),
  );

  return (
    <AdminSessionContext.Provider
      value={{
        token: session.token,
        expiresAtMs: session.expiresAtMs,
        reportUnauthorized: onSessionEnd,
      }}
    >
      <header
        style={{
          height: SIZES['topbar-h'],
          boxSizing: 'border-box',
          background: tokenVar('surface'),
          borderBottom: `1px solid ${tokenVar('line')}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          gap: 16,
          flexShrink: 0,
        }}
      >
        <PanelBrand />
        <span
          aria-hidden="true"
          style={{ width: 1, height: 24, background: tokenVar('line') }}
        />
        <span
          style={{
            ...TEXT_STYLES['label'],
            color: tokenVar('signal-ink'),
          }}
        >
          Пульт · панель администратора
        </span>
        <span style={{ flexGrow: 1, minWidth: 0 }} />
        <span
          data-testid="panel-session-left"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
            whiteSpace: 'nowrap',
          }}
        >
          Сеанс: ещё {minutesLeft} мин
        </span>
        {clock !== null && (
          <TurnBadge>
            ХОД {clock.current_turn} · {clock.game_date_text.toUpperCase()}
          </TurnBadge>
        )}
        <ThemeToggle />
        <button
          type="button"
          onClick={onLogout}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: SIZES['button-h-small'],
            padding: '0 12px',
            border: 'none',
            borderRadius: RADII['radius-md'],
            background: tokenVar('surface-inset'),
            color: tokenVar('ink'),
            cursor: 'pointer',
            whiteSpace: 'nowrap',
            ...TEXT_STYLES['body'],
          }}
        >
          Выйти
        </button>
      </header>
      <div style={{ display: 'flex', alignItems: 'stretch', flexGrow: 1 }}>
        <nav
          aria-label="Разделы панели"
          style={{
            width: 232,
            flexShrink: 0,
            background: tokenVar('surface'),
            borderRight: `1px solid ${tokenVar('line')}`,
            padding: '16px 12px',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          <span
            style={{
              ...TEXT_STYLES['label'],
              color: tokenVar('ink-muted'),
              margin: '12px 12px 4px',
            }}
          >
            Разделы
          </span>
          {PANEL_SECTIONS.map((section) => {
            const selected = section.slug === active.slug;
            return (
              <a
                key={section.slug}
                href={`#/${section.slug}`}
                aria-current={selected ? 'page' : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  height: 40,
                  padding: '0 12px',
                  borderRadius: RADII['radius-md'],
                  background: selected
                    ? tokenVar('surface-inset')
                    : 'transparent',
                  color: tokenVar(selected ? 'ink' : 'ink-muted'),
                  textDecoration: 'none',
                  ...TEXT_STYLES['body'],
                }}
              >
                <PanelIcon name={section.icon} accent={selected} />
                {section.title}
              </a>
            );
          })}
          <span style={{ flexGrow: 1 }} />
          <span
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
              padding: '0 12px',
            }}
          >
            Каждое действие пишется в журнал.
          </span>
        </nav>
        <main
          style={{
            flexGrow: 1,
            minWidth: 0,
            padding: 24,
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
          }}
        >
          <ActiveSection />
        </main>
      </div>
    </AdminSessionContext.Provider>
  );
}
