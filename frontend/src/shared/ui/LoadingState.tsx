/**
 * Loading state (UI Spec 7): one indicator for every place; the block
 * keeps its height while loading so the window does not jump — pass the
 * height of the content being waited for.
 */

import { Spinner } from '@vkontakte/vkui';

export function LoadingState({ height = 120 }: { height?: number }) {
  return (
    <div
      style={{
        minHeight: height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Spinner size="m" disableAnimation={false} />
    </div>
  );
}
