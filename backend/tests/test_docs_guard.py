"""Tests for tools/docs_guard.py (docs drift guard)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "docs_guard.py"

REQUIRED_FILES = [
    "changelog.md",
    "backend/pyproject.toml",
    "backend/src/main.py",
    "frontend/package.json",
    "frontend/package-lock.json",
]
REQUIRED_DIRS = [
    "data/map",
    "tools/map_pipeline",
    "frontend/src/shared",
    "frontend/src/app",
]


def run_guard(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv on repo tooling, no untrusted input
        [sys.executable, str(GUARD), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def make_copy(tmp_path: Path) -> Path:
    for d in ("docs", "tools", "backend/tests", "configs", "deploy"):
        shutil.copytree(ROOT / d, tmp_path / d)
    for rel in REQUIRED_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    for rel in REQUIRED_DIRS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_docs_guard_passes_on_repository() -> None:
    result = run_guard(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_docs_guard_detects_injected_duplicate(tmp_path: Path) -> None:
    make_copy(tmp_path)

    line = "Строка-проверка дубля длиной больше ста двадцати символов для стража. " * 3
    assert len(line.strip()) >= 120
    for rel in ("docs/03_ROADMAP/00_core.md", "docs/03_ROADMAP/01_map.md"):
        target = tmp_path / rel
        target.write_text(
            target.read_text(encoding="utf-8") + "\n" + line + "\n",
            encoding="utf-8",
        )

    result = run_guard(tmp_path)
    assert result.returncode == 1
    assert "G3" in result.stdout


def test_docs_guard_detects_format_violation(tmp_path: Path) -> None:
    make_copy(tmp_path)
    budget_path = tmp_path / "tools/docs_budget.json"
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    budget["legacy_format"] = 0
    budget_path.write_text(json.dumps(budget, ensure_ascii=False), encoding="utf-8")

    target = tmp_path / "docs/03_ROADMAP/map_pipeline.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "line with trailing space \n",
        encoding="utf-8",
    )

    result = run_guard(tmp_path)
    assert result.returncode == 1
    assert "G7" in result.stdout
    assert "map_pipeline.md" in result.stdout


def test_docs_guard_detects_missing_reference(tmp_path: Path) -> None:
    make_copy(tmp_path)
    budget_path = tmp_path / "tools/docs_budget.json"
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    budget["legacy_refs"] = 0
    budget_path.write_text(json.dumps(budget, ensure_ascii=False), encoding="utf-8")

    target = tmp_path / "docs/03_ROADMAP/map_pipeline.md"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nSee `docs/02_SYSTEM_SPECS/definitely_missing_spec_file.md`.\n",
        encoding="utf-8",
    )

    result = run_guard(tmp_path)
    assert result.returncode == 1
    assert "G8" in result.stdout
    assert "definitely_missing_spec_file.md" in result.stdout


def test_docs_guard_g1_measures_lf_normalized_size(tmp_path: Path) -> None:
    """A CRLF working tree must not trip the byte budget (PROC-3).

    git autocrlf rewrites LF blobs to CRLF on Windows, inflating
    ``st_size`` by one byte per line; G1 measures the LF-normalized
    size so the same checkout answers identically on every OS.
    """
    make_copy(tmp_path)

    rel = "docs/03_ROADMAP/map_pipeline.md"
    target = tmp_path / rel
    lf_bytes = target.read_bytes().replace(b"\r\n", b"\n")

    # Shrink the copy's budget so raw CRLF size is over but LF is under.
    budget_path = tmp_path / "tools/docs_budget.json"
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    budget["max_bytes"][rel] = len(lf_bytes) + 5
    budget_path.write_text(json.dumps(budget, ensure_ascii=False), encoding="utf-8")

    target.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))
    assert target.stat().st_size > budget["max_bytes"][rel]
    assert len(lf_bytes) <= budget["max_bytes"][rel]

    result = run_guard(tmp_path)
    assert "G1" not in result.stdout
