/**
 * ProvincePicker — the registration starting-group picker (Spec Part 5).
 *
 * A large ModalPage: a Search row (results only centre/fit the view —
 * they never toggle the selection), the counter «Выбрано N из M» with
 * «минимум K», the local connectivity indicator, a removable-chips row
 * of the current selection, and a MapView in `select` mode filling the
 * rest. «Готово» is enabled while the count is inside [min, max] from
 * GET /nations/rules and — when manifest.rules.require_connected_start
 * is on — the selection is one component over land/strait edges.
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
import {
  Button,
  Chip,
  FormStatus,
  ModalPage,
  ModalPageHeader,
  Search,
  Spinner,
  Text,
  unstable_ModalPageFooter as ModalPageFooter,
} from '@vkontakte/vkui';

import { ApiError } from '../../../shared/api-client';
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
import { useMapGeometry } from '../hooks/useMapGeometry';
import { useMapManifest } from '../hooks/useMapManifest';
import { useMapSearch } from '../hooks/useMapSearch';
import { useMapState } from '../hooks/useMapState';
import { useSession } from '../../00_core/hooks/useAuth';
import { MapView, type MapViewFocus } from './MapView';

/** How long a refusal hint stays visible under the header, ms. */
const HINT_TIMEOUT_MS = 3000;

export interface ProvincePickerProps {
  /** ModalPage nav id inside the caller's ModalRoot. */
  id: string;
  /** Ids already chosen in the form — the picker starts with them. */
  initialSelectedIds?: number[];
  /** min/max provinces from GET /nations/rules; null while unknown. */
  limits: SelectionLimits;
  /** Success: ordered selected ids plus their display names for chips. */
  onDone: (ids: number[], names: Map<number, string>) => void;
  /** Any dismissal (Отмена / Esc / overlay) — the form stays unchanged. */
  onCancel: () => void;
}

export function ProvincePicker({
  id,
  initialSelectedIds,
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
  const mapState = useMapState(manifest?.rules.refresh ?? null);
  const { query, setQuery, results } = useMapSearch(manifest);

  const [selection, setSelection] = useState<number[]>(
    () => initialSelectedIds ?? [],
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
    () => buildOwnerMap(mapState.state),
    [mapState.state],
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
      setServerMessage(null); // a changed selection voids the old verdict
    } else {
      setHint(refusalHint(result.reason, ctx.max));
    }
  };

  const removeId = (id: number) => {
    setSelection((prev) => prev.filter((v) => v !== id));
    setServerMessage(null);
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
  // FocusTrap Escape path runs on document capture, so the trap is
  // disabled while the list is open and this handler closes the list;
  // the modal-level onKeyDown is neutralised by stopPropagation. Once
  // the list is closed the next Esc reaches the modal → onCancel,
  // selection unchanged.
  const onContentKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && searchOpen) {
      e.stopPropagation();
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
      onDone(selection, names);
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

  return (
    <ModalPage
      id={id}
      onClose={onCancel}
      size="calc(100vw - 64px)"
      height="calc(100vh - 96px)"
      disableFocusTrap={searchOpen}
      modalContentTestId="province-picker-content"
      header={<ModalPageHeader>Выбор провинций</ModalPageHeader>}
      footer={
        <ModalPageFooter>
          <div
            style={{
              display: 'flex',
              gap: 8,
              justifyContent: 'flex-end',
            }}
          >
            <Button
              mode="secondary"
              onClick={onCancel}
              data-testid="picker-cancel"
            >
              Отмена
            </Button>
            <Button
              mode="primary"
              onClick={() => void onConfirm()}
              disabled={!valid || checking}
              loading={checking}
              data-testid="picker-done"
            >
              Готово
            </Button>
          </div>
        </ModalPageFooter>
      }
    >
      <div
        data-testid="province-picker"
        onKeyDown={onContentKeyDown}
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 0,
        }}
      >
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            padding: '0 12px 8px',
            flexWrap: 'wrap',
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
              onFocus={() => setSearchOpen(true)}
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
        </div>

        {(selection.length > 0 || hint !== null) && (
          <div
            style={{
              display: 'flex',
              gap: 6,
              alignItems: 'center',
              flexWrap: 'wrap',
              padding: '0 12px 8px',
            }}
          >
            {selection.map((sid) => {
              const node = nodesById.get(sid);
              return (
                <Chip
                  key={sid}
                  value={sid}
                  onRemove={() => removeId(sid)}
                  aria-label={`Удалить ${
                    node ? displayName(node) : String(sid)
                  }`}
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
        )}

        <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
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
              state={mapState.state}
              selectedIds={selection}
              disabledIds={disabledIds}
              onNodeClick={onNodeClick}
              focus={focus}
            />
          )}
        </div>

        {serverMessage !== null && (
          <FormStatus
            mode="error"
            data-testid="picker-server-message"
            style={{ margin: '0 12px 8px' }}
          >
            {serverMessage}
          </FormStatus>
        )}
      </div>
    </ModalPage>
  );
}
