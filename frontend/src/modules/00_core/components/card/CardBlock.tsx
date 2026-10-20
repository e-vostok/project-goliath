/**
 * CardBlock — the surface block every section of the nation card sits
 * in (UI Spec 3.1): `surface` background, `radius-lg`, `space-4`
 * padding. Not a shared-ui element: the card's own building piece,
 * repeated here so every block of the screen looks identical.
 */

import type { CSSProperties, ReactNode } from 'react';

import { RADII, SPACING, tokenVar } from '../../../../shared/ui';

export const CARD_BLOCK_STYLE: CSSProperties = {
  background: tokenVar('surface'),
  borderRadius: RADII['radius-lg'],
  padding: SPACING['space-4'],
};

export function CardBlock({
  children,
  testId,
}: {
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section data-testid={testId} style={CARD_BLOCK_STYLE}>
      {children}
    </section>
  );
}
