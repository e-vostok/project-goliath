/**
 * AppShell — auth gate + top-level layout for module 00_core.
 *
 * Gate: the shared LoadingScreen while POST /auth/vk resolves; a blocking
 * error screen on failure; SessionProvider + routed panels once
 * authenticated.
 * Panel selection follows server truth (nation exists → home, else create),
 * kept in sync with the hash router.
 */

import { useEffect, useRef, useState } from 'react';
import {
  useActiveVkuiLocation,
  useParams,
  useRouteNavigator,
} from '@vkontakte/vk-mini-apps-router';
// `useLocation` exists in the package but is not re-exported from its
// root — the subscreen's «fromTab» chain reads location.state.
import { useLocation } from '@vkontakte/vk-mini-apps-router/dist/hooks/hooks';
import {
  Button,
  Div,
  FormStatus,
  Panel,
  SplitCol,
  SplitLayout,
  Spinner,
  View,
} from '@vkontakte/vkui';

import { useAuth, SessionProvider } from '../modules/00_core/hooks/useAuth';
import { useGameClock } from '../modules/00_core/hooks/useGameClock';
import { useNation } from '../modules/00_core/hooks/useNation';
import { PanelCreateNation } from '../modules/00_core/components/PanelCreateNation';
import { PanelNationHome } from '../modules/00_core/components/PanelNationHome';
import { NationSubscreen } from '../modules/00_core/components/NationSubscreen';
import { PanelMap } from '../modules/01_map/components/PanelMap';
import { setMapEntryRequest } from '../modules/01_map/lib/mapEntryRequest';
import { PanelRegistry } from '../modules/03_registry/components/PanelRegistry';
import { PlayerSubscreen } from '../modules/03_registry/components/PlayerSubscreen';
import { OrdersUiProvider } from '../modules/04_orders/OrdersUiProvider';
import { errorText } from '../shared/errorTexts';
import {
  AuthErrorScreen,
  LoadingScreen,
  NoticeHost,
  PopupHost,
} from '../shared/ui';
import {
  parseRegistryOrderHash,
  setRegistryEntryRequest,
  takeRegistryEntryRequest,
} from '../modules/03_registry/lib/entryRequest';
import { BotStatusProvider } from '../modules/02_bot/hooks/useBotStatus';
import { parseStartHash } from '../modules/02_bot/lib/startHash';
import { AdminBlock } from '../admin/AdminBlock';
import { TopBar } from './TopBar';
import {
  PANEL_CREATE,
  PANEL_HOME,
  PANEL_MAP,
  PANEL_REGISTRY,
} from './panels';
import { useWindowHeight } from './useWindowHeight';

export { PANEL_CREATE, PANEL_HOME, PANEL_MAP, PANEL_REGISTRY };

/**
 * The nation id in the `#/registry/nation-<id>` address — hex + dash
 * (the UUID alphabet), 8–64 chars (UI Spec 9.3). Anything else in the
 * `:sub` segment or after `#registry/nation-` is not a nation address.
 */
export const NATION_SUB_RE = /^nation-[0-9a-fA-F-]{8,64}$/;

/** `#registry/nation-<id>` — the bare (menu/bot) form of the address. */
const NATION_BARE_HASH_RE = /^#registry\/(nation-[0-9a-fA-F-]{8,64})$/;

/**
 * The player subscreen address `#/registry/player-<N>` (UI Spec 9.7,
 * 0.10.0 unit 8b): `<N>` is the player's public Registry number — the
 * players-table row key `p<N>` — 1–9 digits. Anything else in the
 * `:sub` segment is not a player address.
 */
export const PLAYER_SUB_RE = /^player-[0-9]{1,9}$/;

/** `#registry/player-<N>` — the bare form of the address. */
const PLAYER_BARE_HASH_RE = /^#registry\/(player-[0-9]{1,9})$/;

/**
 * The community-menu deep link `https://vk.com/app<APP_ID>#map` arrives
 * as the bare hash `#map`; the hash router expects a path. Call once,
 * before the router is created (main.tsx). Module 02_bot adds the
 * `register` start hint from the bot's keyboard button (Spec 5.6) —
 * it maps to the registration panel, where the consent gate decides
 * what is actually shown after authentication.
 */
