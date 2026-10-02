/**
 * MapEntryButton — the temporary service entry «Карта» on the main
 * panels (Spec 1.8 «Вход на экран карты»). Deliberately trivial to
 * remove: one component, used in AppShell's two panels.
 */

import { useRouteNavigator } from '@vkontakte/vk-mini-apps-router';
import { Button } from '@vkontakte/vkui';

export function MapEntryButton() {
  const navigator = useRouteNavigator();
  return (
    <div
      style={{
        position: 'fixed',
        right: 12,
        bottom: 12,
        zIndex: 3,
      }}
    >
      <Button size="s" mode="secondary" onClick={() => navigator.push('/map')}>
        Карта
      </Button>
    </div>
  );
}
