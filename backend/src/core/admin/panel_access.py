"""
One-time admin-panel entry links (0.11.0 unit 4).

The Mini App issues a cryptographically random link token to an
administrator; a browser tab without VK launch params exchanges it for a
short Bearer session. The store lives in process memory — the backend
runs a single worker (docker-compose.prod.yml) — as an insertion-ordered
dict of ``sha256(token) -> _PanelLink``. The raw token is never stored
and never logged: a leaked log line or a memory dump does not hand out
entry tickets.

Both operations are plain synchronous functions (no ``await``), so on a
single worker the check-and-mark-used of ``redeem`` is atomic: two
exchanges of the same link cannot both win. Expired entries are purged
on every call, a player may hold at most ``max_per_player`` pending
links (the oldest is dropped above the cap) and the whole store is
bounded to ``HARD_CAP`` entries, oldest dropped first — a restarted
process simply forgets unclaimed links and the admin issues a new one.

The clock is a monotonic ``Callable[[], float]`` injectable in tests;
link TTLs and the per-player cap come from ``admin_panel`` in
``configs/00_core.yaml`` and are passed in by the caller.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


def _token_hash(token: str) -> str:
    """SHA-256 hex of the raw link token — the only stored form."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _PanelLink:
    """One pending link: who it belongs to, when it dies, was it spent."""

    player_id: str
    expires_at: float
    used: bool = False


class PanelLinkStore:
    """Bounded process-local store of one-time panel entry links."""

    HARD_CAP = 1000

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # sha256 hex -> _PanelLink; dict order = insertion order (oldest first).
        self._entries: dict[str, _PanelLink] = {}

    def issue(
        self,
        player_id: str,
        *,
        ttl_seconds: int,
        max_per_player: int,
    ) -> str:
        """
        Create a one-time link token for the player and store its hash.

        Purges expired entries, then enforces both bounds BEFORE the new
        entry lands: the player's pending links above ``max_per_player``
        (oldest first) and the store-wide ``HARD_CAP``. Returns the raw
        token — the only place it exists besides the caller's response.
        """
        self._purge_expired()
        pending = [
            key
            for key, entry in self._entries.items()
            if entry.player_id == player_id and not entry.used
        ]
        for key in pending[: max(0, len(pending) - (max_per_player - 1))]:
            del self._entries[key]
        while len(self._entries) >= self.HARD_CAP:
            del self._entries[next(iter(self._entries))]

        token = secrets.token_urlsafe(32)
        self._entries[_token_hash(token)] = _PanelLink(
            player_id=player_id,
            expires_at=self._clock() + ttl_seconds,
        )
        return token

    def redeem(self, token: str) -> str | None:
        """
        Atomically check a token and mark it spent; returns its player_id.

        Unknown, expired and already used tokens all return the same
        ``None`` — the response cannot tell them apart. The entry is
        flagged used (never deleted), so the token stays spent even
        though the caller may still reject the exchange afterwards
        (e.g. revoked admin rights).
        """
        if not isinstance(token, str) or not token:
            return None
        self._purge_expired()
        entry = self._entries.get(_token_hash(token))
        if entry is None or entry.used or entry.expires_at <= self._clock():
            return None
        entry.used = True
        return entry.player_id

    def _purge_expired(self) -> None:
        now = self._clock()
        for key in [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]:
            del self._entries[key]


# The single process-wide store used by the admin router. Tests replace
# it with a fresh instance (or a fake-clock one) via monkeypatch.
store = PanelLinkStore()
