/**
 * ProvincePicker — the registration starting-group picker (Spec Part 5,
 * UI Spec 3.3, unit 6b).
 *
 * A shared `Popup` of size L with a FIXED map height: a toolbar row
 * (Search — results only centre/fit the view, they never toggle the
 * selection — the counter «Выбрано N из M · минимум K», the local
 * connectivity indicator and the capital caption), a MapView in
 * `select` mode inside a 520 px block, and below it the fixed-height
 * removable-chips area of the current selection (two chip rows,
 * internal scroll, always rendered — the map above never resizes when
 * chips come and go). «Готово» is enabled while the count is inside
 * [min, max] from GET /nations/rules and — when
 * manifest.rules.require_connected_start is on — the selection is one
 * component over land/strait edges. A selection or capital mark that
 * differs from the initial ones makes the window `dirty`: Esc and the
 * scrim stop closing it («×» and «Отмена» still do).
 *
 * The capital mark (Issue 15): the right mouse button on a SELECTED
 * province toggles it as capital (one at most; another province moves
 * the mark; the same one again clears it; anywhere else does nothing),
 * and every chip carries a small star button doing the same — the
 * visible fallback for hosts that do not let the page suppress the
 * browser menu. Removing the capital province clears the mark. The
 * mark travels home as onDone's third argument (null = none marked).
 *
 * Local checks are advisory (INV-M8): «Готово» first calls
 * POST /map/starting-group/check; a server disagreement or an error
 * keeps the picker open and shows the server's answer. The registration
 * request itself remains the final word.
 *
 * Manifest/geometry/state come through the shared hooks — the payloads
 * are cached per session, so opening the picker after the map screen
 * does not re-download the ~1.9 MB geometry.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Icon16StarAlt } from '@vkontakte/icons';
import {
  Button,
  Caption,
  Chip,
  FormStatus,
  IconButton,
  Search,
  Spinner,
  Text,
} from '@vkontakte/vkui';

import { ApiError } from '../../../shared/api-client';
import { Popup, tokenVar } from '../../../shared/ui';
import { mapApi } from '../api';
import { buildOwnerMap } from '../lib/colors';
import { displayName } from '../lib/search';
import {
  components,
  describeConnectivity,
  fitBBoxOfSelection,
  isSelectable,
  isSelectionValid,
  refusalHint,
  toggle,
  type SelectionLimits,
} from '../lib/selection';
import type { MapNodeDTO } from '../types';
import { useMapBorders } from '../hooks/useMapBorders';
import { useMapGeometry } from '../hooks/useMapGeometry';
import { useMapManifest } from '../hooks/useMapManifest';
import { useMapSearch } from '../hooks/useMapSearch';
import { useMapState } from '../hooks/useMapState';
import { useSession } from '../../00_core/hooks/useAuth';
import { MapView, type MapViewFocus } from './MapView';

/** How long a refusal hint stays visible inside the chips box, ms. */
const HINT_TIMEOUT_MS = 3000;
/** The map block height — fixed, so the window never depends on the
 *  screen height (unit 6b; the VK window height is automatic). */
const MAP_HEIGHT = 520;
/** Reserved chips block: exactly two chip rows (2×32 + 6 gap) plus
 *  padding — fixed, so the map above never resizes (backlog «Дёрганье
 *  карты»). */
const CHIPS_AREA_HEIGHT = 78;

export interface ProvincePickerProps {
  /** Ids already chosen in the form — the picker starts with them. */
  initialSelectedIds?: number[];
  /** The capital mark inside the initial selection; null = none. */
  initialCapitalId?: number | null;
  /** min/max provinces from GET /nations/rules; null while unknown. */
  limits: SelectionLimits;
  /** Success: ordered ids, their display names, the capital (or null). */
  onDone: (
    ids: number[],
    names: Map<number, string>,
    capitalId: number | null,
  ) => void;
  /** Any dismissal (Отмена / Esc / overlay) — the form stays unchanged. */
  onCancel: () => void;
}

