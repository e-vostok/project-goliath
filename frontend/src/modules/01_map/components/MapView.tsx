/**
 * MapView — the SVG map surface (Spec Part 5, gestures per 3.8).
 *
 * Performance contract (1 123 paths, ~1.9 MB geometry):
 * - Layers bottom→top: background rect (inland_water) · `sea_water`
 *   bays path (sea fill, Spec 1.9 step 5a) · `outside` path ·
 *   inactive-world + playable relief images (map2_16, lazy) ·
 *   ONE <g> with all node paths (single delegated mouse handling,
 *   resolved via `data-id`, no per-path listeners) · border chunks ·
 *   state-name inscriptions (map2_7) · labels · overlays.
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
 * Border layer (map2_4, map2_13, map2_14, map2_15): the shared
 * borders from `borders.json` sit between the fills and the labels —
 * thin solid INTERNAL inside one owner (or both free), solid STATE on
 * land borders between owners, thin COAST everywhere a LAND node
 * meets the sea/excluded land/map edge. Only LAND nodes get lines:
 * pairs touching a SEA node and SEA nodes' own coasts are dropped at
 * build time so the sea stays plain (map2_15) — split into an 8×8
 * spatial chunk grid
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
 * свободна | занята: … | морская зона, выбрать нельзя». The capital
 * mark (Issue 15): `capitalId` draws its province with a thick dark
 * outline plus a white star at the label point — a shape, not a colour,
 * so it reads on any fill. `onNodeContextMenu` reports the right-button
 * hit-test (the same `data-id` lookup as the left click); in select
 * mode `contextmenu` is preventDefault'ed over the whole surface where
 * the browser allows it — view mode keeps the default menu untouched.
 * In `view` mode the single inspected province carries the same white
 * fill pulsing between `selection.pulse_min_opacity` and
 * `pulse_max_opacity` (CSS animation; `prefers-reduced-motion` freezes
 * it at the midpoint).
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';

import {
  DRAG_THRESHOLD_PX,
  FOCUS_BBOX_MARGIN,
  GESTURE_SETTLE_MS,
  LABEL_RELAYOUT_MS,
  LABEL_SWEEP_MS,
  EXIT_DROP_CHUNK,
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
import { useRelief } from '../lib/relief';
import { displayName } from '../lib/search';
import { selectTooltipStatus } from '../lib/selection';
import {
  createMeasurer,
  isProvinceZoom,
  LABEL_FONT_FAMILIES,
  labelMostlyInView,
  layoutLabels,
  mergeRendered,
  selectRendered,
  SPINE_DEFAULTS,
  windowCoversView,
  type LabelRect,
  type PlacedLabel,
  type RenderedLabel,
} from '../lib/labels';
import {
  ensureMapFont,
  FONT_LOAD_TIMEOUT_MS,
} from '../lib/fonts';
import {
  collectStates,
  measureMonoAdvance,
  parsePathRings,
  placeStateNames,
  STATE_FONT_FAMILIES,
  type StateNameCacheEntry,
} from '../lib/stateNames';
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
  /** Select mode: id of the capital-marked province (Issue 15). */
  capitalId?: number | null;
  /** Select mode: right-button hit-test — same lookup as the click. */
  onNodeContextMenu?: (id: number | null) => void;
  focus?: MapViewFocus | null;
}

/** Wheel zoom step per notch — pure UI feel, not a balance rule. */
const WHEEL_ZOOM_STEP = 1.25;
/** Capital mark (select mode): the province's dark outline, screen px. */
const CAPITAL_OUTLINE_PX = 3;
/** Capital star: white fill edge in screen px (non-scaling). */
const CAPITAL_STAR_STROKE_PX = 1.2;
/** Star tip radius = this share of the node's smaller bbox side… */
const CAPITAL_STAR_RATIO = 0.24;
/** …but never smaller than this in map units. */
const CAPITAL_STAR_MIN_R = 1.4;

/**
 * Five-point star centred on (cx, cy) in map units — the capital mark's
 * glyph. Geometry, not a font glyph: it renders identically everywhere
 * and needs no bundled face.
 */
