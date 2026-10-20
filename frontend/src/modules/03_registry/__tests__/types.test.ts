/**
 * Cell-shape guards — the `nation` cell carries `id` since 0.9.0
 * (unit 14): the client needs it to open the «Государство» subscreen.
 */

import { isNationCell, type RegistryCell } from '../types';

describe('isNationCell', () => {
  it('accepts the new shape (id string or null), rejects a cell without `id`', () => {
    const valid = {
      id: 'n1',
      name: 'Новгород',
      color: '#C0392B',
      flag_url: null,
    };
    expect(isNationCell(valid)).toBe(true);
    // The orders source knows only a name/colour snapshot — id is null.
    expect(isNationCell({ ...valid, id: null })).toBe(true);
    // The pre-14b shape without `id` is not a nation cell anymore.
    expect(
      isNationCell({
        name: 'Новгород',
        color: '#C0392B',
        flag_url: null,
      } as unknown as RegistryCell),
    ).toBe(false);
    // A non-string `id` is malformed too.
    expect(
      isNationCell({ ...valid, id: 7 } as unknown as RegistryCell),
    ).toBe(false);
    expect(isNationCell(null)).toBe(false);
  });
});
