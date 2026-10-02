# INTERIM: replaced by lifespan sync in Issue 3
"""
Interim province sync command for module 01_map.

The migration removed the 100 placeholder provinces and the startup
synchronisation only arrives in Issue 3, so a development database would
otherwise stay empty. This command bridges the gap:

    cd backend/src
    python -m modules._01_map.sync_nodes [--manifest PATH]

DATABASE_URL comes from the environment or the repo-root .env (the same
file src/main.py loads). The manifest path defaults to
data/map/manifest.json.

Only the ``id`` and ``kind`` of each manifest node are read — no map
validation (that is Issue 2). Rows are written through
``ProvinceService.ensure_nodes`` in a single transaction; the printed
counts are added / kind_mismatch / extra_in_db.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow `python -m modules._01_map.sync_nodes` from backend/src and direct
# script invocation from anywhere: put backend/src on sys.path if missing.
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from core.db import get_engine, get_session_context, init_engine  # noqa: E402
from modules._00_core.service import (  # noqa: E402
    EnsureNodesResult,
    NodeSpec,
    ProvinceService,
)

_REPO_ROOT = _SRC_DIR.parent.parent
DEFAULT_MANIFEST = _REPO_ROOT / "data" / "map" / "manifest.json"


def load_node_specs(manifest_path: str | Path) -> list[NodeSpec]:
    """Read (id, kind) pairs out of a manifest.json — nothing else."""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return [
        NodeSpec(id=node["id"], kind=node["kind"])
        for node in data["nodes"]
    ]


async def sync_nodes(
    session, manifest_path: str | Path
) -> EnsureNodesResult:
    """
    Ensure all manifest nodes exist in provinces, in one transaction.

    The caller owns the session: this function does not commit.
    """
    nodes = load_node_specs(manifest_path)
    return await ProvinceService.ensure_nodes(session, nodes)


async def _run(manifest_path: str | Path, database_url: str) -> EnsureNodesResult:
    init_engine(database_url)
    try:
        async with get_session_context() as session:
            result = await sync_nodes(session, manifest_path)
            await session.commit()
    finally:
        await get_engine().dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m modules._01_map.sync_nodes",
        description="Insert missing map nodes into provinces (interim).",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to manifest.json (default: data/map/manifest.json).",
    )
    args = parser.parse_args(argv)

    load_dotenv(dotenv_path=_REPO_ROOT / ".env")
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("DATABASE_URL is not set (environment or repo-root .env).")
        return 2

    result = asyncio.run(_run(args.manifest, database_url))
    print(
        f"added={len(result.added)} "
        f"kind_mismatch={len(result.kind_mismatch)} "
        f"extra_in_db={len(result.extra_in_db)}"
    )
    if result.kind_mismatch:
        print(f"kind_mismatch ids: {result.kind_mismatch}")
    if result.extra_in_db:
        print(f"extra_in_db ids: {result.extra_in_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
