/**
 * MapView — the SVG map surface (Spec Part 5, gestures per 3.8).
 *
 * Performance contract (1 123 paths, ~1.9 MB geometry):
 * - Layers bottom→top: background rect (inland_water) · `sea_water`
 *   bays path (sea fill, Spec 1.9 step 5a) · `outside` path ·
 *   ONE <g> with all node paths (single delegated mouse handling,
 *   resolved via `data-id`, no per-path listeners) · labels · overlays.
 * - Pan/zoom live in refs, never in React state; the transform is
 *   applied to ONE container <g> inside requestAnimationFrame. React
 *   state is committed only when a gesture settles (that is what the
 *   zoom-dependent label set re-evaluates on).
 * - Labels are hidden while a gesture is active (3.9 must not cost
 *   frames) and re-evaluated once it settles.
 * - Hover and selection are drawn as overlay copies of the node `d`,
 *   never by restyling the node paths.
 * - The wheel handler is registered non-passive and is the only zoom.
 * - Geometry is parsed once per version (paths memoised by version).
 *
 * `mode="select"` (Issue 6): a settled click reports the node id via
 * `onNodeClick` (the picker decides what it means), the selection draws
 * as a translucent `colors.selected` overlay, the cursor is pointer /
 * not-allowed over selectable / disabled nodes, and the tooltip line is
 * «Название — свободна | занята: … | морская зона, выбрать нельзя».
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import {
  DRAG_THRESHOLD_PX,
  FOCUS_BBOX_MARGIN,
  GESTURE_SETTLE_MS,
  LABEL_FONT_PX,
  LABEL_HALO_COLOR,
  LABEL_HALO_PX,
  LABEL_TEXT_COLOR,
  OVERLAY_STROKE_PX,
  SELECTED_FILL_OPACITY,
  TOOLTIP_OFFSET_PX,
} from '../constants';
import { buildOwnerMap, nodeFill } from '../lib/colors';
import { displayName } from '../lib/search';
import { selectTooltipStatus } from '../lib/selection';
import { visibleLabelNodes } from '../lib/labels';
import {
  bboxCenter,
  centerOn,
  clampOffset,
  fitBBox,
  initialTransform,
  minScale,
  rescaleOnResize,
  scaleBounds,
  zoomAt,
  type BBox,
  type Point,
  type Size,
  type ViewTransform,
} from '../lib/view';
import type {
  MapGeometryDTO,
  MapManifestDTO,
  MapNationDTO,
  MapNodeDTO,
  MapStateDTO,
} from '../types';

export type MapViewMode = 'view' | 'select';

/** Imperative view request; `seq` bumps re-apply the same target. */
export interface MapViewFocus {
  seq: number;
  mode: 'fit' | 'center';
  bbox: BBox;
}

export interface MapViewProps {
  mode?: MapViewMode;
  manifest: MapManifestDTO;
  geometry: MapGeometryDTO;
  /** Latest good state payload (colours); null until first load. */
  state?: MapStateDTO | null;
  selectedIds?: number[];
  disabledIds?: number[];
  onNodeClick?: (id: number | null) => void;
  onHoverChange?: (id: number | null) => void;
  focus?: MapViewFocus | null;
}

/** Wheel zoom step per notch — pure UI feel, not a balance rule. */
const WHEEL_ZOOM_STEP = 1.25;

function nodeIdFrom(target: EventTarget | null): number | null {
  const el = target instanceof Element ? target.closest('[data-id]') : null;
  const raw = el?.getAttribute('data-id');
  if (raw === null || raw === undefined) {
    return null;
  }
  const id = Number(raw);
  return Number.isFinite(id) ? id : null;
}

