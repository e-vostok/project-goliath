#!/usr/bin/env python3
"""Docs drift guard for project-goliath (stdlib only).

Checks G1-G6; prints one line per violation and exits 1, else exits 0.

G1  Size ratchet: every rule file and every file under the three doc trees
    stays within its byte budget in tools/docs_budget.json; every such file
    must have a budget entry.
G2  Roadmaps, Specs and Bibles must not contain a heading matching
    "Правила работы" or any phrase from the budget's forbidden_phrases.
G3  No identical line of >=120 characters in two or more files under docs/**
    (excluding changelog.md, docs/04_VERSIONS/**, docs/05_RESEARCH/**,
    docs/06_DESIGN/**). The count may only fall below legacy_duplicates.
G4  Every relative Markdown link and every backticked docs/, tools/,
    backend/tests/ path in the four rule files exists; every file named
    in TEST-2 exists.
G5  Every GIT|TEST|VER|DOC|SAFE|UI-<n> cited in docs/** (except
    docs/04_VERSIONS/**) is defined exactly once in docs/devin_rules.md;
    no duplicate definitions. A file may declare a family local with
    «PREFIX-N» (e.g. «UI-N») and then that family's IDs are not rule cites.
G6  backend/pyproject.toml, backend/src/main.py and frontend/package.json
    carry the same version, equal to the top released section of
    changelog.md; ## [Unreleased] is the first section.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RULE_FILES = [
    "docs/devin_rules.md",
    "docs/prompts_templates.md",
    "docs/development_workflow.md",
    "docs/PROJECT_STATE.md",
]
DOC_DIRS = ["docs/01_GAME_BIBLE", "docs/02_SYSTEM_SPECS", "docs/03_ROADMAP"]
DUP_EXCLUDE_PREFIXES = ("docs/04_VERSIONS/", "docs/05_RESEARCH/", "docs/06_DESIGN/")
DUP_EXCLUDE_FILES = {"changelog.md"}

ID_RE = re.compile(r"\b(GIT|TEST|VER|DOC|SAFE|UI)-(\d+)\b")
DEF_RE = re.compile(r"^\s*-\s+(GIT|TEST|VER|DOC|SAFE|UI)-(\d+)\.")
LOCAL_NS_RE = re.compile(r"«(GIT|TEST|VER|DOC|SAFE|UI)-N»")
HEADING_RE = re.compile(r"^\s*#{1,6}\s")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK_RE = re.compile(r"`([^`]+)`")
DUP_MIN_LEN = 120


def _check_path(root: Path, where: str, tok: str, out: list[str]) -> None:
    tok = tok.rstrip(".,);:")
    if tok.endswith("/**"):
        if not (root / tok[:-3]).is_dir():
            out.append(f"G4 {where}: missing {tok}")
    elif "*" in tok:
        if not list(root.glob(tok)):
            out.append(f"G4 {where}: no match for {tok}")
    elif not (root / tok).exists():
        out.append(f"G4 {where}: missing {tok}")


def g1(root: Path, budget: dict, out: list[str]) -> None:
    mb = budget["max_bytes"]
    covered = set(RULE_FILES)
    for d in DOC_DIRS:
        for p in (root / d).rglob("*"):
            if p.is_file():
                covered.add(p.relative_to(root).as_posix())
    for rel in sorted(covered):
        p = root / rel
        if rel not in mb:
            out.append(f"G1 {rel}: no budget entry")
        elif not p.is_file():
            out.append(f"G1 {rel}: file missing")
        elif (size := p.stat().st_size) > mb[rel]:
            out.append(f"G1 {rel}: {size} bytes > budget {mb[rel]}")


def g2(root: Path, budget: dict, out: list[str]) -> None:
    phrases = budget["forbidden_phrases"]
    for d in DOC_DIRS:
        for p in (root / d).rglob("*.md"):
            rel = p.relative_to(root).as_posix()
            text = p.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if HEADING_RE.match(line) and "Правила работы" in line:
                    out.append(f"G2 {rel}:{i}: forbidden heading {line.strip()[:100]}")
            for ph in phrases:
                if ph in text:
                    out.append(f"G2 {rel}: forbidden phrase {ph!r}")


def g3(root: Path, budget: dict, out: list[str]) -> None:
    seen: dict[str, set[str]] = {}
    for p in (root / "docs").rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        if rel in DUP_EXCLUDE_FILES or rel.startswith(DUP_EXCLUDE_PREFIXES):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if len(line) >= DUP_MIN_LEN:
                seen.setdefault(line, set()).add(rel)
    dupes = {line: files for line, files in seen.items() if len(files) >= 2}
    limit = budget["legacy_duplicates"]
    if len(dupes) > limit:
        out.append(f"G3 duplicate long lines: {len(dupes)} > legacy {limit}")
        for line in sorted(dupes):
            out.append(f"G3   {sorted(dupes[line])}: {line[:100]}")


def g4(root: Path, out: list[str]) -> None:
    for rel in RULE_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        for m in LINK_RE.finditer(text):
            link = m.group(1).split("#")[0]
            if link and "://" not in link and not (root / link).exists():
                out.append(f"G4 {rel}: dead link {link}")
        for m in BACKTICK_RE.finditer(text):
            for tok in m.group(1).split():
                if "<" in tok or "[" in tok:
                    continue
                if tok.startswith(("docs/", "tools/", "backend/tests/")):
                    _check_path(root, rel, tok, out)
    rules = (root / "docs/devin_rules.md").read_text(encoding="utf-8")
    t2 = rules.split("TEST-2.", 1)[1].split("TEST-3.")[0]
    for name in sorted(set(re.findall(r"test_\w+\.py", t2))):
        if not list((root / "backend/tests").rglob(name)):
            out.append(f"G4 TEST-2: {name} not found under backend/tests")
    if not list((root / "backend/tests").rglob("*_pg.py")):
        out.append("G4 TEST-2: no *_pg.py tests under backend/tests")
    if not (root / "backend/tests/modules").is_dir():
        out.append("G4 TEST-2: backend/tests/modules missing")
    for m in BACKTICK_RE.finditer(t2):
        for tok in m.group(1).split():
            if "<" in tok or "[" in tok:
                continue
            if tok.startswith(("docs/", "tools/", "backend/", "frontend/", "configs/", "data/")):
                _check_path(root, "TEST-2", tok, out)


def g5(root: Path, out: list[str]) -> None:
    text = (root / "docs/devin_rules.md").read_text(encoding="utf-8")
    defs: dict[str, int] = {}
    for line in text.splitlines():
        m = DEF_RE.match(line)
        if m:
            rid = f"{m.group(1)}-{m.group(2)}"
            if rid in defs:
                out.append(f"G5 {rid}: duplicate definition in devin_rules.md")
            defs[rid] = 1
    for p in (root / "docs").rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("docs/04_VERSIONS/"):
            continue
        t = p.read_text(encoding="utf-8")
        local = set(LOCAL_NS_RE.findall(t))
        for m in ID_RE.finditer(t):
            if m.group(1) in local:
                continue
            rid = f"{m.group(1)}-{m.group(2)}"
            if rid not in defs:
                out.append(f"G5 {rel}: cites undefined rule id {rid}")


def g6(root: Path, out: list[str]) -> None:
    py = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (root / "backend/pyproject.toml").read_text(encoding="utf-8"))
    mv = re.search(r'version\s*=\s*"([^"]+)"', (root / "backend/src/main.py").read_text(encoding="utf-8"))
    pj = json.loads((root / "frontend/package.json").read_text(encoding="utf-8")).get("version")
    vers = {"pyproject": py and py.group(1), "main.py": mv and mv.group(1), "package.json": pj}
    heads = re.findall(r"(?m)^## \[([^\]]+)\]", (root / "changelog.md").read_text(encoding="utf-8"))
    if not heads or heads[0] != "Unreleased":
        out.append("G6 changelog.md: first section is not [Unreleased]")
    released = next((h for h in heads if h != "Unreleased"), None)
    if len(set(vers.values())) != 1:
        out.append(f"G6 version mismatch: {vers}")
    elif released != vers["pyproject"]:
        out.append(f"G6 version {vers['pyproject']} != changelog top release {released}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="repository root (default: parent of tools/)")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    budget = json.loads((root / "tools/docs_budget.json").read_text(encoding="utf-8"))
    out: list[str] = []
    g1(root, budget, out)
    g2(root, budget, out)
    g3(root, budget, out)
    g4(root, out)
    g5(root, out)
    g6(root, out)
    for line in out:
        print(line)
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
