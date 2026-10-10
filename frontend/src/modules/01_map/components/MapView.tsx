/**
 * MapView — the SVG map surface (Spec Part 5, gestures per 3.8).
 *
 * Performance contract (1 123 paths, ~1.9 MB geometry):
 * - Layers bottom→top: background rect (inland_water) · `sea_water`
 *   bays path (sea fill, Spec 1.9 step 5a) · `outside` path ·
 *   ONE <g> with all node paths (single delegated mouse handling,
 *   resolved via `data-id`, no per-path listeners) · border chunks ·
 *   labels · overlays.
 * - Pan/zoom live in refs, never in React state. Every frame of a
 *   gesture writes the LIVE transform into the `transform` attribute
 *   of ONE container <g> inside requestAnimationFrame (map2_14): the
 *   map is re-painted for real every frame — there is no snapshot
 *   raster, no bake-on-settle swap, and nothing hides mid-gesture.
 *   The zoom-dependent label set re-evaluates only when a gesture
 *   settles (Spec 3.9), so a gesture commits no React state at all —
 *   label size/halo and the border LOD pick are imperative writes on
 *   the <g> elements.
 * - Labels stay visible during gestures: their font size and halo
 *   live on the labels <g> and follow the in-flight scale through two
 *   attribute writes per frame. The selection pulse is paused for the
 *   gesture + the settle window (invisible — the pulse is opaque
 *   nowhere). Every border stays visible always (map2_13).
 * - Hover and selection are drawn as overlay copies of the node `d`,
 *   never by restyling the node paths.
 * - The wheel handler is registered non-passive and is the only zoom.
 * - Geometry is parsed once per version (paths memoised by version).
 *
 * Border layer (map2_4, map2_13, map2_14): the shared borders from
 * `borders.json` sit between the fills and the labels — thin solid
 * INTERNAL inside one owner (or both free), solid STATE on land
 * borders between owners, thin COAST everywhere a node meets the
 * sea/excluded land/map edge — split into an 8×8 spatial chunk grid
 * so the browser can cull off-screen cells instead of re-stroking the
 * whole map every frame. Each class×cell exists in three LOD copies
 * (two Douglas–Peucker simplifications under half a screen pixel at
 * their switch scales, plus the original geometry); only the matching
 * LOD group is displayed. Ownership changes re-join only the cells
 * whose pairs changed class. The seam cover (map2_13) is a stroke of
 * `colors.land_underlay` on the fills <g> itself: cracks between
 * neighbours show land colour, never the sea — gated to the zoom
 * levels where a covered crack can reach a pixel. The legacy per-node
 * stroke remains the fallback when the borders payload failed to load
 * (the hook logs one warning then).
 *
 * `mode="select"` (Issue 6): a settled click reports the node id via
 * `onNodeClick` (the picker decides what it means), picked provinces
 * draw a constant white `colors.hover` fill at
 * `selection.picked_opacity`, the cursor is pointer / not-allowed over
 * selectable / disabled nodes, and the tooltip line is «Название —
 * свободна | занята: … | морская зона, выбрать нельзя». In `view` mode
 * the single inspected province carries the same white fill pulsing
 * between `selection.pulse_min_opacity` and `pulse_max_opacity` (CSS
 * animation; `prefers-reduced-motion` freezes it at the midpoint).
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
  SEAM_MIN_S,
  SEAM_NSS_MAX_S,
  SEAM_STROKE_PX,
  SEAM_STROKE_W,
  TOOLTIP_OFFSET_PX,
} from '../constants';
import {
  BORDER_LODS,
  borderLOD,
  buildBorderLayer,
  reclassifyBorderLayer,
  type BorderLOD,
  type BorderLayer,
} from '../lib/borders';
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
  MapBordersDTO,
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
  /** Shared borders of `manifest.borders_version`; null until loaded. */
  borders?: MapBordersDTO | null;
  /** Borders load failed — draw the legacy per-node strokes instead. */
  bordersFailed?: boolean;
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
  const nodesGRef = useRef<SVGGElement>(null);
  const hoverPathRef = useRef<SVGPathElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const viewRef = useRef<ViewTransform | null>(null);
  const frame = useRef(0);
  /** Scale last written into the labels <g> / LOD pick. */
  const scaledS = useRef(0);
  /** Seam-cover band last written to the nodes <g>: off below
   *  SEAM_MIN_S, a non-scaling hairline to SEAM_NSS_MAX_S, the
   *  world-space stroke above. */
  const seamBand = useRef<'off' | 'nss' | 'world'>('world');
  /** Border LOD group currently displayed. */
  const lodRef = useRef<BorderLOD>('high');
  /** The three LOD <g> elements — display is owned imperatively. */
  const lodGroupRefs = useRef<
    Partial<Record<BorderLOD, SVGGElement | null>>
  >({});
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

  // Write one seam band into the DOM: the inherited group width plus,
  // only on entering/leaving the non-scaling band, vector-effect on
  // every fill (it does not inherit — ~1000 writes, once per crossing).
  const applySeamBand = useCallback(
    (band: 'off' | 'nss' | 'world', prev?: 'off' | 'nss' | 'world') => {
      const g = nodesGRef.current;
      if (!g) {
        return;
      }
      g.setAttribute(
        'stroke-width',
        band === 'world'
          ? String(SEAM_STROKE_W)
          : band === 'nss'
            ? String(SEAM_STROKE_PX)
            : '0',
      );
      if (band === 'nss' || prev === 'nss') {
        for (const p of g.querySelectorAll('path[data-id]')) {
          if (band === 'nss') {
            p.setAttribute('vector-effect', 'non-scaling-stroke');
          } else {
            p.removeAttribute('vector-effect');
          }
        }
      }
    },
    [],
  );

  // Write the live view into the DOM: the world transform (every
  // frame) plus, only when the scale actually moved, the label
  // font-size/halo on the labels <g> and the border LOD pick — a few
  // attribute writes per frame, never a React commit. The label SET
  // re-evaluates only on settle (Spec 3.9) so a zoom burst diffs no
  // label elements mid-gesture.
  const writeView = useCallback((v: ViewTransform) => {
    worldRef.current?.setAttribute(
      'transform',
      `translate(${v.tx} ${v.ty}) scale(${v.s})`,
    );
    if (v.s === scaledS.current) {
      return;
    }
    scaledS.current = v.s;
    labelsGRef.current?.setAttribute(
      'font-size',
      String(LABEL_FONT_PX / v.s),
    );
    labelsGRef.current?.setAttribute(
      'stroke-width',
      String(LABEL_HALO_PX / v.s),
    );
    const nextLod = borderLOD(v.s);
    if (nextLod !== lodRef.current) {
      const prev = lodGroupRefs.current[lodRef.current];
      if (prev) {
        prev.style.display = 'none';
      }
      lodRef.current = nextLod;
      const next = lodGroupRefs.current[nextLod];
      if (next) {
        next.style.display = '';
      }
    }
    // Seam cover band switch (one batch of writes on a threshold
    // crossing, never per frame): below SEAM_MIN_S the stroke is off —
    // even the widest covered void is subpixel; to SEAM_NSS_MAX_S a
    // non-scaling hairline hits the fast raster path; above it the
    // world-space stroke is both cheaper (no per-frame device
    // re-stroke on zoom) and already pixel-wide.
    const band =
      v.s < SEAM_MIN_S ? 'off' : v.s < SEAM_NSS_MAX_S ? 'nss' : 'world';
    if (band !== seamBand.current) {
      const prev = seamBand.current;
      seamBand.current = band;
      applySeamBand(band, prev);
    }
  }, [applySeamBand]);

  // Per-frame live redraw while a gesture is in flight — every frame
  // paints the real map at the in-flight position (map2_14).
  const applyTransform = useCallback(() => {
    if (frame.current !== 0) {
      return;
    }
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const v = viewRef.current;
      if (v) {
        writeView(v);
      }
    });
  }, [writeView]);

  const commitView = useCallback(
    (v: ViewTransform) => {
      viewRef.current = v;
      writeView(v);
      setView(v);
    },
    [writeView],
  );

  const bounds = useCallback((): [number, number] => {
    const sMin = minScale(rules.frame, viewport);
    return scaleBounds(sMin, rules.zoom_max);
  }, [rules.frame, viewport, rules.zoom_max]);

  const clamped = useCallback(
    (v: ViewTransform): ViewTransform =>
      clampOffset(v, rules.frame, viewport, rules.pan_margin_fraction),
    [rules.frame, viewport, rules.pan_margin_fraction],
  );

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

  // While a gesture (or the settle window) is active the only flag is
  // `data-gesture`: CSS pauses the selection pulse under it. Nothing
  // else is simplified — every layer, labels included, stays live
  // (map2_14).
  const setGestureFlag = useCallback((active: boolean) => {
    containerRef.current?.toggleAttribute('data-gesture', active);
  }, []);

  const beginGesture = useCallback(() => {
    setGestureFlag(true);
    if (settleTimer.current) {
      clearTimeout(settleTimer.current);
    }
  }, [setGestureFlag]);

  const endGestureSoon = useCallback(() => {
    if (settleTimer.current) {
      clearTimeout(settleTimer.current);
    }
    settleTimer.current = setTimeout(() => {
      settleTimer.current = null;
      setGestureFlag(false);
      if (viewRef.current) {
        setView({ ...viewRef.current });
      }
    }, GESTURE_SETTLE_MS);
  }, [setGestureFlag]);

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

  // The chunked border layer: built once per borders payload, then
  // reclassified incrementally on every owners change — only the
  // cells whose pairs flipped class get new strings, every other
  // cell keeps its reference and React writes no `d` for it (map2_14).
  const layerRef = useRef<BorderLayer | null>(null);
  const borderLayer = useMemo(() => {
    let next: BorderLayer | null = null;
    if (props.borders) {
      next =
        layerRef.current !== null &&
        layerRef.current.borders === props.borders
          ? reclassifyBorderLayer(layerRef.current, owners)
          : buildBorderLayer(props.borders, owners, manifest.view_box);
    }
    layerRef.current = next;
    return next;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.borders, owners, manifest.view_box]);
  // Legacy per-node strokes survive only as the borders-failed fallback.
  const legacyStrokes =
    borderLayer === null && props.bordersFailed === true;

  // Seam cover (map2_13) as a per-node stroke (map2_14): every fill
  // carries a hairline of `land_underlay` in world units, so a crack
  // between neighbours shows land colour — the same pixels the old
  // under-stroke covered, but rasterised inside each node's own
  // bounding box, which the browser culls far better than the old
  // compound seam paths.
  const seamStrokes = borderLayer !== null;
  const seamColor = colors.land_underlay ?? colors.neutral_province;

  const nodePaths = useMemo(
    () =>
      manifest.nodes.map((node) => (
        <path
          key={node.id}
          data-id={node.id}
          d={geometry.paths[node.id] ?? ''}
          fill={nodeFill(node, ownerOf(node.id), colors)}
          // Seam-cover stroke inherits colour and width from the nodes
          // <g> — writeView gates the width to zero at zoom levels
          // where every covered crack would be subpixel anyway.
          stroke={
            seamStrokes
              ? undefined
              : legacyStrokes
                ? colors.province_border
                : 'none'
          }
          strokeWidth={legacyStrokes ? 1 : undefined}
          vectorEffect={legacyStrokes ? 'non-scaling-stroke' : undefined}
        />
      )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [manifest.nodes, geometry.version, owners, colors, legacyStrokes, seamStrokes, seamColor],
  );

  const labeled = useMemo(
    () =>
      view === null
        ? []
        : visibleLabelNodes(manifest.nodes, view.s, rules.label_min_width_px),
    [manifest.nodes, view, rules.label_min_width_px],
  );

  // Border chunks as a memoised subtree: settle-time React commits
  // (label set, ownership) re-render MapView but bail out on this
  // stable element array — and during a gesture there are no commits.
  const borderEls = useMemo(() => {
    if (borderLayer === null) {
      return null;
    }
    const b = rules.borders;
    const classStyle: Record<
      'internal' | 'coast' | 'state',
      {
        stroke: string;
        strokeWidth: number;
        strokeOpacity?: number;
      }
    > = {
      internal: {
        stroke: b.internal_color,
        strokeWidth: b.internal_width,
        strokeOpacity: b.internal_opacity,
      },
      coast: {
        stroke: b.coast_color,
        strokeWidth: b.coast_width,
      },
      state: {
        stroke: b.state_color,
        strokeWidth: b.state_width,
      },
    };
    return (
      <g data-layer="borders" pointerEvents="none">
        {BORDER_LODS.map((level) => (
          <g
            key={level}
            ref={(el) => {
              lodGroupRefs.current[level] = el;
            }}
            data-border-lod={level}
            // Display starts hidden and is owned imperatively by
            // writeView — a LOD switch mid-gesture never re-renders.
            style={{ display: 'none' }}
          >
            {(Object.keys(classStyle) as Array<keyof typeof classStyle>).map(
              (cls) => (
                <g key={cls} data-border={cls} fill="none" {...classStyle[cls]}>
                  {borderLayer.chunks[level][cls].map(
                    (d, i) =>
                      d !== null && (
                        <path
                          key={i}
                          d={d}
                          vectorEffect="non-scaling-stroke"
                        />
                      ),
                  )}
                </g>
              ),
            )}
          </g>
        ))}
      </g>
    );
  }, [borderLayer, rules.borders]);

  // Show the LOD group matching the current scale when the layer
  // (re)mounts — afterwards writeView owns the display flips.
  useEffect(() => {
    for (const level of BORDER_LODS) {
      const el = lodGroupRefs.current[level];
      if (el) {
        el.style.display = level === lodRef.current ? '' : 'none';
      }
    }
  }, [borderLayer]);

  // Re-apply the seam band after the fills re-render — a React write
  // of the paths' stroke props would drop the imperative band attrs.
  useEffect(() => {
    applySeamBand(seamBand.current, seamBand.current);
  }, [nodePaths, applySeamBand]);

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
      {/* Selection pulse (map2_4): opacity swings min→max→min on one
          overlay element; prefers-reduced-motion freezes it halfway. */}
      <style>{`
        @keyframes pg-map-selected-pulse {
          0%, 100% { opacity: ${rules.selection.pulse_min_opacity}; }
          50% { opacity: ${rules.selection.pulse_max_opacity}; }
        }
        .pg-map-selected-pulse {
          animation: pg-map-selected-pulse ${rules.selection.pulse_period_s}s ease-in-out infinite;
        }
        [data-gesture] .pg-map-selected-pulse {
          animation-play-state: paused;
        }
        @media (prefers-reduced-motion: reduce) {
          .pg-map-selected-pulse {
            animation: none;
            opacity: ${(rules.selection.pulse_min_opacity + rules.selection.pulse_max_opacity) / 2};
          }
        }
      `}</style>
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
          {/* fills — each inherits the land-coloured seam-cover stroke
              from this <g> (map2_13/map2_14): cracks between neighbours
              show land, never the sea underneath; writeView zeroes the
              group width below SEAM_MIN_S where no crack can be seen. */}
          <g
            ref={nodesGRef}
            data-layer="nodes"
            stroke={seamStrokes ? seamColor : undefined}
            strokeWidth={SEAM_STROKE_W}
            /* Faster raster path for the fills (map2_14): their edges
               are re-drawn under the border strokes and the seam cover
               anyway, so the lighter AA is invisible. */
            shapeRendering="optimizeSpeed"
          >
            {nodePaths}
          </g>
          {/* border layer: above the fills, below selection/hover and
              labels — chunked + LOD copies, inert (map2_4, map2_14). */}
          {borderEls}
          {/* labels — font size and halo live on this <g> (imperative,
              follows the in-flight scale every frame); the set itself
              re-evaluates from the committed scale on settle (3.9). */}
          <g ref={labelsGRef} data-layer="labels" pointerEvents="none">
            {labeled.map((node) => (
              <text
                key={node.id}
                x={node.anchor[0]}
                y={node.anchor[1]}
                textAnchor="middle"
                fill={LABEL_TEXT_COLOR}
                stroke={LABEL_HALO_COLOR}
                paintOrder="stroke"
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
                className={
                  mode === 'view' ? 'pg-map-selected-pulse' : undefined
                }
                d={geometry.paths[id] ?? ''}
                fill={colors.hover}
                fillOpacity={
                  mode === 'select'
                    ? rules.selection.picked_opacity
                    : undefined
                }
                vectorEffect="non-scaling-stroke"
              />
            ))}
            <path
              ref={hoverPathRef}
              data-layer="hover"
              fill={colors.hover}
              fillOpacity={rules.hover_fill_opacity}
              stroke={rules.hover_stroke_enabled ? colors.hover : 'none'}
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
