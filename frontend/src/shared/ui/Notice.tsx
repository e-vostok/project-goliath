/**
 * Notice — the one shared «done» message (UI Spec 7, version 0.9.0
 * unit 9): a small bar at the TOP of the app window, under the top bar
 * (the bottom of a tall window is out of sight), with a check and the
 * text in `positive`; disappears after 4 s or on click.
 *
 * `NoticeHost` lives inside the app root container next to `PopupHost`
 * and portals the bar into the same container — `position: absolute`,
 * never `fixed`, so it follows the content top rather than the
 * viewport. `useNotice()` returns `notify(text)`; one message at a
 * time — a new one replaces the old and restarts the timer.
 */

import {
  createContext,
  type CSSProperties,
  type ReactNode,
  type RefObject,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

import { RADII, shadowVar, TEXT_STYLES, tokenVar } from './tokens';

/** How long the bar stays visible. */
export const NOTICE_TIMEOUT_MS = 4000;

interface NoticeState {
  seq: number;
  text: string;
}

type Notify = (text: string) => void;

const NoticeContext = createContext<Notify | null>(null);

/** The notify(text) sender — must sit under NoticeHost. */
export function useNotice(): Notify {
  const notify = useContext(NoticeContext);
  if (notify === null) {
    throw new Error('useNotice must be used inside NoticeHost');
  }
  return notify;
}

const noticeStyle: CSSProperties = {
  position: 'absolute',
  top: 56,
  left: '50%',
  transform: 'translateX(-50%)',
  maxWidth: 480,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '10px 16px',
  background: tokenVar('surface-raised'),
  boxShadow: shadowVar('shadow-popup'),
  borderRadius: RADII['radius-md'],
  color: tokenVar('positive'),
  cursor: 'pointer',
  // Above the popups' scrims (they carry no z-index): the notice must
  // be readable while a window stays open after a verdict.
  zIndex: 40,
};

const checkStyle: CSSProperties = {
  flexShrink: 0,
};

/** Small check — one-off glyph, not a block icon. */
function CheckIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
      style={checkStyle}
    >
      <path
        d="M3.5 9.5 7 13 14.5 5.5"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export interface NoticeHostProps {
  /** The app root container (position: relative) — same as PopupHost. */
  container: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}

export function NoticeHost({ container, children }: NoticeHostProps) {
  const [notice, setNotice] = useState<NoticeState | null>(null);

  const notify = useCallback((text: string) => {
    setNotice((prev) => ({ seq: (prev?.seq ?? 0) + 1, text }));
  }, []);

  // The timer restarts on every new notice — including an identical
  // text — and only a re-render with the same notice object keeps it.
  useEffect(() => {
    if (notice === null) {
      return;
    }
    const timer = setTimeout(() => setNotice(null), NOTICE_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const host = container.current;
  return (
    <NoticeContext.Provider value={useMemo(() => notify, [notify])}>
      {children}
      {host !== null &&
        notice !== null &&
        createPortal(
          <div
            data-testid="notice"
            role="status"
            style={noticeStyle}
            onClick={() => setNotice(null)}
          >
            <CheckIcon />
            <span style={TEXT_STYLES.body}>{notice.text}</span>
          </div>,
          host,
        )}
    </NoticeContext.Provider>
  );
}