export function normalizeEntryHash(): void {
  // `#registry/order-<1-9 digits>` (a bot message link, Spec 04_orders
  // 5.5): open the Registry and hand it the order request — the hash
  // itself is only a start hint and carries no access.
  const orderRequest = parseRegistryOrderHash(window.location.hash);
  if (orderRequest) {
    setRegistryEntryRequest(orderRequest);
    window.history.replaceState(null, '', '#/registry');
    return;
  }
  // `#registry/nation-<id>` (UI Spec 9.3): the nation subscreen. A
  // malformed id falls back to the plain Registry, no error shown.
  if (window.location.hash.startsWith('#registry/nation-')) {
    const match = NATION_BARE_HASH_RE.exec(window.location.hash);
    window.history.replaceState(
      null,
      '',
      match ? `#/registry/${match[1]}` : '#/registry',
    );
    return;
  }
  // `#registry/player-<N>` (UI Spec 9.7): the player subscreen. A
  // malformed number falls back to the plain Registry, no error shown.
  if (window.location.hash.startsWith('#registry/player-')) {
    const match = PLAYER_BARE_HASH_RE.exec(window.location.hash);
    window.history.replaceState(
      null,
      '',
      match ? `#/registry/${match[1]}` : '#/registry',
    );
    return;
  }
  if (window.location.hash === '#map') {
    window.history.replaceState(null, '', '#/map');
    return;
  }
  if (window.location.hash === '#registry') {
    window.history.replaceState(null, '', '#/registry');
    return;
  }
  if (parseStartHash(window.location.hash) === 'register') {
    window.history.replaceState(null, '', '#/nation/new');
  }
}

export function AppShell() {
  const auth = useAuth();

  if (auth.status === 'loading') {
    return <LoadingScreen />;
  }

  if (auth.status === 'error') {
    // The Mini App relaunches with fresh launch params every time, so
    // retrying the exchange is a full page reload (useAuth).
    return (
      <AuthErrorScreen
        reason={errorText(auth.error)}
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <SessionProvider session={{ token: auth.token, player: auth.player }}>
      <BotStatusProvider>
        <AuthedArea />
      </BotStatusProvider>
    </SessionProvider>
  );
}

function LoadingCell() {
  return (
    <Div
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '48px 0',
      }}
    >
      <Spinner size="l" />
    </Div>
  );
}

