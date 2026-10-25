/**
 * The one-time entry link token (0.11.0 unit 5a).
 *
 * The Mini App opens `/admin.html#t=<token>` in a new tab; the
 * fragment never reaches the server or Referer. On load the page
 * lifts the token OUT of the address bar immediately — it must never
 * stay visible in the URL — and exchanges it for a short session.
 */

const ENTRY_TOKEN_RE = /^#t=(.+)$/;

/**
 * Read `#t=…` and strip the whole fragment with `history.replaceState`
 * in the same step. Returns the raw token, or null when the address
 * carries no entry token. Never logs or persists the token.
 */
export function takeEntryToken(): string | null {
  const match = ENTRY_TOKEN_RE.exec(window.location.hash);
  if (match === null) {
    return null;
  }
  const token = match[1];
  try {
    window.history.replaceState(
      null,
      '',
      window.location.pathname + window.location.search,
    );
  } catch {
    // A locked-down history leaves the fragment in place — the
    // exchange still runs; the token simply stays in the bar.
  }
  return token;
}
