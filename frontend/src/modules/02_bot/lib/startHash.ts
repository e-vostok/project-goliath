/**
 * The «Создать государство» button of the bot's GUEST keyboard opens the
 * Mini App with `hash = "register"` (Spec 5.5): VK passes it in the launch
 * params after `#`, so the app starts with the bare hash `#register`.
 *
 * Exact match after stripping ONE leading '#': `register&x=1` or
 * `register?x=1` are NOT interpreted — the hash carries no data and
 * grants no access. `map` belongs to module 01_map; everything else is
 * ignored.
 */
export function parseStartHash(hash: string): 'register' | null {
  const value = hash.startsWith('#') ? hash.slice(1) : hash;
  return value === 'register' ? 'register' : null;
}
