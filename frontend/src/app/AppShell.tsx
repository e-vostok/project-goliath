/**
 * AppShell — auth gate + top-level layout for module 00_core.
 *
 * Gate: ScreenSpinner while POST /auth/vk resolves; a blocking error screen
 * on failure; SessionProvider + routed panels once authenticated.
 * Panel selection follows server truth (nation exists → home, else create),
 * kept in sync with the hash router.
 */

import { useEffect, useState } from 'react';
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
import { useNation } from '../modules/00_core/hooks/useNation';
import { PanelCreateNation } from '../modules/00_core/components/PanelCreateNation';
import { PanelNationHome } from '../modules/00_core/components/PanelNationHome';
import { ModalConfirmDeleteNation } from '../modules/00_core/components/ModalConfirmDeleteNation';
import { PanelMap } from '../modules/01_map/components/PanelMap';
import { MapEntryButton } from '../modules/01_map/components/MapEntryButton';
import { AdminBlock } from '../admin/AdminBlock';

export const PANEL_HOME = 'nation-home';
export const PANEL_CREATE = 'nation-create';
export const PANEL_MAP = 'map';
const MODAL_DELETE_NATION = 'confirm-delete-nation';

/**
 * The community-menu deep link `https://vk.com/app<APP_ID>#map` arrives
 * as the bare hash `#map`; the hash router expects a path. Call once,
 * before the router is created (main.tsx).
 */
export function normalizeEntryHash(): void {
  if (window.location.hash === '#map') {
    window.history.replaceState(null, '', '#/map');
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
      <AuthedArea />
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

  const { status, nation, refresh } = nationState;
  const activePanel = panel ?? PANEL_HOME;
  // Bumped by the admin block after tick/reset: remounts PanelNationHome so
  // it refetches the game clock, while refresh() reloads the nation itself.
  const [worldVersion, setWorldVersion] = useState(0);
  const handleWorldChanged = () => {
    refresh();
    setWorldVersion((v) => v + 1);
  };

  // The panel is a function of nation existence — keep the route in sync.
  // The map screen is open to everyone, so it is exempt from the redirect.
  useEffect(() => {
    if (status !== 'ready') {
      return;
    }
    if (
      nation === null &&
      activePanel !== PANEL_CREATE &&
      activePanel !== PANEL_MAP
    ) {
      void navigator.push('/nation/new');
    }
    if (
      nation !== null &&
      activePanel !== PANEL_HOME &&
      activePanel !== PANEL_MAP
    ) {
      void navigator.push('/');
    }
  }, [status, nation, activePanel, navigator]);

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
    <SplitLayout modal={modal}>
      <SplitCol>
        <View activePanel={activePanel}>
          <Panel id={PANEL_CREATE}>
            {status === 'loading' ? (
              <LoadingCell />
            ) : (
              nation === null && <PanelCreateNation onCreated={refresh} />
            )}
            <AdminBlock onWorldChanged={handleWorldChanged} />
          </Panel>
          <Panel id={PANEL_HOME}>
            {status === 'loading' && <LoadingCell />}
            {status === 'error' && (
              <Div>
                <FormStatus mode="error" title="Не удалось загрузить государство">
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
                onDeleteRequest={() => setActiveModal(MODAL_DELETE_NATION)}
              />
            )}
            <AdminBlock onWorldChanged={handleWorldChanged} />
          </Panel>
          <Panel id={PANEL_MAP}>
            <PanelMap />
          </Panel>
        </View>
        {/* Temporary service entry «Карта» — Issue 5; remove with the
            real navigation. One component, one import. */}
        {activePanel !== PANEL_MAP && <MapEntryButton />}
      </SplitCol>
    </SplitLayout>
  );
}


