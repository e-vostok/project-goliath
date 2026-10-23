/**
 * lib/tableFilterExtensions.ts — table filter extensions a module
 * registers for a Registry table (Spec 5.5 «Фильтры расширений»).
 *
 * Same idea as `cellActions`: the module that owns the data registers
 * the filter once; the Registry renders one labelled «Все / Да»
 * control per extension in the table's filter panel and knows nothing
 * about the data behind it. `load` returns the set of order numbers
 * the «Да» position keeps — fetched lazily on the first «Да» (or a
 * preset asking for it) and reloaded on «Обновить»; never requested
 * before the player asks. The set is evaluated in the browser
 * (lib/tableView.ts): a row passes «Да» only when the number its key
 * carries (`o<N>` → N) is in the set — everything the filter needs is
 * data the caller already owns, so the rows response and the URL stay
 * exactly the same for every player.
 */

export interface TableFilterExtension {
  /** Unique within the table; also the key of the view state. */
  id: string;
  /** Group label in the filter panel («Назначены мне»). */
  label: string;
  /** Fetch the numbers «Да» keeps; the session Bearer token. */
  load: (token: string) => Promise<ReadonlySet<number>>;
}

/** Load state of an extension's number set, kept by PanelRegistry. */
export type ExtensionSetState =
  | { status: 'loading' }
  | { status: 'ready'; set: ReadonlySet<number> }
  | { status: 'error'; error: Error };

const extensions = new Map<string, TableFilterExtension[]>();

/** Register `ext` on `tableId`; re-registering the same id replaces
 * the previous one (same replace semantics as `registerCellAction`
 * and the backend table sources). */
export function registerTableFilterExtension(
  tableId: string,
  ext: TableFilterExtension,
): void {
  const list = extensions.get(tableId) ?? [];
  const next = list.filter((e) => e.id !== ext.id);
  next.push(ext);
  extensions.set(tableId, next);
}

/** The extensions registered for a table, in registration order. */
export function getTableFilterExtensions(
  tableId: string,
): readonly TableFilterExtension[] {
  return extensions.get(tableId) ?? [];
}

/** Drop every registration — test isolation. */
export function clearTableFilterExtensions(): void {
  extensions.clear();
}