function capitalStarPath(cx: number, cy: number, rOuter: number): string {
  const rInner = rOuter * 0.42;
  let d = '';
  for (let i = 0; i < 10; i += 1) {
    const r = i % 2 === 0 ? rOuter : rInner;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    d += `${i === 0 ? 'M' : ' L'} ${(cx + r * Math.cos(a)).toFixed(2)} ${(
      cy +
      r * Math.sin(a)
    ).toFixed(2)}`;
  }
  return `${d} Z`;
}

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
  const labelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverId = useRef<number | null>(null);
  const cursor = useRef<Point>({ x: 0, y: 0 });

  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  const prevViewport = useRef<Size>({ width: 0, height: 0 });
  const [hoverNode, setHoverNode] = useState<MapNodeDTO | null>(null);
  /** Rendered label set (map2_6c): the placed labels inside the current
   *  viewport window plus `exiting` copies fading out. Re-selected on
   *  relayout and by the pan sweep — keyed single-element updates only. */
  const [rendered, setRendered] = useState<RenderedLabel[]>([]);
  const renderedRef = useRef<RenderedLabel[]>([]);
  /** Full layout of the last committed scale — pan-independent. */
  const placedRef = useRef<PlacedLabel[]>([]);
  /** Scaled-map-space rect the rendered set covers (±½ screen). */
  const coverageRef = useRef<LabelRect | null>(null);
  /** label id → its <text> element (for imperative visibility writes). */
  const labelEls = useRef(new Map<number, SVGTextElement>());
  /** label id → last WRITTEN data-off state; writes happen only on a
   *  flip so the transition is set only for state changes (map2_6c). */
  const visState = useRef(new Map<number, boolean>());
  const lastLabelSweep = useRef(0);
  const exitSeq = useRef(0);
  /** The two label kind groups — LAND and SEA fade against each other
   *  as ONE element each on a zoom-threshold crossing (map2_21)
   *  instead of per-label exits. */
  const labelKindEls = useRef<{ LAND?: SVGGElement; SEA?: SVGGElement }>(
    {},
  );
  /** True while a wheel-zoom gesture is in flight (settle window
   *  included): the rendered set is frozen — re-selecting it every
   *  sweep under a moving scale is what churned ~9k mounts (map2_21). */
  const zoomGesture = useRef(false);
  /** Kind the current `placed` set was laid out for — a mid-gesture
   *  change means the wheel crossed `province_zoom_ratio` and the
   *  incoming kind must be laid out exactly once (map2_21). */
  const placedKind = useRef<'LAND' | 'SEA' | null>(null);
  const relayoutRef = useRef<() => void>(() => {});
  /** Scale of the last settled gesture — the state-name layer derives
   *  its min_px/max_px/visibility writes from it (map2_7). */
  const [committedScale, setCommittedScale] = useState(0);
  /** Bumped when the bundled fonts finish loading — re-measures the
   *  real monospace advance and re-places state names once. */
  const [fontEpoch, setFontEpoch] = useState(0);
  /** Per-state placement cache (map2_7): an ownership change recomputes
   *  only the states whose signature moved. */
  const stateNameCache = useRef(new Map<string, StateNameCacheEntry>());

  const nodesById = useMemo(
    () => new Map(manifest.nodes.map((n) => [n.id, n])),
    [manifest],
  );
  const owners = useMemo(
    () => buildOwnerMap(props.state ?? null, nodesById),
    [props.state, nodesById],
  );

  // Relief underlay (map2_16): {inactive, playable} nulls until the
  // images arrive — every other layer renders exactly as before while
  // they load and forever when disabled or failed.
  const relief = useRelief(rules.relief);

  /* ---------------------------------------------------- label layout */

  // Bundled label font (map2_6): one measurer per family, measuring the
  // real font once it has loaded (document.fonts.ready triggers one
  // extra relayout below; until then the canvas falls back to the
  // system font and the layout is corrected on arrival).
  // Bundled label faces (map2_21): one registry — province names use
  // labels.font, sea names labels.sea_font (defaulting to the same
  // face); each stack already ends with its generic family, so a
  // missing bundle degrades to system mono/sans, never serif.
  const fontSpec = LABEL_FONT_FAMILIES[rules.labels.font];
  const seaFontSpec =
    LABEL_FONT_FAMILIES[
      rules.labels.sea_font ?? SPINE_DEFAULTS.sea_font
    ];
  const measurer = useMemo(
    () => createMeasurer(fontSpec.family),
    // fontEpoch: re-create (fresh width cache) once the bundled face
    // really loads — the layout then measures the real face, not the
    // generic fallback it was built with (map2_21).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fontSpec.family, fontEpoch],
  );
  const seaMeasurer = useMemo(
    () =>
      seaFontSpec.family === fontSpec.family
        ? measurer
        : createMeasurer(seaFontSpec.family),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [seaFontSpec.family, fontSpec.family, measurer, fontEpoch],
  );

  /** Fade duration for label appear/disappear (map2_6c):
   *  labels.fade_ms, forced to 0 under prefers-reduced-motion. */
  const fadeMs = useCallback(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
        ? 0
        : rules.labels.fade_ms,
    [rules.labels.fade_ms],
  );

  /** Camera top scale (the zoom clamp): minScale × zoom_max. */
  const maxScale = useCallback(
    () => minScale(rules.frame, viewport) * rules.zoom_max,
    [rules.frame, rules.zoom_max, viewport],
  );

  /* -------------------------------------------- state names (map2_7) */

  // One fitted inscription per state territory, in MAP units: the
  // placement is recomputed only when ownership, the font, the config
  // or the manifest changes — a pan or a zoom re-derives nothing (the
  // <text> elements ride the world transform; only the min_px/max_px
  // screen clamp and the maximum-zoom gate follow the settled scale).
  const stateFontSpec = STATE_FONT_FAMILIES[rules.states.font];
  const stateAdvanceEm = useMemo(
    () => measureMonoAdvance(stateFontSpec.family),
    // fontEpoch: re-measure once document.fonts delivers the real face.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stateFontSpec.family, fontEpoch],
  );
  const ringsById = useMemo(() => {
    const map = new Map<number, Point[][]>();
    for (const node of manifest.nodes) {
      if (node.kind === 'LAND') {
        map.set(node.id, parsePathRings(geometry.paths[node.id] ?? ''));
      }
    }
    return map;
  }, [manifest.nodes, geometry.paths]);
  /** Map-unit floor of the font size: below states.min_px even at the
   *  TOP of the zoom range the inscription can never be readable, so
   *  the placement skips it outright. Depends on the fit scale — part
   *  of the placement signature below (a resize re-fits once, exactly
   *  like a config change; never during a gesture). */
  const stateFontFloor =
    viewport.width > 0
      ? rules.states.min_px / Math.max(maxScale(), 1e-9)
      : 0;
  const stateNames = useMemo(() => {
    // No viewport yet → no scale → nothing to place (the cache stays
    // empty until the first sized pass writes entries under the real
    // floor).
    const specs =
      viewport.width > 0 ? collectStates(props.state ?? null, nodesById) : [];
    const fingerprint = `${JSON.stringify(rules.states)}|${stateAdvanceEm.toFixed(4)}|${stateFontFloor.toFixed(4)}`;
    const result = placeStateNames(specs, fingerprint, {
      nodesById,
      edges: manifest.edges,
      ringsById,
      advanceEm: stateAdvanceEm,
      rules: rules.states,
      minFontSize: stateFontFloor,
      cache: stateNameCache.current,
    });
    stateNameCache.current = result.cache;
    return result.names;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    props.state,
    viewport.width,
    nodesById,
    manifest.edges,
    ringsById,
    rules.states,
    stateAdvanceEm,
    stateFontFloor,
  ]);
  // Per-settled-scale resolution: the map-unit size becomes screen px
  // under the current zoom — below min_px the inscription is off, above
  // max_px its font size is capped (the box stays inside the state).
  const stateNameRows = useMemo(
    () =>
      stateNames.map((label) => ({
        label,
        hidden:
          !(committedScale > 0) ||
          label.fontSize * committedScale < rules.states.min_px,
        fontSize:
          committedScale > 0
            ? Math.min(label.fontSize, rules.states.max_px / committedScale)
            : label.fontSize,
      })),
    [stateNames, committedScale, rules.states],
  );
  // Mirror image of the province names: visible at every zoom BELOW
  // the province-name threshold, gone at the maximum zoom.
  const stateNamesOff =
    committedScale > 0 &&
    isProvinceZoom(committedScale, maxScale(), rules.labels);

  // Imperative visibility writer (map2_6c): province labels at the
  // maximum zoom show only while most of their province is in view;
  // exiting copies stay off so they can fade out; everything else is
  // on. `data-off` is written only when the desired state differs from
  // the last written one — no write, no transition, for a label that
  // merely moved.
  const applyLabelVisibility = useCallback(() => {
    const v = viewRef.current;
    if (v === null || viewport.width <= 0) {
      return;
    }
    const atMax = isProvinceZoom(v.s, maxScale(), rules.labels);
    // map2_21: exiting copies whose kind group is already faded out are
    // invisible either way — writing data-off on each is ~450 attribute
    // writes burned on the crossing frame for nothing.
    const groupOff = { LAND: false, SEA: false };
    for (const kind of ['LAND', 'SEA'] as const) {
      groupOff[kind] =
        labelKindEls.current[kind]?.hasAttribute('data-off') === true;
    }
    for (const l of renderedRef.current) {
      const el = labelEls.current.get(l.id);
      if (!el) {
        continue;
      }
      // Ghost copies are display:none — a visibility write on each is
      // a wasted attribute on the crossing frame (map2_21).
      if (
        l.ghost === true ||
        (l.exiting !== undefined && groupOff[l.kind])
      ) {
        continue;
      }
      const off =
        l.exiting !== undefined ||
        (atMax && l.kind === 'LAND' && !labelMostlyInView(l, v, viewport));
      if (visState.current.get(l.id) !== off) {
        visState.current.set(l.id, off);
        if (off) {
          el.setAttribute('data-off', '');
        } else {
          el.removeAttribute('data-off');
        }
      }
    }
  }, [viewport, maxScale, rules.labels]);

  // Reconciler for the rendered set: the caller computes `items`
  // (selectRendered) at any pan position; mergeRendered keeps leaving
  // onscreen labels as `exiting` copies to fade out and drops offscreen
  // ones outright. `stamp` tags each exiting batch for its timeout.
  const commitRendered = useCallback(
    (items: PlacedLabel[], v: ViewTransform) => {
      setRendered((prev) => {
        // map2_21: on a LAND↔SEA set switch the outgoing labels stay
        // mounted under their own kind group so the group fade-out has
        // something to show — mergeRendered already keeps onscreen
        // leavers as `exiting` copies for exactly that.
        const merged = mergeRendered(
          prev,
          items,
          v,
          viewport,
          ++exitSeq.current,
          fadeMs(),
        );
        if (
          merged.length === prev.length &&
          merged.every((l, i) => l === prev[i])
        ) {
          return prev;
        }
        return merged;
      });
    },
    [viewport, fadeMs],
  );

  /** Kind-of-set the live scale wants: province names exist only at
   *  the maximum zoom, sea names only below it (map2_6c). */
  const liveLabelKind = useCallback(
    (s: number) =>
      isProvinceZoom(s, maxScale(), rules.labels) ? 'LAND' : 'SEA',
    [maxScale, rules.labels],
  );

  /** The LAND↔SEA crossfade as ONE opacity animation of two groups
   *  (map2_21): each kind group is faded out when the live scale wants
   *  the other kind — the outgoing set fades under its own group while
   *  the incoming group fades back in once its set is mounted. A
   *  single attribute write per group per crossing replaces up to 600
   *  individual opacity transitions racing the transform; a group with
   *  no mounted set of its kind stays hidden (`visibility:hidden`
   *  stops its repaint entirely). */
  const applyKindFade = useCallback(
    (v: ViewTransform) => {
      const live = liveLabelKind(v.s);
      const mounted = { LAND: false, SEA: false };
      for (const l of renderedRef.current) {
        if (l.exiting === undefined) {
          mounted[l.kind] = true;
          if (mounted.LAND && mounted.SEA) {
            break;
          }
        }
      }
      for (const kind of ['LAND', 'SEA'] as const) {
        const g = labelKindEls.current[kind];
        if (g === undefined) {
          continue;
        }
        const off = kind !== live || !mounted[kind];
        if (g.hasAttribute('data-off') !== off) {
          g.toggleAttribute('data-off', off);
        }
      }
    },
    [liveLabelKind],
  );

  // One layout per committed scale: positions/sizes live in map units,
  // so the labels <g> rides the world transform and a pan costs
  // nothing. The layout covers ALL nodes of the zoom-gated kind
  // (map2_6c) — the rendered subset then follows the viewport.
  const relayout = useCallback(() => {
    const v = viewRef.current;
    if (v === null || viewport.width <= 0 || viewport.height <= 0) {
      return;
    }
    const t0 = performance.now();
    // Only one kind is laid out per call (map2_6c kind gate) — the
    // measurer follows it: land face at the maximum zoom, sea face
    // below (map2_21).
    const all = layoutLabels(
      manifest.nodes,
      v.s,
      rules.labels,
      isProvinceZoom(v.s, maxScale(), rules.labels)
        ? measurer
        : seaMeasurer,
      maxScale(),
    );
    // map2_21: the benchmark counts layout runs/cost through this
    // optional hook — absent in normal use, zero overhead.
    (
      globalThis as unknown as {
        __pgLabelStats?: { scale: number; ms: number; placed: number }[];
      }
    ).__pgLabelStats?.push({
      scale: v.s,
      ms: performance.now() - t0,
      placed: all.length,
    });
    setCommittedScale(v.s);
    placedRef.current = all;
    placedKind.current = liveLabelKind(v.s);
    const { items, window } = selectRendered(all, v, viewport);
    coverageRef.current = window;
    commitRendered(items, v);
  }, [
    manifest.nodes,
    rules.labels,
    measurer,
    seaMeasurer,
    viewport,
    maxScale,
    liveLabelKind,
    commitRendered,
  ]);
  relayoutRef.current = relayout;

  // Zoom storms (wheel bursts, resize streams) collapse into one
  // layout after the last step (map2_6, Spec 3.9). map2_21: while a
  // wheel gesture is in flight NO layout is scheduled at all — a
  // mid-gesture ~60 ms layout of the whole node set is what produced
  // the >33 ms frames; the settle callback runs it exactly once.
  const scheduleRelayout = useCallback(() => {
    if (zoomGesture.current) {
      return;
    }
    if (labelTimer.current !== null) {
      clearTimeout(labelTimer.current);
    }
    labelTimer.current = setTimeout(() => {
      labelTimer.current = null;
      // A timer armed just before the gesture started must not fire
      // inside it either — the settle callback owns the layout.
      if (!zoomGesture.current) {
        relayoutRef.current();
      }
    }, LABEL_RELAYOUT_MS);
  }, []);

  /** Stable ref for label <text> elements: mounts start hidden
   *  (data-off) so the post-commit visibility pass fades in only the
   *  visible ones; unmounts are pruned from labelEls in the effect. */
  const labelElRef = useCallback((el: SVGTextElement | null) => {
    if (el === null) {
      return;
    }
    const id = Number(el.getAttribute('data-label'));
    labelEls.current.set(id, el);
    // Mounts under a group that is itself faded out skip the per-label
    // off-state — the kind group's own fade-in carries them as ONE
    // animation (map2_21), not ~450 individual transitions.
    const off = !el
      .closest('g[data-labelkind]')
      ?.hasAttribute('data-off');
    if (off) {
      el.setAttribute('data-off', '');
    }
    visState.current.set(id, off);
  }, []);

  /** Pan sweep (map2_6c), at most every LABEL_SWEEP_MS: re-selects the
   *  rendered set once the quarter-screen lead is gone (labels must
   *  exist before their province comes into view) and re-evaluates the
   *  «mostly in view» fade — writes only labels whose state changed.
   *  map2_21: during a wheel-zoom gesture the re-selection is skipped —
   *  the set rides the world transform, edge labels that only became
   *  eligible mid-zoom wait for the settle sweep. */
  const labelsTick = useCallback(
    (force = false) => {
      const v = viewRef.current;
      if (v === null || viewport.width <= 0) {
        return;
      }
      const now = performance.now();
      if (!force && now - lastLabelSweep.current < LABEL_SWEEP_MS) {
        return;
      }
      lastLabelSweep.current = now;
      const cov = coverageRef.current;
      if (
        cov === null ||
        (!zoomGesture.current && !windowCoversView(cov, v, viewport))
      ) {
        const sel = selectRendered(placedRef.current, v, viewport);
        coverageRef.current = sel.window;
        commitRendered(sel.items, v);
      }
      applyLabelVisibility();
    },
    [viewport, commitRendered, applyLabelVisibility],
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
        // Only paths that inherit the group stroke (LAND fills); a
        // stroke="none" path never carries the seam cover (map2_15).
        for (const p of g.querySelectorAll('path[data-id]:not([stroke="none"])')) {
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
  // frame) plus, only when the scale actually moved, the border LOD
  // pick — a few attribute writes per frame, never a React commit.
  // The label SET re-evaluates only on the debounced relayout
  // (Spec 3.9, map2_6): its font sizes live in map units so the texts
  // simply scale with the world mid-gesture.
  const writeView = useCallback(
    (v: ViewTransform) => {
      worldRef.current?.setAttribute(
        'transform',
        `translate(${v.tx} ${v.ty}) scale(${v.s})`,
      );
      applyKindFade(v);
      // Threshold crossed inside a wheel gesture: the incoming kind is
      // laid out exactly ONCE here (map2_21) so the group crossfade has
      // its set — the only mid-gesture layout, never both kinds.
      if (
        zoomGesture.current &&
        placedKind.current !== null &&
        placedKind.current !== liveLabelKind(v.s)
      ) {
        relayoutRef.current();
      }
      labelsTick();
    if (v.s === scaledS.current) {
      return;
    }
    scaledS.current = v.s;
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
    },
    [applyKindFade, applySeamBand, labelsTick, liveLabelKind],
  );

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
      scheduleRelayout();
    },
    [writeView, scheduleRelayout],
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
      const wasZoom = zoomGesture.current;
      zoomGesture.current = false;
      setGestureFlag(false);
      if (labelTimer.current !== null) {
        clearTimeout(labelTimer.current);
        labelTimer.current = null;
      }
      // Wheel-zoom settle: the one deferred layout (map2_21 — none ran
      // mid-gesture except a single threshold-crossing build) re-fits
      // the set for the new scale; a pan settle only needs the final
      // sweep catching any viewport the throttled sweeps skipped.
      if (wasZoom) {
        relayoutRef.current();
      }
      labelsTick(true);
    }, GESTURE_SETTLE_MS);
  }, [setGestureFlag, labelsTick]);

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
      zoomGesture.current = true;
      viewRef.current = clamped(zoomAt(viewRef.current, c, nextScale));
      applyTransform();
      scheduleRelayout();
      endGestureSoon();
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [bounds, clamped, applyTransform, beginGesture, endGestureSoon, scheduleRelayout]);

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

  // Right button (Issue 15, select mode only): swallow the browser menu
  // over the whole map surface and report the hit node — the same
  // `data-id` lookup the settled left click uses (`nodeIdFrom`). View
  // mode is untouched: no preventDefault, no callback.
  const onContextMenu = useCallback(
    (e: React.MouseEvent) => {
      if (mode !== 'select') {
        return;
      }
      e.preventDefault();
      props.onNodeContextMenu?.(nodeIdFrom(e.target));
    },
    [mode, props.onNodeContextMenu],
  );

  // Label relayout triggers (map2_6): once when the layout inputs
  // change (mount, new manifest/rules, font swap, resize) and once
  // after the bundled font has actually loaded — the canvas then
  // measures the real face instead of the fallback.
  useEffect(() => {
    scheduleRelayout();
  }, [relayout, scheduleRelayout]);

  // Post-commit label pass (map2_6c): mirror the rendered set for the
  // imperative writer, drop refs of unmounted texts, apply the
  // «mostly in view» visibility (only changed labels are written), and
  // unmount exiting copies once their fade has run.
  useEffect(() => {
    renderedRef.current = rendered;
    // A fresh set of the live kind lifts the group fade (map2_21) —
    // applyKindFade compares kinds itself, so a stale set stays hidden.
    if (viewRef.current !== null) {
      applyKindFade(viewRef.current);
    }
    applyLabelVisibility();
    const alive = new Set(rendered.map((l) => l.id));
    for (const id of labelEls.current.keys()) {
      if (!alive.has(id)) {
        labelEls.current.delete(id);
        visState.current.delete(id);
      }
    }
    const stamps = new Set(
      rendered
        .filter((l) => l.exiting !== undefined)
        .map((l) => l.exiting as number),
    );
    if (stamps.size === 0) {
      return;
    }
    // map2_21: a kind switch leaves up to ~500 exiting copies — dropping
    // them in ONE commit produced a >33 ms frame mid-gesture. Ghost
    // copies are display:none and the faded-out group is
    // visibility:hidden, so their detach is pure DOM work with no
    // raster — all ghosts go in the first tick; the visible exits then
    // drain at EXIT_DROP_CHUNK per tick across the next frames.
    const drop = () =>
      setRendered((list) => {
        const tagged = list.filter(
          (l) => l.exiting !== undefined && stamps.has(l.exiting),
        );
        const visible = tagged.filter((l) => l.ghost !== true);
        if (visible.length <= EXIT_DROP_CHUNK) {
          return list.filter(
            (l) =>
              l.exiting === undefined || !stamps.has(l.exiting as number),
          );
        }
        const keep = new Set(
          visible.slice(EXIT_DROP_CHUNK).map((l) => l.id),
        );
        return list.filter(
          (l) =>
            l.exiting === undefined ||
            !stamps.has(l.exiting as number) ||
            (l.ghost !== true && keep.has(l.id)),
        );
      });
    const ms = fadeMs();
    if (ms <= 0) {
      drop();
      return;
    }
    const t = setTimeout(drop, ms);
    return () => clearTimeout(t);
  }, [rendered, applyLabelVisibility, applyKindFade, fadeMs]);

  // Bundled-face loading (map2_21): probe every face the config asks
  // for with real Cyrillic text. A face that is not usable within
  // FONT_LOAD_TIMEOUT_MS logs ONE warning — the stack's generic tail
  // keeps drawing meanwhile (never a serif); when a face does arrive
  // (loadingdone), the layout and the mono advance re-run once.
  useEffect(() => {
    if (typeof document === 'undefined' || document.fonts === undefined) {
      return;
    }
    const fonts = document.fonts;
    let cancelled = false;
    const faces = new Set([
      fontSpec.face,
      seaFontSpec.face,
      stateFontSpec.face,
    ]);
    const relayout = () => {
      if (cancelled) {
        return;
      }
      // The epoch bump alone drives the one re-layout: new measurers →
      // new `relayout` identity → the debounced scheduler runs it (or
      // the settle does, if a wheel gesture is in flight — a ~45 ms
      // layout inside a wheel storm is what map2_21 removes). Calling
      // relayoutRef here too would do the same layout twice.
      setFontEpoch((e) => e + 1);
    };
    for (const face of faces) {
      ensureMapFont(face).then((ok) => {
        if (cancelled) {
          return;
        }
        if (!ok) {
          console.warn(
            `[01_map] bundled font ${face} did not load within ${FONT_LOAD_TIMEOUT_MS} ms — generic fallback stays`,
          );
        }
        relayout();
      });
    }
    // A face that missed the timeout but arrived later still triggers
    // exactly one re-measure + relayout.
    fonts.addEventListener('loadingdone', relayout);
    return () => {
      cancelled = true;
      fonts.removeEventListener('loadingdone', relayout);
    };
  }, [fontSpec.face, seaFontSpec.face, stateFontSpec.face]);

  useEffect(
    () => () => {
      if (frame.current) {
        cancelAnimationFrame(frame.current);
      }
      if (settleTimer.current) {
        clearTimeout(settleTimer.current);
      }
      if (labelTimer.current) {
        clearTimeout(labelTimer.current);
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
  // LAND ids for the border build — sea zones get no lines (map2_15).
  const landIds = useMemo(
    () =>
      new Set(
        manifest.nodes
          .filter((n) => n.kind === 'LAND')
          .map((n) => n.id),
      ),
    [manifest.nodes],
  );
  const layerRef = useRef<BorderLayer | null>(null);
  const borderLayer = useMemo(() => {
    let next: BorderLayer | null = null;
    if (props.borders) {
      next =
        layerRef.current !== null &&
        layerRef.current.borders === props.borders
          ? reclassifyBorderLayer(layerRef.current, owners)
          : buildBorderLayer(
              props.borders,
              owners,
              manifest.view_box,
              landIds,
            );
    }
    layerRef.current = next;
    return next;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.borders, owners, manifest.view_box, landIds]);
  // Legacy per-node strokes survive only as the borders-failed fallback.
  const legacyStrokes =
    borderLayer === null && props.bordersFailed === true;

  // Seam cover (map2_13) as a per-node stroke (map2_14): every LAND
  // fill carries a hairline of `land_underlay` in world units, so a
  // crack between neighbours shows land colour — the same pixels the
  // old under-stroke covered, but rasterised inside each node's own
  // bounding box, which the browser culls far better than the old
  // compound seam paths. SEA fills opt out (map2_15): the sea must
  // look like plain sea — no grey rim between sea zones or along the
  // excluded zone — and a crack between sea fills shows the
  // sea-coloured background anyway.
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
          // where every covered crack would be subpixel anyway. SEA
          // nodes opt out (map2_15): a grey rim between sea zones or
          // along the excluded zone must not appear.
          stroke={
            seamStrokes
              ? node.kind === 'LAND'
                ? undefined
                : 'none'
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
  // The fills split by kind so the relief multiply blend (map2_5) can
  // apply to land only — SEA fills keep the plain sea colour.
  const landPaths = useMemo(
    () =>
      nodePaths.filter(
        (_, i) => manifest.nodes[i].kind === 'LAND',
      ),
    [nodePaths, manifest.nodes],
  );
  const seaPaths = useMemo(
    () =>
      nodePaths.filter((_, i) => manifest.nodes[i].kind === 'SEA'),
    [nodePaths, manifest.nodes],
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
  const capitalNode =
    mode === 'select' && props.capitalId != null
      ? nodesById.get(props.capitalId)
      : undefined;
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
      onContextMenu={onContextMenu}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        cursor: cursorStyle,
        userSelect: 'none',
        // Anything beyond view_box (pan margin, oversized window) is
        // land/unknown sea outside the playable field — or plain sea
        // once the world relief is on: it supplies every land pixel
        // the camera can reach (map2_16).
        background: relief.inactive ? colors.sea : colors.outside,
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
        /* relief fade-in (map2_5): the raster mounts only after it is
           decoded; a short opacity ramp avoids a hard pop. */
        @keyframes pg-relief-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .pg-relief-in {
          animation: pg-relief-in 400ms ease-out;
        }
        @media (prefers-reduced-motion: reduce) {
          .pg-relief-in {
            animation: none;
          }
        }
        /* Label visibility transition (map2_6c): data-off hides a label
           — opacity fades out, visibility flips at the end of the fade;
           on removal the label reappears instantly and fades in. The
           duration comes from --pg-label-fade (labels.fade_ms, 0 under
           prefers-reduced-motion). */
        .pg-map-label {
          transition: opacity var(--pg-label-fade) ease, visibility 0s;
        }
        .pg-map-label[data-off] {
          opacity: 0;
          visibility: hidden;
          transition: opacity var(--pg-label-fade) ease,
            visibility 0s linear var(--pg-label-fade);
        }
        /* State-name layer (map2_7): same data-off fade as labels —
           the group fades out at the maximum zoom, a single
           inscription fades under states.min_px. */
        .pg-map-state {
          transition: opacity var(--pg-label-fade) ease, visibility 0s;
        }
        .pg-map-state[data-off] {
          opacity: 0;
          visibility: hidden;
          transition: opacity var(--pg-label-fade) ease,
            visibility 0s linear var(--pg-label-fade);
        }
        /* Kind-group fade (map2_21): crossing labels.province_zoom_ratio
           swaps province names for sea names — ONE opacity transition on
           each of the two kind groups instead of a transition per <text>;
           visibility:hidden at the end of the fade stops the group's
           repaint entirely while the wrong-kind set stays mounted
           underneath (it also covers mounts that skipped their own
           data-off because the group was already off). */
        g[data-labelkind] {
          transition: opacity var(--pg-label-fade) ease, visibility 0s;
        }
        g[data-labelkind][data-off] {
          opacity: 0;
          visibility: hidden;
          transition: opacity var(--pg-label-fade) ease,
            visibility 0s linear var(--pg-label-fade);
        }
        /* Bundled label fonts (map2_6): self-hosted WOFF2 subsets
           (Latin + Cyrillic + basic punctuation, SIL OFL — licence
           files alongside), swapped in with font-display: swap. */
        @font-face {
          font-family: 'Fira Sans Condensed';
          src: url('/assets/fonts/firasanscondensed-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'Fira Sans Condensed';
          src: url('/assets/fonts/firasanscondensed-medium.woff2') format('woff2');
          font-weight: 500; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'Fira Sans Condensed';
          src: url('/assets/fonts/firasanscondensed-italic.woff2') format('woff2');
          font-weight: 400; font-style: italic; font-display: swap;
        }
        @font-face {
          font-family: 'Fira Sans Condensed';
          src: url('/assets/fonts/firasanscondensed-mediumitalic.woff2') format('woff2');
          font-weight: 500; font-style: italic; font-display: swap;
        }
        @font-face {
          font-family: 'PT Sans Narrow';
          src: url('/assets/fonts/ptsansnarrow-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'PT Sans Narrow';
          src: url('/assets/fonts/ptsansnarrow-bold.woff2') format('woff2');
          font-weight: 700; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'Roboto Condensed';
          src: url('/assets/fonts/robotocondensed-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'Roboto Condensed';
          src: url('/assets/fonts/robotocondensed-medium.woff2') format('woff2');
          font-weight: 500; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'Roboto Condensed';
          src: url('/assets/fonts/robotocondensed-italic.woff2') format('woff2');
          font-weight: 400; font-style: italic; font-display: swap;
        }
        @font-face {
          font-family: 'Roboto Condensed';
          src: url('/assets/fonts/robotocondensed-mediumitalic.woff2') format('woff2');
          font-weight: 500; font-style: italic; font-display: swap;
        }
        /* Terminal monospace faces (map2_7/map2_21): same self-hosted
           OFL WOFF2 subsets — Latin + Cyrillic + digits + punctuation. */
        @font-face {
          font-family: 'Share Tech Mono';
          src: url('/assets/fonts/sharetechmono-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'IBM Plex Mono';
          src: url('/assets/fonts/ibmplexmono-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
        }
        @font-face {
          font-family: 'PT Mono';
          src: url('/assets/fonts/ptmono-regular.woff2') format('woff2');
          font-weight: 400; font-style: normal; font-display: swap;
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
          {/* The outside path carries the inactive zone: classic
              `colors.outside` while the world relief is off/absent, and
              the plain sea colour once it is on — the dark world image
              then supplies every land pixel (its own water stays
              transparent); it is never a flat grey over the relief. */}
          <path
            d={geometry.outside}
            fill={relief.inactive ? colors.sea : colors.outside}
          />
          {/* relief (map2_16): two baked rasters, lazy — they mount
              only once decoded, so the map never blocks or flickers
              waiting for them; both move with the same world transform
              as every other layer (map2_14). Alpha is baked into the
              images: no runtime clip/mask, no fade or feather — the
              visible relief edge IS the province / world-land shape. */}
          {relief.inactive && (
            <image
              data-layer="relief-inactive"
              href={relief.inactive.file}
              x={relief.inactive.rect[0]}
              y={relief.inactive.rect[1]}
              width={relief.inactive.rect[2]}
              height={relief.inactive.rect[3]}
              preserveAspectRatio="none"
              pointerEvents="none"
              className="pg-relief-in"
            />
          )}
          {relief.playable && (
            <image
              data-layer="relief-playable"
              href={relief.playable.file}
              x={relief.playable.rect[0]}
              y={relief.playable.rect[1]}
              width={relief.playable.rect[2]}
              height={relief.playable.rect[3]}
              preserveAspectRatio="none"
              pointerEvents="none"
              className="pg-relief-in"
            />
          )}
          {/* fills — SEA first (plain sea colour, never shaded), then
              LAND; when the relief is on a copy of the playable raster
              in `multiply` sits right above them so its shading shows
              through the palette (map2_16). Each land fill
              inherits the land-coloured seam-cover stroke from this <g>
              (map2_13/map2_14): cracks between neighbours show land,
              never the sea underneath; writeView zeroes the group width
              below SEAM_MIN_S where no crack can be seen. Default
              anti-aliased rendering (map2_16): the seam cover exists
              for the cracks it would reveal. */}
          <g data-layer="sea-nodes">{seaPaths}</g>
          <g
            ref={nodesGRef}
            data-layer="nodes"
            stroke={seamStrokes ? seamColor : undefined}
            strokeWidth={SEAM_STROKE_W}
          >
            {landPaths}
          </g>
          {/* playable multiply (map2_16): a second copy of the playable
              raster above the fills — multiply commutes, so the fills
              get the shading while the element being blended stays a
              single cached texture (a <g> of fills would re-rasterise
              ~800 paths every gesture frame). Its baked alpha already
              limits shading to LAND provinces — no runtime mask. */}
          {relief.playable && (
            <image
              data-layer="relief-mult"
              href={relief.playable.file}
              x={relief.playable.rect[0]}
              y={relief.playable.rect[1]}
              width={relief.playable.rect[2]}
              height={relief.playable.rect[3]}
              preserveAspectRatio="none"
              pointerEvents="none"
              className="pg-relief-in"
              style={{
                mixBlendMode: 'multiply',
                opacity: rules.relief.strength_playable,
              }}
            />
          )}
          {/* border layer: above the fills, below selection/hover and
              labels — chunked + LOD copies, inert (map2_4, map2_14). */}
          {borderEls}
          {/* state names (map2_7): one fitted inscription per state
              territory — above the fills and internal borders, below
              the labels and the hover/selection overlays, and never an
              event target. Map-unit geometry + font size: a pan/zoom
              moves and scales it with the world; the settled scale only
              clamps screen size to states.min_px..max_px and gates the
              whole layer at the maximum zoom (fade = labels.fade_ms —
              the crossfade mirror of the province names). */}
          <g
            data-layer="state-names"
            pointerEvents="none"
            className="pg-map-state"
            {...(stateNamesOff ? { 'data-off': '' } : {})}
            style={
              { '--pg-label-fade': `${fadeMs()}ms` } as CSSProperties
            }
          >
            <g opacity={rules.states.opacity}>
              <defs>
                {stateNameRows.map(({ label: l }) => (
                  <path
                    key={`arc-${l.key}`}
                    id={`pg-state-arc-${l.key.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                    d={`M ${l.path.x0} ${l.path.y0} Q ${l.path.cx} ${l.path.cy} ${l.path.x1} ${l.path.y1}`}
                    fill="none"
                  />
                ))}
              </defs>
              {stateNameRows.map(({ label: l, hidden, fontSize }) => (
                <text
                  key={l.key}
                  data-state={l.stateKey}
                  className="pg-map-state"
                  {...(hidden ? { 'data-off': '' } : {})}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={fontSize}
                  fontFamily={stateFontSpec.family}
                  letterSpacing={`${l.letterSpacingEm}em`}
                  fill={l.color}
                >
                  <textPath
                    href={`#pg-state-arc-${l.key.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                    startOffset="50%"
                  >
                    {l.text}
                  </textPath>
                </text>
              ))}
            </g>
          </g>
          {/* labels (map2_6/map2_6c): the rendered subset of the last
              layout — placed for all nodes of the zoom-gated kind
              (provinces only at the maximum zoom, seas only below),
              then kept to the viewport ±½ screen by the pan sweep.
              Positions and font sizes are map units, so the group rides
              the world transform; a pan adds/removes single <text>
              elements only (≤100 ms sweeps, keyed merges). Visibility is
              imperative `data-off` writes — opacity/visibility fade via
              the .pg-map-label transition above. Halo = thin dark glyph
              outline via stroke + paint-order, no filters/shadows. Sea
              labels are italic (or skewX-slanted when the family has no
              italic cut) with letter spacing and their own colour.
              map2_20: a name with a `path` rides its spine via
              <textPath> exactly like the state names; the whole-element
              opacity sits on the <text> itself so glyphs and halo
              composite together (an opacity<1 element renders to one
              surface either way — a wrapping <g> would only add ~150
              DOM nodes to the per-frame SVG repaint). */}
          <g
            data-layer="labels"
            pointerEvents="none"
            style={{ '--pg-label-fade': `${fadeMs()}ms` } as CSSProperties}
          >
            <defs>
              {rendered.map((l) =>
                l.path === null ? null : (
                  <path
                    key={`arc-${l.id}`}
                    id={`pg-label-arc-${l.id}`}
                    d={`M ${l.path.x0} ${l.path.y0} Q ${l.path.cx} ${l.path.cy} ${l.path.x1} ${l.path.y1}`}
                    fill="none"
                  />
                ),
              )}
            </defs>
            {(['LAND', 'SEA'] as const).map((kind) => (
              // map2_21: each kind lives in its own group — the
              // LAND↔SEA crossfade is ONE opacity animation of the two
              // groups (`data-off` is written imperatively).
              <g
                key={kind}
                ref={(el) => {
                  if (el !== null) {
                    labelKindEls.current[kind] = el;
                  }
                }}
                data-labelkind={kind}
              >
                {rendered.map((l) => {
                  if (l.kind !== kind) {
                    return null;
                  }
              const sea = l.kind === 'SEA';
              const spec = sea ? seaFontSpec : fontSpec;
              const slant = sea && spec.syntheticSlant;
              return (
                <text
                  key={l.id}
                  ref={labelElRef}
                  className="pg-map-label"
                  opacity={l.opacity < 1 ? l.opacity : undefined}
                  display={l.ghost === true ? 'none' : undefined}
                  data-label={l.id}
                  textAnchor="middle"
                  fontSize={l.fontSize}
                  fontFamily={spec.family}
                  fontWeight={sea || spec.mono ? 400 : 500}
                  fontStyle={
                    sea && !spec.syntheticSlant ? 'italic' : undefined
                  }
                  letterSpacing={
                    l.letterSpacingEm !== 0
                      ? `${l.letterSpacingEm}em`
                      : undefined
                  }
                  fill={sea ? rules.labels.sea_color : rules.labels.land_color}
                  stroke={rules.labels.halo_color}
                  strokeWidth={l.haloW}
                  paintOrder="stroke"
                  dominantBaseline={
                    l.lines.length === 1 ? 'central' : undefined
                  }
                  {...(l.path !== null
                    ? slant
                      ? {
                          transform: `translate(${l.x} ${l.y}) skewX(-9) translate(${-l.x} ${-l.y})`,
                        }
                      : {}
                    : slant
                      ? {
                          transform: `translate(${l.x} ${l.y}) skewX(-9)`,
                          x: 0,
                          y: 0,
                        }
                      : { x: l.x, y: l.y })}
                >
                  {l.path !== null ? (
                    <textPath
                      href={`#pg-label-arc-${l.id}`}
                      startOffset="50%"
                    >
                      {l.lines[0]}
                    </textPath>
                  ) : l.lines.length === 1 ? (
                    l.lines[0]
                  ) : (
                    <>
                      <tspan x={slant ? 0 : l.x} dy="-0.25em">
                        {l.lines[0]}
                      </tspan>
                      <tspan x={slant ? 0 : l.x} dy="1.2em">
                        {l.lines[1]}
                      </tspan>
                    </>
                  )}
                </text>
              );
                })}
              </g>
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
            {/* capital mark (Issue 15, select mode): a thick dark
                outline around the province plus a white star at its
                label point — a shape difference, not a colour one, so
                it reads on any fill. pointerEvents stays off via the
                parent group: the right-button hit-test lands on the
                node path underneath, exactly like the left click. */}
            {capitalNode !== undefined && (
              <g data-layer="capital" data-capital={capitalNode.id}>
                <path
                  d={geometry.paths[capitalNode.id] ?? ''}
                  fill="none"
                  stroke={rules.borders.state_color}
                  strokeWidth={CAPITAL_OUTLINE_PX}
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
                <path
                  d={capitalStarPath(
                    capitalNode.label.x,
                    capitalNode.label.y,
                    Math.max(
                      CAPITAL_STAR_MIN_R,
                      Math.min(
                        capitalNode.bbox[2] - capitalNode.bbox[0],
                        capitalNode.bbox[3] - capitalNode.bbox[1],
                      ) * CAPITAL_STAR_RATIO,
                    ),
                  )}
                  fill={colors.hover}
                  stroke={rules.borders.state_color}
                  strokeWidth={CAPITAL_STAR_STROKE_PX}
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            )}
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
                    ? hoverOwner.short_name
                    : 'свободна'}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
