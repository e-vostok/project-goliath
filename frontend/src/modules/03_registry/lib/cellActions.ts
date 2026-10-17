/**
 * lib/cellActions.ts — the client-side cell action registry (Spec 5.6).
 *
 * The Registry renders an `action_text` cell as a button-looking link
 * whose `action` string is "<handler>:<arg>" (e.g. "order:12"). The
 * module that owns the data registers `handler` once; a click runs it
 * with `arg`. With no handler registered the click does nothing — the
 * Registry itself knows nothing about orders or other callers.
 */

export type CellActionHandler = (arg: string) => void;

const handlers = new Map<string, CellActionHandler>();

/** Register `fn` as the handler named `handler`; re-registering
 * replaces the previous one (same replace semantics as the backend
 * table sources). */
export function registerCellAction(
  handler: string,
  fn: CellActionHandler,
): void {
  handlers.set(handler, fn);
}

/** Run `action` ("<handler>:<arg>") exactly like a cell click would. */
export function runCellAction(action: string): void {
  const sep = action.indexOf(':');
  if (sep <= 0) {
    return;
  }
  handlers.get(action.slice(0, sep))?.(action.slice(sep + 1));
}

/** Drop every registration — test isolation. */
export function clearCellActions(): void {
  handlers.clear();
}
