/**
 * registryFilters.ts — the «Назначены мне» filter the orders module
 * adds to the Registry's «Приказы» table (Spec 5.6, Spec 03_registry
 * 5.5 «Фильтры расширений»).
 *
 * Registered once by `OrdersUiProvider`, next to the `order` cell
 * action. `load` reads `GET /orders/assigned` — the caller's own
 * judge queue — and returns the order numbers; the Registry keeps
 * only rows whose `o<N>` key is in the set. The response never
 * carries judge fields (INV-O5) and nothing about the judge reaches
 * the rows request or the URL: the filter is evaluated in the
 * browser from data the caller already owns.
 */

import { registerTableFilterExtension } from '../03_registry/lib/tableFilterExtensions';
import { ordersApi } from './api';
import { ORDERS_TEXTS } from './texts';

/** The Registry table the filter extends (configs/03_registry.yaml). */
export const ORDERS_TABLE_ID = 'orders';

/** Extension id — the view-state key and the preset's target. */
export const ASSIGNED_TO_ME_FILTER_ID = 'assigned_to_me';

export function registerOrdersTableFilters(): void {
  registerTableFilterExtension(ORDERS_TABLE_ID, {
    id: ASSIGNED_TO_ME_FILTER_ID,
    label: ORDERS_TEXTS.assignedToMeFilter,
    load: async (token) => {
      const dto = await ordersApi.getAssigned(token);
      return new Set(dto.items.map((item) => item.number));
    },
  });
}
