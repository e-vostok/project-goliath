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

export const PANEL_HOME = 'nation-home';
export const PANEL_CREATE = 'nation-create';
const MODAL_DELETE_NATION = 'confirm-delete-nation';

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
            <FormStatus mode="error" title="Failed to sign in">
              {auth.error.message}
            </FormStatus>
          </Div>
          <Div>
            <Button
              size="l"
              stretched
              onClick={() => window.location.reload()}
            >
              Retry
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

  // The panel is a function of nation existence — keep the route in sync.
  useEffect(() => {
    if (status !== 'ready') {
      return;
    }
    if (nation === null && activePanel !== PANEL_CREATE) {
      void navigator.push('/nation/new');
    }
    if (nation !== null && activePanel !== PANEL_HOME) {
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
          </Panel>
          <Panel id={PANEL_HOME}>
            {status === 'loading' && <LoadingCell />}
            {status === 'error' && (
              <Div>
                <FormStatus mode="error" title="Could not load your nation">
                  {nationState.error.message}
                </FormStatus>
                <Button size="l" stretched onClick={refresh}>
                  Retry
                </Button>
              </Div>
            )}
            {status === 'ready' && nation && (
              <PanelNationHome
                nation={nation}
                onChanged={refresh}
                onDeleteRequest={() => setActiveModal(MODAL_DELETE_NATION)}
              />
            )}
          </Panel>
        </View>
      </SplitCol>
    </SplitLayout>
  );
}


