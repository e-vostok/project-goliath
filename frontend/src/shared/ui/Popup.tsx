/**
 * Popup + PopupHost — the «Всплывающее окно» (UI Spec 3.3, unit 6a).
 *
 * PopupHost keeps the stack of open popups and a ref to the app's root
 * container; Popup renders through a portal INTO that container — scrim
 * and window are `position: absolute` inside it, the window pinned to
 * the container's top (the visible part of the VK page is unknown, so
 * nothing is centred vertically and nothing is `position: fixed`).
 * Every level adds its own scrim, so a nested confirmation darkens the
 * window below.
 *
 * Behaviour: Esc and a scrim click close only the TOP popup and do
 * nothing while the top popup is `dirty` (the «×» and footer buttons
 * still close). Focus lands on the first field of the body (else the
 * window), Tab/Shift+Tab stay inside the top popup and focus returns
 * to the element that had it before. Nesting allows one level and only
 * a size 'S' popup on top — anything else throws in non-production
 * builds. While a popup is open the host sets `min-height` on the
 * container from a ResizeObserver on the window, so the VK window
 * grows for a tall popup (`useWindowHeight` follows the container).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';

import { BlockIcon } from './icons';
import type { BlockIconName } from './icons';
import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  shadowVar,
  tokenVar,
} from './tokens';

export type PopupSize = 'S' | 'M' | 'L';

/** Spec 3.3 — the window hugs the top of the app window. */
const POPUP_TOP_PX = 64;
/** Bottom margin the container keeps below the lowest popup. */
const POPUP_BOTTOM_GAP_PX = 24;

const WIDTHS: Record<PopupSize, number> = {
  S: SIZES['win-popup-s'],
  M: SIZES['win-popup-m'],
  L: SIZES['win-popup-l'],
};

const FOCUSABLE_SELECTOR =
  'a[href], button, input, textarea, select, [tabindex]';

interface PopupEntry {
  id: symbol;
  size: PopupSize;
}

interface PopupHostValue {
  container: RefObject<HTMLElement | null>;
  /** The open popups, bottom → top. */
  stack: readonly PopupEntry[];
  mount: (id: symbol, size: PopupSize) => void;
  unmount: (id: symbol) => void;
  /** Track a popup's measured height for the container min-height. */
  setHeight: (id: symbol, px: number | null) => void;
}

const PopupHostContext = createContext<PopupHostValue | null>(null);

function usePopupHost(): PopupHostValue {
  const host = useContext(PopupHostContext);
  if (!host) {
    throw new Error('Popup must be used inside PopupHost');
  }
  return host;
}

