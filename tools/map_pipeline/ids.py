"""Stable node ids shared by the ``nodes`` and ``graph`` commands (INV-M1).

The "current key set" is the union of included land keys and the
``sea_*`` keys of ``overrides.sea_zones``. Existing keys keep their ids;
new keys receive ``max(existing, MIN_NODE_ID - 1) + 1, +2, ...`` — new land
keys first (ascending key), then new sea keys (ascending key). Because both
commands call this function with the same rule, they produce the identical
``ids.lock.json`` regardless of the order they are run in. A locked key that
disappears from the input is ``KEY_REMOVED``, never a silent deletion.
"""
from __future__ import annotations

import json
from pathlib import Path

from .errors import KEY_REMOVED, PipelineError, PipelineFailure
from .models import IdsLock, MIN_NODE_ID, load_ids_lock

_IDS_LOCK_FILE = "ids.lock.json"


def canonical_lock(ids: dict[str, int]) -> str:
    ordered = {k: v for k, v in sorted(ids.items(), key=lambda kv: kv[1])}
    doc = {"version": 1, "ids": ordered}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def assign_ids(
    data_dir: Path,
    land_keys: list[str],
    sea_keys: list[str],
    keep_extra: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, int], list[int], str, bool]:
    """Load the lock and append new keys.

    ``keep_extra`` lists keys that may stay in the lock without producing a
    node — provinces moved to ``boundary.exclude_explicit`` and retired sea
    zones (INV-M1: a retired node's id is never reused). Every other locked
    key that disappears from the current key set is still ``KEY_REMOVED``.

    Returns ``(ids, new_ids, canonical_text, changed)``: ``ids`` maps every
    current key (land and sea), ``new_ids`` lists freshly assigned ids in the
    order they were handed out, ``changed`` says the canonical text differs
    from the file on disk.
    """
    lock_path = data_dir / _IDS_LOCK_FILE
    existing: dict[str, int] = {}
    old_text: str | None = None
    if lock_path.exists():
        lock: IdsLock = load_ids_lock(lock_path)
        existing = dict(lock.ids)
        old_text = lock_path.read_text(encoding="utf-8")

    key_set = set(land_keys) | set(sea_keys)
    removed = sorted(
        k for k in existing if k not in key_set and k not in keep_extra
    )
    if removed:
        raise PipelineFailure(
            [
                PipelineError(
                    KEY_REMOVED,
                    f"ids.lock.json key {k!r} is no longer an included "
                    "node and is not retired; remove it manually if "
                    "intentional",
                )
                for k in removed
            ]
        )

    # Locked keys kept only because they are retired: they produce no node
    # but their ids remain reserved forever (INV-M1).
    retained = {
        k: v for k, v in existing.items() if k not in key_set
    }
    ids = {k: existing[k] for k in key_set if k in existing}
    new_ids: list[int] = []
    next_id = max([MIN_NODE_ID - 1, *existing.values()]) + 1
    for key in sorted(set(land_keys) - ids.keys()):
        ids[key] = next_id
        new_ids.append(next_id)
        next_id += 1
    for key in sorted(set(sea_keys) - ids.keys()):
        ids[key] = next_id
        new_ids.append(next_id)
        next_id += 1

    text = canonical_lock({**ids, **retained})
    return ids, new_ids, text, text != old_text
