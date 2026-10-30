"""Tests for tools/docs_guard.py (docs drift guard)."""

from __future__ import annotations

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
    return subprocess.run(
        [sys.executable, str(GUARD), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_docs_guard_passes_on_repository() -> None:
    result = run_guard(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_docs_guard_detects_injected_duplicate(tmp_path: Path) -> None:
    for d in ("docs", "tools", "backend/tests", "configs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    for rel in REQUIRED_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    for rel in REQUIRED_DIRS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)

    line = "Строка-проверка дубля длиной больше ста двадцати символов для стража. " * 3
    assert len(line.strip()) >= 120
    for rel in ("docs/03_ROADMAP/00_core.md", "docs/03_ROADMAP/01_map.md"):
        target = tmp_path / rel
        target.write_text(target.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")

    result = run_guard(tmp_path)
    assert result.returncode == 1
    assert "G3" in result.stdout
