/**
 * RegistryEntryButton — the temporary service entry «Реестр» (Spec 5.5).
 * Same shape as MapEntryButton, fixed right:12 directly above the «Карта»
 * button (map button: bottom 12, size-s height ~28px + 8px gap => 48).
 * Deliberately trivial to remove with the real navigation.
 */

import { useRouteNavigator } from '@vkontakte/vk-mini-apps-router';
import { Button } from '@vkontakte/vkui';

export function RegistryEntryButton() {
  const navigator = useRouteNavigator();
  return (
    <div
      style={{
        position: 'fixed',
        right: 12,
        bottom: 48,
        zIndex: 3,
      }}
    >
      <Button
        size="s"
        mode="secondary"
        onClick={() => navigator.push('/registry')}
      >
        Реестр
      </Button>
    </div>
  );
}