export function PopupHost({
  container,
  children,
}: {
  /** The app root container — popups portal into it. */
  container: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  // `stack` drives re-renders (isTop); `stackRef` is the same array for
  // the mount-time nesting check, which runs inside layout effects.
  const stackRef = useRef<PopupEntry[]>([]);
  const [stack, setStack] = useState<readonly PopupEntry[]>([]);
  const heights = useRef(new Map<symbol, number>());

  const applyMinHeight = useCallback(() => {
    const el = container.current;
    if (!el) {
      return;
    }
    let lowest = 0;
    for (const height of heights.current.values()) {
      lowest = Math.max(lowest, height);
    }
    el.style.minHeight =
      lowest > 0 ? `${POPUP_TOP_PX + lowest + POPUP_BOTTOM_GAP_PX}px` : '';
  }, [container]);

  const mount = useCallback(
    (id: symbol, size: PopupSize) => {
      if (!import.meta.env.PROD) {
        if (stackRef.current.length >= 2) {
          throw new Error(
            'Popup: nesting beyond one level is forbidden — only a ' +
              "single 'S' popup may lie over another popup (UI Spec 3.3)",
          );
        }
        if (stackRef.current.length === 1 && size !== 'S') {
          throw new Error(
            `Popup: only an 'S' popup may lie over another popup ` +
              `(UI Spec 3.3), got size '${size}'`,
          );
        }
      }
      stackRef.current = [...stackRef.current, { id, size }];
      setStack(stackRef.current);
    },
    [],
  );

  const unmount = useCallback(
    (id: symbol) => {
      stackRef.current = stackRef.current.filter((e) => e.id !== id);
      heights.current.delete(id);
      setStack(stackRef.current);
      applyMinHeight();
    },
    [applyMinHeight],
  );

  const setHeight = useCallback(
    (id: symbol, px: number | null) => {
      if (px === null) {
        heights.current.delete(id);
      } else {
        heights.current.set(id, px);
      }
      applyMinHeight();
    },
    [applyMinHeight],
  );

  const value = useMemo<PopupHostValue>(
    () => ({ container, stack, mount, unmount, setHeight }),
    [container, stack, mount, unmount, setHeight],
  );

  return (
    <PopupHostContext.Provider value={value}>
      {children}
    </PopupHostContext.Provider>
  );
}

export interface PopupProps {
  size: PopupSize;
  title: string;
  icon?: BlockIconName;
  /** Extra node inside the title row, e.g. the nation mark. */
  headerExtra?: ReactNode;
  /** Esc and scrim clicks; always wired, `dirty` blocks both. */
  onClose: () => void;
  /** Unsaved input — Esc and the scrim no longer close the window. */
  dirty?: boolean;
  /** Body without padding and gap — full-bleed content (e.g. the map). */
  flush?: boolean;
  /** Footer bar content — the caller orders the buttons. */
  footer?: ReactNode;
  children: ReactNode;
  testId?: string;
}

export function Popup({
  size,
  title,
  icon,
  headerExtra,
  onClose,
  dirty = false,
  flush = false,
  footer,
  children,
  testId,
}: PopupProps) {
  const host = usePopupHost();
  const [selfId] = useState(() => Symbol('popup'));
  const dialogRef = useRef<HTMLElement>(null);
  const previousFocus = useRef<Element | null>(null);
  const titleId = useId();
  const isTop =
    host.stack.length > 0 &&
    host.stack[host.stack.length - 1].id === selfId;

  // Latest values for the document listeners — no listener churn on
  // every keystroke that flips `dirty`.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  // Stack registration + focus capture/restore + height reporting.
  useLayoutEffect(() => {
    previousFocus.current = document.activeElement;
    host.mount(selfId, size);
    const dialog = dialogRef.current;
    let observer: ResizeObserver | null = null;
    if (dialog && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        host.setHeight(selfId, dialog.offsetHeight);
      });
      observer.observe(dialog);
    }
    return () => {
      observer?.disconnect();
      host.unmount(selfId);
      const previous = previousFocus.current;
      if (previous instanceof HTMLElement && previous.isConnected) {
        previous.focus();
      }
    };
  }, [host.mount, host.unmount, host.setHeight, selfId, size]);

  // Autofocus: on becoming the top popup focus the first field in the
  // body, else the window itself — unless focus is already inside
  // (regained top after a nested popup restored its owner's focus).
  useEffect(() => {
    if (!isTop) {
      return;
    }
    const dialog = dialogRef.current;
    if (!dialog || dialog.contains(document.activeElement)) {
      return;
    }
    const field = dialog.querySelector<HTMLElement>(
      '[data-popup-body] input, [data-popup-body] textarea, [data-popup-body] select',
    );
    (field ?? dialog).focus();
  }, [isTop]);

  // Esc and the Tab trap — only while this popup is the top one.
  useEffect(() => {
    if (!isTop) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // A window part already consumed this Esc (e.g. it closed its
        // own dropdown) — the popup leaves it alone.
        if (event.defaultPrevented) {
          return;
        }
        if (!dirtyRef.current) {
          onCloseRef.current();
        }
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }
      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }
      const focusables = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter(
        (el) => !el.hasAttribute('disabled') && el.tabIndex >= 0,
      );
      if (focusables.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      const inside = active !== null && dialog.contains(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isTop]);

  const container = host.container.current;
  if (container === null) {
    return null;
  }

  return createPortal(
    <>
      <div
        data-testid={testId ? `${testId}-scrim` : undefined}
        onClick={
          isTop && !dirty
            ? (event) => {
                if (event.target === event.currentTarget) {
                  onClose();
                }
              }
            : undefined
        }
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0,0,0,0.6)',
        }}
      />
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid={testId}
        style={{
          position: 'absolute',
          top: POPUP_TOP_PX,
          left: '50%',
          transform: 'translateX(-50%)',
          width: WIDTHS[size],
          maxWidth: 'calc(100% - 32px)',
          boxSizing: 'border-box',
          background: tokenVar('surface-raised'),
          borderRadius: RADII['radius-lg'],
          boxShadow: shadowVar('shadow-popup'),
          overflow: 'hidden',
          color: tokenVar('ink'),
          ...TEXT_STYLES['body'],
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: SPACING['space-3'],
            padding: '12px 12px 12px 16px',
            borderBottom: `1px solid ${tokenVar('line')}`,
          }}
        >
          <h2
            id={titleId}
            style={{
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: SPACING['space-2'],
              minWidth: 0,
              ...TEXT_STYLES['title-uppercase'],
              fontSize: 20,
              lineHeight: '24px',
            }}
          >
            {icon && <BlockIcon name={icon} />}
            <span>{title}</span>
            {headerExtra}
          </h2>
          <button
            type="button"
            aria-label="Закрыть"
            onClick={onClose}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 32,
              height: 32,
              flexShrink: 0,
              padding: 0,
              border: 'none',
              borderRadius: RADII['radius-md'],
              background: tokenVar('surface-inset'),
              color: tokenVar('ink'),
              cursor: 'pointer',
            }}
          >
            <svg
              width={14}
              height={14}
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              strokeLinecap="round"
              aria-hidden="true"
              style={{ display: 'block' }}
            >
              <path d="M2 2l10 10M12 2L2 12" />
            </svg>
          </button>
        </div>
        <div
          data-popup-body
          style={{
            padding: flush ? 0 : SPACING['space-4'],
            display: 'flex',
            flexDirection: 'column',
            gap: flush ? 0 : SPACING['space-3'],
          }}
        >
          {children}
        </div>
        {footer !== undefined && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: SPACING['space-2'],
              padding: '12px 16px',
              borderTop: `1px solid ${tokenVar('line')}`,
            }}
          >
            {footer}
          </div>
        )}
      </section>
    </>,
    container,
  );
}
