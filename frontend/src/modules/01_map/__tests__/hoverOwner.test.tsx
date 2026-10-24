/**
 * Unit 6a: the map names a nation by its SHORT name only — the hover
 * tooltip's owner line reads `MapNationDTO.short_name`, never the
 * full `name` (no flags on the map).
 */

import { fireEvent, render, screen } from '@testing-library/react';

import { MapView } from '../components/MapView';
import {
  MINI_BORDERS,
  MINI_GEOMETRY,
  MINI_MANIFEST,
  MINI_STATE,
} from '../fixtures/miniMap';
import type { MapStateDTO } from '../types';

const STATE: MapStateDTO = {
  ...MINI_STATE,
  nations: [
    {
      id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
      name: 'Тестия-Большая',
      short_name: 'ТСТ',
      color_hex: '#e64545',
    },
  ],
};

describe('MapView — hover owner name (unit 6a)', () => {
  it('shows the owner short name, not the full one', () => {
    render(
      <MapView
        manifest={MINI_MANIFEST}
        geometry={MINI_GEOMETRY}
        borders={MINI_BORDERS}
        state={STATE}
      />,
    );

    const path = document.querySelector(
      'path[data-id="1001"]',
    ) as SVGPathElement;
    fireEvent.mouseMove(path, { clientX: 10, clientY: 10 });

    const tip = screen.getByTestId('map-tooltip');
    expect(tip).toHaveTextContent('ТСТ');
    expect(tip).not.toHaveTextContent('Тестия-Большая');
  });
});
