"""Command line entry point: ``python -m tools.map_pipeline ...``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import PipelineError, PipelineFailure, print_errors
from .pipeline import run_nodes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.map_pipeline",
        description="Offline map data pipeline for Project Goliath.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    nodes = sub.add_parser(
        "nodes",
        help="steps 1-4: build land nodes, land_nodes.json, report.md "
        "and update ids.lock.json",
    )
    nodes.add_argument("--data-dir", default="data/map", type=Path)
    nodes.add_argument(
        "--out-dir", default="tools/map_pipeline/out", type=Path
    )
    nodes.add_argument(
        "--check",
        action="store_true",
        help="never write; exit 1 if ids.lock.json would change",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "nodes":
            return run_nodes(args.data_dir, args.out_dir, args.check)
    except PipelineFailure as failure:
        print_errors(failure.errors)
        return 1
    except PipelineError as error:
        print_errors([error])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
