/**
 * Tooltip — the «Подсказка» (UI Spec 3.4, version 0.9.0 unit 11): a
 * small read-only window that opens AT THE CURSOR ~0.5 s after the
 * pointer enters the trigger, then FOLLOWS the pointer while it moves
 * over the trigger (Project Owner decision 21.10.2026) and closes the
 * moment the pointer leaves. A pointerdown, a page or table scroll,
 * Esc or a window blur close it too; the box is `pointer-events:
 * none`, so it never steals the hover or a click and never flickers
 * under the cursor.
 *
 * The pointer's last known spot is tracked from `pointerenter` on —
 * a tip that opens after the delay lands where the pointer IS, not
 * where it was half a second ago. Following runs on
 * `requestAnimationFrame` (at most one position update per frame)
 * with no CSS transition, so the tip does not lag. The box renders
 * hidden, is measured once via `getBoundingClientRect` and shown
 * (no flicker); a ResizeObserver re-measures only when the content
 * changes size (e.g. the nation's data arrives while the tip keeps
 * following).
 *
 * The box is portaled into the app root container
 * (`[data-testid="app-root"]`, `position: relative`) with
 * `position: absolute` — never `fixed`, because the VK window's
 * scroll position is unknown to the app (same reason as Popup and
 * Notice, UI Spec 2). It carries no z-index: positioned, it paints
 * over the table's in-flow content, and its portal node is committed
 * before the popups' in the same container, so a popup window and its
 * scrim always lie above it; only the table's sticky header
 * (z-index 5) may cross over it — and any scroll closes the tip
 * anyway.
 *
 * It never leaves the container: near the right edge it shifts left
 * to an 8 px inset, near the bottom it flips above the pointer and
 * flips back when the pointer moves up, and it is clamped to the
 * top — all continuously, so it slides along an edge as the pointer
 * moves. Opening never moves focus and, being absolutely positioned,
 * never changes the container's height.
 */

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  shadowVar,
  tokenVar,
} from './tokens';

/** Spec 3.4 — the tip opens after ~0.5 s of hovering. */
export const TOOLTIP_DELAY_MS = 500;

/** The tip opens this far right of the pointer and this far below it. */
const OFFSET_X_PX = 12;
const OFFSET_Y_PX = 16;
/** Inset the tip keeps to the container's right edge. */
const EDGE_INSET_PX = 8;
/** The root container every overlay of the app portals into. */
const APP_ROOT_SELECTOR = '[data-testid="app-root"]';

interface TipPosition {
  left: number;
  top: number;
}

export interface TooltipProps {
  /**
   * What the tip shows. A function is called while the tip is open —
   * the content may load data (show its own muted «Загрузка…» line)
   * and re-render; the tip keeps following the pointer meanwhile.
   */
  content: ReactNode | (() => ReactNode);
  /** Hover delay before the tip opens — `TOOLTIP_DELAY_MS` (500 ms). */
  delayMs?: number;
  /** The trigger, wrapped in a span that fills its container box. */
  children: ReactNode;
}

// The trigger fills its box: an inline-flex wrapper would shrink to
// the text and the tip would close the moment the pointer slid off
// the glyphs while still inside the cell — the «doesn't follow» bug
// seen in real VK (12b). `height: 100%` resolves against sized
// containers (a table cell); elsewhere it is just auto.
const TRIGGER_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  minWidth: 0,
  maxWidth: '100%',
  height: '100%',
};

const TIP_STYLE: CSSProperties = {
  position: 'absolute',
  boxSizing: 'border-box',
  maxWidth: SIZES['win-tooltip-max'],
  padding: `${SPACING['space-2']}px ${SPACING['space-3']}px`,
  background: tokenVar('surface-raised'),
  border: `1px solid ${tokenVar('line')}`,
  borderRadius: RADII['radius-md'],
  boxShadow: shadowVar('shadow-tip'),
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
  pointerEvents: 'none',
};

