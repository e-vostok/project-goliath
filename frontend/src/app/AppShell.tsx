/**
 * AppShell — auth gate + top-level layout for module 00_core.
 *
 * Gate: ScreenSpinner while POST /auth/vk resolves; a blocking error screen
 * on failure; SessionProvider + routed panels once authenticated.
 * Panel selection follows server truth (nation exists → home, else create),
 * kept in sync with the hash router.
 */

import { useEffect, useRef, useState } from 'react';
import {
  useActiveVkuiLocation,
  useRouteNavigator,
} from '@vkontakte/vk-mini-apps-router';
import {
  Button,
  Div,
  FormStatus,
  ModalRoot,
  Panel,
  ScreenSpinner,
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
import { ModalConfirmDeleteNation } from '../modules/00_core/components/ModalConfirmDeleteNation';
import { PanelMap } from '../modules/01_map/components/PanelMap';
import { PanelRegistry } from '../modules/03_registry/components/PanelRegistry';
import { OrdersUiProvider } from '../modules/04_orders/OrdersUiProvider';
import { PopupHost } from '../shared/ui';
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
const MODAL_DELETE_NATION = 'confirm-delete-nation';

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
    return <ScreenSpinner />;
  }

  if (auth.status === 'error') {
    return (
      <SplitLayout>
        <SplitCol>
          <Div>
            <FormStatus mode="error" title="Не удалось войти">
              {auth.error.message}
            </FormStatus>
          </Div>
          <Div>
            <Button
              size="l"
              stretched
              onClick={() => window.location.reload()}
            >
              Повторить
            </Button>
          </Div>
        </SplitCol>
      </SplitLayout>
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
  const nationState = useNation();
  const [activeModal, setActiveModal] = useState<string | null>(null);
  // The root container the VK window height follows (UI Spec 2):
  // top bar + layout, measured as one block — never the page.
  const shellRef = useRef<HTMLDivElement>(null);
  useWindowHeight(shellRef);
  // The entry request is consumed once — the first read wins, later
  // renders get null (takeRegistryEntryRequest clears the store).
  const registryRequest = useRef(takeRegistryEntryRequest()).current;

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

  // The VKUI ModalRoot keeps ONLY the delete-nation card (unit 8
  // removes it); the order windows are shared Popups inside the
  // provider — PopupHost portals them into the root container.
  const modal = (
    <ModalRoot
      activeModal={activeModal}
      onClose={() => setActiveModal(null)}
    >
      <ModalConfirmDeleteNation
        id={MODAL_DELETE_NATION}
        nationName={nation?.name ?? ''}
        onClose={() => setActiveModal(null)}
        onDeleted={() => {
          setActiveModal(null);
          refresh();
        }}
      />
    </ModalRoot>
  );

  return (
    <div
      ref={shellRef}
      data-testid="app-root"
      style={{ position: 'relative' }}
    >
      <PopupHost container={shellRef}>
        <OrdersUiProvider>
          <TopBar activePanel={activePanel} clock={clock} />
          <SplitLayout modal={modal}>
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
                        {nationState.error.message}
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
                      onDeleteRequest={() =>
                        setActiveModal(MODAL_DELETE_NATION)
                      }
                    />
                  )}
                  <AdminBlock onWorldChanged={handleWorldChanged} />
                </Panel>
                <Panel id={PANEL_MAP}>
                  <PanelMap />
                </Panel>
                <Panel id={PANEL_REGISTRY}>
                  <PanelRegistry
                    entryRequest={registryRequest}
                    active={activePanel === PANEL_REGISTRY}
                  />
                </Panel>
              </View>
            </SplitCol>
          </SplitLayout>
        </OrdersUiProvider>
      </PopupHost>
    </div>
  );
}