function AuthedArea() {
  const { panel } = useActiveVkuiLocation();
  const navigator = useRouteNavigator();
  const params = useParams();
  const location = useLocation();
  const nationState = useNation();
  // The root container the VK window height follows (UI Spec 2):
  // top bar + layout, measured as one block — never the page.
  const shellRef = useRef<HTMLDivElement>(null);
  useWindowHeight(shellRef);
  // The entry request is consumed once — the first read wins, later
  // renders get null (takeRegistryEntryRequest clears the store).
  const registryRequest = useRef(takeRegistryEntryRequest()).current;

  // The nation subscreen (unit 14c) and the player subscreen (0.10.0
  // unit 8b): the `/registry/:sub` route's segment → the nation id or
  // the player number; any other segment shows the plain Registry.
  // `fromTab` rides router state (a row click pushes
  // {fromTab: <tab title>}); a bare link has none.
  const subSegment = params?.sub;
  const nationSubId =
    typeof subSegment === 'string' && NATION_SUB_RE.test(subSegment)
      ? subSegment.slice('nation-'.length)
      : null;
  const playerSubNumber =
    typeof subSegment === 'string' && PLAYER_SUB_RE.test(subSegment)
      ? Number(subSegment.slice('player-'.length))
      : null;
  const fromTab = (() => {
    const state = location.state as { fromTab?: unknown } | null;
    return state !== null && typeof state.fromTab === 'string'
      ? state.fromTab
      : null;
  })();

  const { status, nation, refresh } = nationState;
  const activePanel = panel ?? PANEL_HOME;
  // Bumped by the admin block after tick/reset: remounts PanelNationHome so
  // it refetches the game clock, while refresh() reloads the nation itself.
  const [worldVersion, setWorldVersion] = useState(0);
  // The top bar's turn badge follows the same refresh signal.
  const clock = useGameClock(worldVersion);
  const handleWorldChanged = () => {
    refresh();
    setWorldVersion((v) => v + 1);
  };

  // The panel is a function of nation existence — keep the route in sync.
  // The map and registry screens are open to everyone, so they are exempt
  // from the redirect.
  useEffect(() => {
    if (status !== 'ready') {
      return;
    }
    if (
      nation === null &&
      activePanel !== PANEL_CREATE &&
      activePanel !== PANEL_MAP &&
      activePanel !== PANEL_REGISTRY
    ) {
      void navigator.push('/nation/new');
    }
    if (
      nation !== null &&
      activePanel !== PANEL_HOME &&
      activePanel !== PANEL_MAP &&
      activePanel !== PANEL_REGISTRY
    ) {
      void navigator.push('/');
    }
  }, [status, nation, activePanel, navigator]);

  return (
    <div
      ref={shellRef}
      data-testid="app-root"
      style={{ position: 'relative' }}
    >
      <PopupHost container={shellRef}>
        <NoticeHost container={shellRef}>
          <OrdersUiProvider>
            <TopBar activePanel={activePanel} clock={clock} />
            <SplitLayout>
              <SplitCol>
                <View activePanel={activePanel}>
                  <Panel id={PANEL_CREATE}>
                    {status === 'loading' ? (
                      <LoadingCell />
                    ) : (
                      nation === null && (
                        <PanelCreateNation onCreated={refresh} />
                      )
                    )}
                    <AdminBlock onWorldChanged={handleWorldChanged} />
                  </Panel>
                  <Panel id={PANEL_HOME}>
                    {status === 'loading' && <LoadingCell />}
                    {status === 'error' && (
                      <Div>
                        <FormStatus
                          mode="error"
                          title="Не удалось загрузить государство"
                        >
                          {errorText(nationState.error)}
                        </FormStatus>
                        <Button size="l" stretched onClick={refresh}>
                          Повторить
                        </Button>
                      </Div>
                    )}
                    {status === 'ready' && nation && (
                      <PanelNationHome
                        key={worldVersion}
                        nation={nation}
                        onChanged={refresh}
                        onOpenRegistry={(request) => {
                          // The «Штаб» order badges' in-app entry
                          // (Spec 03_registry 5.5): store the request,
                          // the Registry takes it on activation.
                          setRegistryEntryRequest(request);
                          void navigator.push('/registry');
                        }}
                      />
                    )}
                    <AdminBlock onWorldChanged={handleWorldChanged} />
                  </Panel>
                  <Panel id={PANEL_MAP}>
                    <PanelMap active={activePanel === PANEL_MAP} />
                  </Panel>
                  <Panel id={PANEL_REGISTRY}>
                    {/* The nation and player subscreens replace the
                        Registry's content IN THE SAME panel — the
                        Registry stays mounted (display:none) and keeps
                        `active=true`, so its tab/search/sort/filters/
                        scroll survive the round trip (Bible 2.7, UI
                        Spec 9.3 / 9.7). */}
                    <div
                      style={
                        nationSubId === null && playerSubNumber === null
                          ? undefined
                          : { display: 'none' }
                      }
                    >
                      <PanelRegistry
                        entryRequest={registryRequest}
                        active={activePanel === PANEL_REGISTRY}
                        onOpenNation={(nationId, fromTabTitle) =>
                          void navigator.push(`/registry/nation-${nationId}`, {
                            state: { fromTab: fromTabTitle },
                          })
                        }
                        onOpenPlayer={(playerNumber, fromTabTitle) =>
                          void navigator.push(
                            `/registry/player-${playerNumber}`,
                            { state: { fromTab: fromTabTitle } },
                          )
                        }
                      />
                    </div>
                    {nationSubId !== null && (
                      <NationSubscreen
                        nationId={nationSubId}
                        fromTab={fromTab}
                        onBack={() => void navigator.push('/registry')}
                        onShowOnMap={(capitalProvinceId) => {
                          if (capitalProvinceId !== null) {
                            setMapEntryRequest({
                              provinceId: capitalProvinceId,
                            });
                          }
                          void navigator.push('/map');
                        }}
                      />
                    )}
                    {playerSubNumber !== null && (
                      <PlayerSubscreen
                        number={playerSubNumber}
                        fromTab={fromTab}
                        onBack={() => void navigator.push('/registry')}
                        onOpenNation={(nationId) =>
                          void navigator.push(`/registry/nation-${nationId}`, {
                            state: { fromTab: fromTab ?? 'Игроки' },
                          })
                        }
                      />
                    )}
                  </Panel>
                </View>
              </SplitCol>
            </SplitLayout>
          </OrdersUiProvider>
        </NoticeHost>
      </PopupHost>
    </div>
  );
}


