/**
 * registryFilters.ts — the «Назначены мне» and «Мои приказы» filters
 * the orders module adds to the Registry's «Приказы» table (Spec 5.6,
 * Spec 03_registry 5.5 «Фильтры расширений»).
 *
 * Registered once by `OrdersUiProvider`, next to the `order` cell
 * action. `load` reads `GET /orders/assigned` — the caller's own
 * judge queue — and `GET /orders/mine` — the order numbers of the
 * caller's CURRENT nation (matched on `nation_id`, so a rename keeps
 * them, 0.14.0 unit 5); both return the order numbers and the
 * Registry keeps only rows whose `o<N>` key is in the set. Neither
 * response carries judge fields (INV-O5) and nothing about the judge
 * reaches the rows request or the URL: the filters are evaluated in
 * the browser from data the caller already owns.
 */

import { registerTableFilterExtension } from '../03_registry/lib/tableFilterExtensions';
import { ordersApi } from './api';
import { ORDERS_TEXTS } from './texts';

/** The Registry table the filters extend (configs/03_registry.yaml). */
export const ORDERS_TABLE_ID = 'orders';

/** Extension ids — the view-state keys and the presets' targets. */
export const ASSIGNED_TO_ME_FILTER_ID = 'assigned_to_me';
export const MY_ORDERS_FILTER_ID = 'my_orders';

export function registerOrdersTableFilters(): void {
  registerTableFilterExtension(ORDERS_TABLE_ID, {
    id: ASSIGNED_TO_ME_FILTER_ID,
    label: ORDERS_TEXTS.assignedToMeFilter,
    load: async (token) => {
      const dto = await ordersApi.getAssigned(token);
      return new Set(dto.items.map((item) => item.number));
    },
  });
  registerTableFilterExtension(ORDERS_TABLE_ID, {
    id: MY_ORDERS_FILTER_ID,
    label: ORDERS_TEXTS.myOrdersFilter,
    load: async (token) => {
      const dto = await ordersApi.getMine(token);
      return new Set(dto.items.map((item) => item.number));
    },
  });
}