export function ProvincePicker({
  initialSelectedIds,
  initialCapitalId,
  limits,
  onDone,
  onCancel,
}: ProvincePickerProps) {
  const { token } = useSession();
  const manifestState = useMapManifest();
  const manifest =
    manifestState.status === 'ready' ? manifestState.manifest : null;
  const geometryState = useMapGeometry(
    manifest?.geometry_version ?? null,
    manifestState.reload,
  );
  const bordersState = useMapBorders(
    manifest?.borders_version ?? null,
    manifestState.reload,
  );
  const mapState = useMapState(manifest?.rules.refresh ?? null);
  const { query, setQuery, results } = useMapSearch(manifest);

  const [selection, setSelection] = useState<number[]>(
    () => initialSelectedIds ?? [],
  );
  // The capital mark lives in the picker; a mark outside the initial
  // selection starts as none (the panel re-validates anyway).
  const [capitalId, setCapitalId] = useState<number | null>(() =>
    initialCapitalId !== null &&
    initialCapitalId !== undefined &&
    (initialSelectedIds ?? []).includes(initialCapitalId)
      ? initialCapitalId
      : null,
  );
  const [hint, setHint] = useState<string | null>(null);
  const [serverMessage, setServerMessage] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [focus, setFocus] = useState<MapViewFocus | null>(null);
  const focusSeq = useRef(0);
  const didInitialFit = useRef(false);

  const nodesById = useMemo(
    () => new Map((manifest?.nodes ?? []).map((n) => [n.id, n])),
    [manifest],
  );
  const owners = useMemo(
    () => buildOwnerMap(mapState.state, nodesById),
    [mapState.state, nodesById],
  );
  const ctx = useMemo(
    () => ({ nodes: nodesById, owners, max: limits.max }),
    [nodesById, owners, limits.max],
  );
  const edges = useMemo(() => manifest?.edges ?? [], [manifest]);
  const componentCount = useMemo(
    () => components(selection, edges).length,
    [selection, edges],
  );
  const connectivityText = describeConnectivity(componentCount);
  const valid =
    manifest !== null &&
    isSelectionValid(selection, manifest.rules, limits, edges);
  const disabledIds = useMemo(
    () =>
      manifest === null
        ? []
        : manifest.nodes
            .filter((node) => isSelectable(node, ctx) !== 'OK')
            .map((node) => node.id),
    [manifest, ctx],
  );

  // First open with an existing selection: fit its bbox once (else the
  // MapView default — the whole playable area — applies anyway).
  useEffect(() => {
    if (manifest === null || didInitialFit.current) {
      return;
    }
    didInitialFit.current = true;
    const box = fitBBoxOfSelection(initialSelectedIds ?? [], nodesById);
    if (box !== null) {
      focusSeq.current += 1;
      setFocus({ seq: focusSeq.current, mode: 'fit', bbox: box });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per mount
  }, [manifest, nodesById]);

  // Refusal hints clear themselves.
  useEffect(() => {
    if (hint === null) {
      return;
    }
    const timer = setTimeout(() => setHint(null), HINT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [hint]);

  const onNodeClick = (id: number | null) => {
    if (id === null) {
      return;
    }
    const result = toggle(selection, id, ctx);
    if (result.ok) {
      setSelection(result.selection);
      // Deselecting the capital province clears the mark.
      setCapitalId((prev) =>
        prev !== null && !result.selection.includes(prev) ? null : prev,
      );
      setServerMessage(null); // a changed selection voids the old verdict
    } else {
      setHint(refusalHint(result.reason, ctx.max));
    }
  };

  const removeId = (id: number) => {
    setSelection((prev) => prev.filter((v) => v !== id));
    setCapitalId((prev) => (prev === id ? null : prev));
    setServerMessage(null);
  };

  // Capital mark (Issue 15): one at most, only among the selected.
  const toggleCapital = (id: number) => {
    if (!selection.includes(id)) {
      return;
    }
    setCapitalId((prev) => (prev === id ? null : id));
  };

  // Right button on the map — same hit-test as the left click; only a
  // SELECTED province toggles, anything else is a no-op.
  const onNodeContextMenu = (id: number | null) => {
    if (id === null) {
      return;
    }
    toggleCapital(id);
  };

  const requestFocus = (node: MapNodeDTO) => {
    focusSeq.current += 1;
    setFocus({ seq: focusSeq.current, mode: 'fit', bbox: node.bbox });
  };

  const chooseResult = (node: MapNodeDTO) => {
    requestFocus(node); // centres the view only — never toggles
    setSearchOpen(false);
    setActiveIndex(-1);
  };

  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const delta = e.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((i) =>
        Math.min(results.length - 1, Math.max(0, i + delta)),
      );
    } else if (e.key === 'Enter') {
      const node = results[activeIndex >= 0 ? activeIndex : 0];
      if (node) {
        chooseResult(node);
      }
    }
  };

  // Esc with the list open closes only the list (Spec Part 5): the
  // preventDefault marks the event as consumed, and the Popup's Esc
  // listener skips `defaultPrevented` events — neither the picker nor
  // anything else reacts. Once the list is closed the next Esc is a
  // plain one and reaches the Popup → onCancel (or stays, if dirty).
  const onContentKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && searchOpen && results.length > 0) {
      e.preventDefault();
      setSearchOpen(false);
      setActiveIndex(-1);
    }
  };

  const onConfirm = async () => {
    if (!valid || checking || manifest === null) {
      return;
    }
    setChecking(true);
    setServerMessage(null);
    try {
      const answer = await mapApi.checkStartingGroup(token, selection);
      if (
        manifest.rules.require_connected_start &&
        !answer.connected
      ) {
        // The server wins: stay open and show its verdict.
        setServerMessage(
          describeConnectivity(answer.component_count) ??
            'Сервер: набор не связен',
        );
        return;
      }
      const names = new Map<number, string>();
      for (const id of selection) {
        const node = nodesById.get(id);
        if (node) {
          names.set(id, displayName(node));
        }
      }
      onDone(
        selection,
        names,
        capitalId !== null && selection.includes(capitalId)
          ? capitalId
          : null,
      );
    } catch (error) {
      setServerMessage(
        error instanceof ApiError
          ? error.message
          : 'Ошибка сети — попробуйте ещё раз.',
      );
    } finally {
      setChecking(false);
    }
  };

  const countText =
    limits.max !== null
      ? `Выбрано ${selection.length} из ${limits.max}`
      : `Выбрано ${selection.length}`;
  const minText =
    limits.min !== null ? `минимум ${limits.min}` : null;

  // Unsaved input (UI Spec 3.3): the ordered selection or the capital
  // mark differs from what the form handed in — Esc and the scrim stop
  // closing, «×» and «Отмена» keep working.
  const initialCapital =
    initialCapitalId !== null &&
    initialCapitalId !== undefined &&
    (initialSelectedIds ?? []).includes(initialCapitalId)
      ? initialCapitalId
      : null;
  const initialIds = initialSelectedIds ?? [];
  const dirty =
    capitalId !== initialCapital ||
    selection.length !== initialIds.length ||
    selection.some((sid, i) => sid !== initialIds[i]);

  return (
    <Popup
      size="L"
      icon="map"
      title="Выбор провинций"
      onClose={onCancel}
      dirty={dirty}
      flush
      testId="province-picker"
      footer={
        <>
          <Button
            size="m"
            mode="secondary"
            onClick={onCancel}
            data-testid="picker-cancel"
          >
            Отмена
          </Button>
          <Button
            size="m"
            mode="primary"
            onClick={() => void onConfirm()}
            disabled={!valid || checking}
            loading={checking}
            data-testid="picker-done"
          >
            Готово
          </Button>
        </>
      }
    >
      <div
        onKeyDown={onContentKeyDown}
        style={{
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Toolbar: search + counter + connectivity + the capital
            caption — one row, fixed (nothing measures the window). */}
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            padding: '12px 16px',
            flexWrap: 'wrap',
            borderBottom: `1px solid ${tokenVar('line')}`,
          }}
        >
          <div style={{ position: 'relative', flex: 1, minWidth: 240 }}>
            <Search
              value={query}
              placeholder="Найти провинцию"
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchOpen(true);
                setActiveIndex(-1);
              }}
              onKeyDown={onSearchKeyDown}
              // The window's autofocus must NOT open the list (it
              // stays closed until the player types or clicks) — so
              // open on click, not on focus.
              onClick={() => setSearchOpen(true)}
            />
            {searchOpen && results.length > 0 && (
              <div
                data-testid="picker-search-results"
                role="listbox"
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  zIndex: 20,
                  background: 'var(--vkui--color_background_content)',
                  border:
                    '1px solid var(--vkui--color_separator_primary)',
                  borderRadius: 8,
                  maxHeight: 320,
                  overflowY: 'auto',
                }}
              >
                {results.map((node, i) => (
                  <button
                    key={node.id}
                    type="button"
                    role="option"
                    aria-selected={i === activeIndex}
                    data-result-id={node.id}
                    onClick={() => chooseResult(node)}
                    style={{
                      display: 'block',
                      width: '100%',
                      textAlign: 'left',
                      padding: '8px 12px',
                      border: 0,
                      background:
                        i === activeIndex
                          ? 'var(--vkui--color_background_secondary)'
                          : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    {displayName(node)}
                    <Text
                      style={{ opacity: 0.6, marginLeft: 8 }}
                      Component="span"
                    >
                      {node.kind === 'SEA' ? 'морская зона' : 'провинция'}
                    </Text>
                  </button>
                ))}
              </div>
            )}
          </div>
          <Text data-testid="picker-count">
            {countText}
            {minText !== null ? ` · ${minText}` : ''}
          </Text>
          {connectivityText !== null && (
            <Text
              data-testid="picker-connectivity"
              style={{
                color:
                  componentCount === 1
                    ? 'var(--vkui--color_text_positive)'
                    : 'var(--vkui--color_text_negative)',
              }}
            >
              {connectivityText}
            </Text>
          )}
          <Caption
            data-testid="picker-capital-caption"
            style={{
              color: 'var(--vkui--color_text_secondary)',
            }}
          >
            Правая кнопка мыши по выбранной провинции — столица
          </Caption>
        </div>

        {/* Map — a fixed-height block (520 px); MapView fills it.
            Nothing in the window measures `vh` or 100 % of it. */}
        <div
          data-testid="picker-map"
          style={{
            position: 'relative',
            height: MAP_HEIGHT,
            overflow: 'hidden',
          }}
        >
          {manifestState.status === 'error' && (
            <div style={{ padding: 24 }}>
              <FormStatus mode="error" title="Не удалось загрузить карту">
                {manifestState.error.message}
              </FormStatus>
              <Button
                size="l"
                style={{ marginTop: 12 }}
                onClick={() => void manifestState.reload()}
              >
                Повторить
              </Button>
            </div>
          )}
          {manifestState.status !== 'error' &&
            geometryState.status === 'error' && (
              <div style={{ padding: 24 }}>
                <FormStatus
                  mode="error"
                  title="Не удалось загрузить геометрию"
                >
                  {geometryState.error.message}
                </FormStatus>
                <Button
                  size="l"
                  style={{ marginTop: 12 }}
                  onClick={geometryState.retry}
                >
                  Повторить
                </Button>
              </div>
            )}
          {manifest === null || geometryState.geometry === null ? (
            manifestState.status !== 'error' &&
            geometryState.status !== 'error' && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'center',
                  paddingTop: 48,
                }}
              >
                <Spinner size="l" />
              </div>
            )
          ) : (
            <MapView
              mode="select"
              manifest={manifest}
              geometry={geometryState.geometry}
              borders={bordersState.borders}
              bordersFailed={bordersState.status === 'error'}
              state={mapState.state}
              selectedIds={selection}
              disabledIds={disabledIds}
              capitalId={capitalId}
              onNodeClick={onNodeClick}
              onNodeContextMenu={onNodeContextMenu}
              focus={focus}
            />
          )}
        </div>

        {/* Chips area — a fixed two-row box with internal scroll,
            always rendered BELOW the map: the map keeps its constant
            height when provinces are added or removed (backlog
            «Дёрганье карты»). The refusal hint lives inside the same
            reserved box. */}
        <div
          data-testid="picker-chips"
          style={{
            boxSizing: 'border-box',
            height: CHIPS_AREA_HEIGHT,
            overflowY: 'auto',
            padding: '4px 16px',
            borderTop: `1px solid ${tokenVar('line')}`,
          }}
        >
          <div
            style={{
              display: 'flex',
              gap: 6,
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            {selection.map((sid) => {
              const node = nodesById.get(sid);
              const isCapital = sid === capitalId;
              return (
                <Chip
                  key={sid}
                  value={sid}
                  onRemove={() => removeId(sid)}
                  aria-label={`Удалить ${
                    node ? displayName(node) : String(sid)
                  }`}
                  after={
                    <IconButton
                      aria-label={
                        isCapital
                          ? 'Снять отметку столицы'
                          : 'Сделать столицей'
                      }
                      aria-pressed={isCapital}
                      data-testid={`capital-star-${sid}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleCapital(sid);
                      }}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        blockSize: 24,
                        inlineSize: 24,
                        color: isCapital
                          ? 'var(--vkui--color_icon_accent)'
                          : 'var(--vkui--color_icon_secondary)',
                        opacity: isCapital ? 1 : 0.55,
                      }}
                    >
                      <Icon16StarAlt style={{ padding: 0 }} />
                    </IconButton>
                  }
                >
                  {node ? displayName(node) : String(sid)}
                </Chip>
              );
            })}
            {hint !== null && (
              <Text
                data-testid="picker-hint"
                style={{
                  color: 'var(--vkui--color_text_negative)',
                }}
              >
                {hint}
              </Text>
            )}
          </div>
        </div>

        {serverMessage !== null && (
          <FormStatus
            mode="error"
            data-testid="picker-server-message"
            style={{ margin: '8px 16px' }}
          >
            {serverMessage}
          </FormStatus>
        )}
      </div>
    </Popup>
  );
}