export function MapView(props: MapViewProps) {
  const mode = props.mode ?? 'view';

  const { manifest, geometry } = props;
  const rules = manifest.rules;
  const colors = rules.colors;

  const containerRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<SVGGElement>(null);
  const labelsGRef = useRef<SVGGElement>(null);
  const hoverPathRef = useRef<SVGPathElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const viewRef = useRef<ViewTransform | null>(null);
  const frame = useRef(0);
  const dragging = useRef<{
    startX: number;
    startY: number;
    lastX: number;
    lastY: number;
    moved: boolean;
    target: EventTarget | null;
  } | null>(null);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverId = useRef<number | null>(null);
  const cursor = useRef<Point>({ x: 0, y: 0 });

  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  const prevViewport = useRef<Size>({ width: 0, height: 0 });
  const [view, setView] = useState<ViewTransform | null>(null);
  const [hoverNode, setHoverNode] = useState<MapNodeDTO | null>(null);

  const nodesById = useMemo(
    () => new Map(manifest.nodes.map((n) => [n.id, n])),
    [manifest],
  );
  const owners = useMemo(
    () => buildOwnerMap(props.state ?? null, nodesById),
    [props.state, nodesById],
  );

  /* ------------------------------------------------ transform plumbing */

  const applyTransform = useCallback(() => {
    if (frame.current !== 0) {
      return;
    }
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const v = viewRef.current;
      if (v && worldRef.current) {
        worldRef.current.setAttribute(
          'transform',
          `translate(${v.tx} ${v.ty}) scale(${v.s})`,
        );
      }
    });
  }, []);

  const commitView = useCallback((v: ViewTransform) => {
    viewRef.current = v;
    setView(v);
    applyTransform();
  }, [applyTransform]);

  const bounds = useCallback((): [number, number] => {
    const sMin = minScale(rules.frame, viewport);
    return scaleBounds(sMin, rules.zoom_max);
  }, [rules.frame, viewport, rules.zoom_max]);

  const clamped = useCallback(
    (v: ViewTransform): ViewTransform =>
      clampOffset(v, rules.frame, viewport, rules.pan_margin_fraction),
    [rules.frame, viewport, rules.pan_margin_fraction],
  );

  const setLabelsVisible = useCallback((visible: boolean) => {
    if (labelsGRef.current) {
      labelsGRef.current.style.display = visible ? '' : 'none';
    }
  }, []);

  /* ------------------------------------------------------ viewport fit */

  // Measure the container; centre the frame on first layout and keep
  // the view centre on every later resize (incl. fullscreen switches).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) {
      return;
    }
    const measure = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        return;
      }
      const size = { width: rect.width, height: rect.height };
      setViewport(size);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (viewport.width === 0) {
      return;
    }
    const prev = prevViewport.current;
    prevViewport.current = viewport;
    const next =
      prev.width === 0 || viewRef.current === null
        ? initialTransform(rules.frame, viewport)
        : rescaleOnResize(
            viewRef.current,
            rules.frame,
            prev,
            viewport,
          );
    commitView(clamped(next));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only size changes
  }, [viewport]);

  /* ------------------------------------------------------------ focus */

  useEffect(() => {
    if (!props.focus || viewport.width === 0) {
      return;
    }
    const [sMin, sMax] = bounds();
    const current =
      viewRef.current ?? initialTransform(rules.frame, viewport);
    const next =
      props.focus.mode === 'fit'
        ? fitBBox(props.focus.bbox, viewport, FOCUS_BBOX_MARGIN, sMin, sMax)
        : centerOn(current, bboxCenter(props.focus.bbox), viewport, sMin, sMax);
    commitView(clamped(next));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by seq
  }, [props.focus?.seq]);

  /* ----------------------------------------------------------- gestures */

  const beginGesture = useCallback(() => {
    setLabelsVisible(false);
    if (settleTimer.current) {
      clearTimeout(settleTimer.current);
    }
  }, [setLabelsVisible]);

  const endGestureSoon = useCallback(() => {
    if (settleTimer.current) {
      clearTimeout(settleTimer.current);
    }
    settleTimer.current = setTimeout(() => {
      settleTimer.current = null;
      setLabelsVisible(true);
      if (viewRef.current) {
        setView({ ...viewRef.current });
      }
    }, GESTURE_SETTLE_MS);
  }, [setLabelsVisible]);

  // Wheel zoom — non-passive, the only zoom path (Spec 3.8).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) {
      return;
    }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (viewRef.current === null) {
        return;
      }
      const rect = el.getBoundingClientRect();
      const c = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      const [sMin, sMax] = bounds();
      const step = e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP;
      const nextScale = Math.min(
        sMax,
        Math.max(sMin, viewRef.current.s * step),
      );
      if (nextScale === viewRef.current.s) {
        return;
      }
      beginGesture();
      viewRef.current = clamped(zoomAt(viewRef.current, c, nextScale));
      applyTransform();
      endGestureSoon();
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [bounds, clamped, applyTransform, beginGesture, endGestureSoon]);

  const positionTooltip = useCallback(() => {
    const el = tooltipRef.current;
    if (el) {
      el.style.transform = `translate(${cursor.current.x + TOOLTIP_OFFSET_PX}px, ${
        cursor.current.y + TOOLTIP_OFFSET_PX
      }px)`;
    }
  }, []);

  const setHover = useCallback(
    (id: number | null) => {
      if (id === hoverId.current) {
        return;
      }
      hoverId.current = id;
      const node = id === null ? null : (nodesById.get(id) ?? null);
      setHoverNode(node);
      if (hoverPathRef.current) {
        if (node) {
          hoverPathRef.current.setAttribute(
            'd',
            geometry.paths[node.id] ?? '',
          );
          hoverPathRef.current.style.display = '';
        } else {
          hoverPathRef.current.style.display = 'none';
        }
      }
      props.onHoverChange?.(id);
    },
    [geometry.paths, nodesById, props.onHoverChange],
  );

  const toLocal = useCallback((e: React.MouseEvent | MouseEvent): Point => {
    const rect = containerRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) {
      return;
    }
    dragging.current = {
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      moved: false,
      target: e.target,
    };
  }, []);

  // Drag continues outside the container — listeners live on window.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const drag = dragging.current;
      if (!drag || !drag.moved || viewRef.current === null) {
        return;
      }
      const dx = e.clientX - drag.lastX;
      const dy = e.clientY - drag.lastY;
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
      beginGesture();
      viewRef.current = clamped({
        ...viewRef.current,
        tx: viewRef.current.tx + dx,
        ty: viewRef.current.ty + dy,
      });
      applyTransform();
    };
    const onUp = () => {
      const drag = dragging.current;
      if (!drag) {
        return;
      }
      dragging.current = null;
      if (drag.moved) {
        endGestureSoon();
        return;
      }
      const id = nodeIdFrom(drag.target);
      props.onNodeClick?.(id);
    };
    const onMoveGlobal = (e: MouseEvent) => {
      const drag = dragging.current;
      if (drag && !drag.moved) {
        if (
          Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) >=
          DRAG_THRESHOLD_PX
        ) {
          drag.moved = true;
        }
      }
      onMove(e);
    };
    window.addEventListener('mousemove', onMoveGlobal);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMoveGlobal);
      window.removeEventListener('mouseup', onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clamped, applyTransform, beginGesture, endGestureSoon, props.onNodeClick]);

  const onMouseMove = useCallback(
    (e: React.MouseEvent) => {
      cursor.current = toLocal(e);
      positionTooltip();
      if (dragging.current?.moved) {
        return;
      }
      setHover(nodeIdFrom(e.target));
    },
    [toLocal, positionTooltip, setHover],
  );

  const onMouseLeave = useCallback(() => {
    setHover(null);
  }, [setHover]);

  useEffect(
    () => () => {
      if (frame.current) {
        cancelAnimationFrame(frame.current);
      }
      if (settleTimer.current) {
        clearTimeout(settleTimer.current);
      }
    },
    [],
  );

  /* ------------------------------------------------------------ render */

  const ownerOf = (id: number): MapNationDTO | undefined => owners.get(id);

  const nodePaths = useMemo(
    () =>
      manifest.nodes.map((node) => (
        <path
          key={node.id}
          data-id={node.id}
          d={geometry.paths[node.id] ?? ''}
          fill={nodeFill(node, ownerOf(node.id), colors)}
          stroke={colors.province_border}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [manifest.nodes, geometry.version, owners, colors],
  );

  const labeled = useMemo(
    () =>
      view === null
        ? []
        : visibleLabelNodes(manifest.nodes, view.s, rules.label_min_width_px),
    [manifest.nodes, view, rules.label_min_width_px],
  );

  const selected = props.selectedIds ?? [];
  const disabledSet = useMemo(
    () => new Set(props.disabledIds ?? []),
    [props.disabledIds],
  );
  const hoverOwner =
    hoverNode && hoverNode.kind === 'LAND'
      ? owners.get(hoverNode.id)
      : undefined;

  // Select-mode cursor (Spec Part 5): pointer over a selectable node,
  // not-allowed over a disabled one — derived from `hoverNode`, so it
  // changes only when the hovered node changes.
  const cursorStyle =
    mode !== 'select'
      ? 'grab'
      : hoverNode === null
        ? 'grab'
        : disabledSet.has(hoverNode.id)
          ? 'not-allowed'
          : 'pointer';

  return (
    <div
      ref={containerRef}
      data-testid="map-view"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        cursor: cursorStyle,
        userSelect: 'none',
        // Anything beyond view_box (pan margin, oversized window) is
        // land/unknown sea outside the playable field.
        background: colors.outside,
      }}
    >
      <svg width={viewport.width} height={viewport.height}>
        <g ref={worldRef}>
          {/* background — inland water shows through the holes (lakes)
              of `outside`; confined to view_box in MAP coordinates so
              it can never bleed beyond the map area. */}
          <rect
            data-layer="inland-water"
            x={manifest.view_box[0]}
            y={manifest.view_box[1]}
            width={manifest.view_box[2]}
            height={manifest.view_box[3]}
            fill={colors.inland_water}
          />
          {geometry.sea_water !== '' && (
            <path
              data-layer="sea-water"
              d={geometry.sea_water}
              fill={colors.sea}
              pointerEvents="none"
            />
          )}
          <path d={geometry.outside} fill={colors.outside} />
          <g>{nodePaths}</g>
          <g ref={labelsGRef} pointerEvents="none">
            {labeled.map((node) => (
              <text
                key={node.id}
                x={node.anchor[0]}
                y={node.anchor[1]}
                textAnchor="middle"
                fill={LABEL_TEXT_COLOR}
                stroke={LABEL_HALO_COLOR}
                paintOrder="stroke"
                fontSize={view ? LABEL_FONT_PX / view.s : 0}
                strokeWidth={view ? LABEL_HALO_PX / view.s : 0}
              >
                {displayName(node)}
              </text>
            ))}
          </g>
          {/* hover + selection overlays — copies of node paths */}
          <g pointerEvents="none">
            {selected.map((id) => (
              <path
                key={id}
                data-selected={id}
                d={geometry.paths[id] ?? ''}
                fill={mode === 'select' ? colors.selected : 'none'}
                fillOpacity={
                  mode === 'select' ? SELECTED_FILL_OPACITY : undefined
                }
                stroke={colors.selected}
                strokeWidth={OVERLAY_STROKE_PX}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            <path
              ref={hoverPathRef}
              fill="none"
              stroke={colors.hover}
              strokeWidth={OVERLAY_STROKE_PX}
              vectorEffect="non-scaling-stroke"
              style={{ display: 'none' }}
            />
          </g>
        </g>
      </svg>
      {hoverNode && (
        <div
          ref={tooltipRef}
          data-testid="map-tooltip"
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            pointerEvents: 'none',
            background: 'rgba(20,20,24,0.92)',
            color: '#fff',
            borderRadius: 6,
            padding: '4px 8px',
            fontSize: 13,
            whiteSpace: 'nowrap',
          }}
        >
          {mode === 'select' ? (
            <div>
              {displayName(hoverNode)} —{' '}
              {selectTooltipStatus(hoverNode, hoverOwner)}
            </div>
          ) : (
            <>
              <div>{displayName(hoverNode)}</div>
              <div style={{ opacity: 0.75 }}>
                {hoverNode.kind === 'SEA'
                  ? 'Морская зона'
                  : hoverOwner
                    ? hoverOwner.name
                    : 'свободна'}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