export function Tooltip({
  content,
  delayMs = TOOLTIP_DELAY_MS,
  children,
}: TooltipProps) {
  const tooltipId = useId();
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const pointerRef = useRef({ x: 0, y: 0 });
  const hostRef = useRef<HTMLElement | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const timerRef = useRef<number | undefined>(undefined);
  const frameRef = useRef<number | undefined>(undefined);
  const [armed, setArmed] = useState(false);
  const [open, setOpen] = useState(false);
  const [measured, setMeasured] = useState(false);
  const [pos, setPos] = useState<TipPosition | null>(null);

  const close = useCallback(() => {
    window.clearTimeout(timerRef.current);
    timerRef.current = undefined;
    if (frameRef.current !== undefined) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = undefined;
    }
    setArmed(false);
    setOpen(false);
    setMeasured(false);
    setPos(null);
  }, []);

  // The clamped position for the CURRENT pointer spot: +12/+16 from
  // it, slid left to the edge inset, flipped above the pointer when
  // the bottom would cross the container's and clamped to its top.
  const place = useCallback(() => {
    const host = hostRef.current;
    if (host === null) {
      return;
    }
    const rect = host.getBoundingClientRect();
    const { width, height } = sizeRef.current;
    let left = pointerRef.current.x - rect.left + OFFSET_X_PX;
    if (left + width > rect.width) {
      left = rect.width - EDGE_INSET_PX - width;
    }
    if (left < 0) {
      left = 0;
    }
    let top = pointerRef.current.y - rect.top + OFFSET_Y_PX;
    if (top + height > rect.height) {
      top = pointerRef.current.y - rect.top - OFFSET_Y_PX - height;
    }
    if (top < 0) {
      top = 0;
    }
    setPos({ left, top });
  }, []);

  const onPointerEnter = (event: ReactPointerEvent<HTMLSpanElement>) => {
    pointerRef.current = { x: event.clientX, y: event.clientY };
    window.clearTimeout(timerRef.current);
    setArmed(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = undefined;
      hostRef.current =
        wrapperRef.current?.closest<HTMLElement>(APP_ROOT_SELECTOR) ??
        document.body;
      setArmed(false);
      setOpen(true);
    }, delayMs);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLSpanElement>) => {
    pointerRef.current = { x: event.clientX, y: event.clientY };
    if (!open || frameRef.current !== undefined) {
      return;
    }
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = undefined;
      place();
    });
  };

  // First commit of the portal: measure the hidden box once, place
  // and show it — no flicker. After that a ResizeObserver re-measures
  // only when the content changes size; every pointer move reuses the
  // stored size and only re-runs the clamp.
  useLayoutEffect(() => {
    if (!open) {
      return;
    }
    const box = boxRef.current;
    if (box !== null) {
      const rect = box.getBoundingClientRect();
      sizeRef.current = { width: rect.width, height: rect.height };
    }
    place();
    setMeasured(true);
    if (box === null || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(() => {
      const rect = box.getBoundingClientRect();
      sizeRef.current = { width: rect.width, height: rect.height };
      place();
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [open, place]);

  // A click anywhere, a scroll of the page or the table, Esc and a
  // window blur close an armed or open tip alike.
  useEffect(() => {
    if (!armed && !open) {
      return;
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close();
      }
    };
    document.addEventListener('pointerdown', close, true);
    document.addEventListener('scroll', close, true);
    window.addEventListener('scroll', close);
    document.addEventListener('keydown', onEscape);
    window.addEventListener('blur', close);
    return () => {
      document.removeEventListener('pointerdown', close, true);
      document.removeEventListener('scroll', close, true);
      window.removeEventListener('scroll', close);
      document.removeEventListener('keydown', onEscape);
      window.removeEventListener('blur', close);
    };
  }, [armed, open, close]);

  // Nothing outlives the trigger.
  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current);
      if (frameRef.current !== undefined) {
        cancelAnimationFrame(frameRef.current);
      }
    },
    [],
  );

  const host = hostRef.current;
  return (
    <>
      <span
        ref={wrapperRef}
        aria-describedby={open ? tooltipId : undefined}
        onPointerEnter={onPointerEnter}
        onPointerMove={onPointerMove}
        onPointerLeave={close}
        style={TRIGGER_STYLE}
      >
        {children}
      </span>
      {open &&
        host !== null &&
        createPortal(
          <div
            ref={boxRef}
            role="tooltip"
            id={tooltipId}
            data-testid="tooltip"
            style={{
              ...TIP_STYLE,
              left: pos?.left ?? 0,
              top: pos?.top ?? 0,
              visibility: measured ? 'visible' : 'hidden',
            }}
          >
            {typeof content === 'function' ? content() : content}
          </div>,
          host,
        )}
    </>
  );
}

/**
 * TooltipRow — a «label : value» line inside a «Подсказка»: the label
 * muted on the left, the value in `ink` on the right (Spec 3.4).
 */
export function TooltipRow({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: SPACING['space-3'],
      }}
    >
      <span style={{ color: tokenVar('ink-muted'), flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ color: tokenVar('ink'), textAlign: 'right' }}>
        {value}
      </span>
    </div>
  );
}
