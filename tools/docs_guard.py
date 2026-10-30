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
G7  Format of docs/** (excluding docs/04_VERSIONS/**, docs/05_RESEARCH/**,
    docs/06_DESIGN/**): UTF-8 without BOM, LF endings, one trailing
    newline, no trailing spaces, no tabs, at most one blank line in a row,
    one H1 per file, no heading level jump, bullet marker "-", code fences
    carry a language, table rows have the header's column count. Content
    inside code fences is ignored except the fence line itself. Ratchet:
    the count of files with violations may only fall vs legacy_format.
G8  References in docs/** (excluding docs/04_VERSIONS/**): every
    backticked token starting with docs/, tools/, backend/, frontend/,
    configs/, deploy/ or data/ and containing no "*", "<", "{", space or
    "..." must exist as a tracked file or folder. Ratchet: the count of
    misses may only fall vs legacy_refs.
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


G7_DIRS_EXCLUDE = DUP_EXCLUDE_PREFIXES
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
HEAD_RE = re.compile(r"^\s*(#{1,6})\s")
H1_RE = re.compile(r"^\s*#\s")
BULLET_RE = re.compile(r"^\s*[*+]\s")
G8_SKIP_CHARS = ("*", "<", "{", " ", "...")
G8_PREFIXES = ("docs/", "tools/", "backend/", "frontend/", "configs/", "deploy/", "data/")


def _g7_file(path: Path, index_eol: str | None) -> list[str]:
    """Return the list of format problems in one markdown file.

    index_eol is the blob's line-ending from `git ls-files --eol` ("lf",
    "crlf", "mixed") or None for untracked files / non-git roots; the
    "LF endings" rule applies to the committed content, not to what a
    Windows autocrlf checkout happens to look like on disk. All other
    checks run on line-ending-normalized text.
    """
    raw = path.read_bytes()
    problems: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("bom")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["not-utf8"]
    if index_eol == "crlf" or (index_eol is None and "\r" in text):
        problems.append("crlf")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n") or text.endswith("\n\n"):
        problems.append("trailing-newline")
    lines = text.split("\n")
    in_fence = False
    blank_run = 0
    prev_head = 0
    h1 = 0
    table_pipes: int | None = None
    for i, line in enumerate(lines[:-1] if text.endswith("\n") else lines, 1):
        fence = FENCE_RE.match(line)
        if fence:
            if not in_fence and not fence.group(2).strip():
                problems.append(f"{i}: bare-fence")
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line != line.rstrip():
            problems.append(f"{i}: trailing-space")
        if "\t" in line:
            problems.append(f"{i}: tab")
        if not line.strip():
            blank_run += 1
            if blank_run >= 2:
                problems.append(f"{i}: blank-run")
        else:
            blank_run = 0
        head = HEAD_RE.match(line)
        if head:
            level = len(head.group(1))
            if prev_head and level > prev_head + 1:
                problems.append(f"{i}: heading-jump")
            prev_head = level
            if level == 1:
                h1 += 1
        if BULLET_RE.match(line):
            problems.append(f"{i}: bullet-marker")
        if line.lstrip().startswith("|"):
            pipes = line.count("|")
            if table_pipes is None:
                table_pipes = pipes
            elif pipes != table_pipes:
                problems.append(f"{i}: table-cols")
        else:
            table_pipes = None
    if h1 != 1:
        problems.append(f"h1-count={h1}")
    return problems


def _index_eols(root: Path) -> dict[str, str] | None:
    import subprocess

    try:
        res = subprocess.run(
            ["git", "ls-files", "--eol", "docs/"],
            cwd=root, capture_output=True, text=True, timeout=20,
        )
    except OSError:
        return None
    if res.returncode != 0:
        return None
    eols: dict[str, str] = {}
    for line in res.stdout.splitlines():
        m = re.match(r"i/(\S+)\s+w/\S+\s+attr/\S*\s*\t(.+)", line)
        if m:
            eols[m.group(2)] = m.group(1)
    return eols


def g7(root: Path, budget: dict, out: list[str], notes: list[str]) -> None:
    eols = _index_eols(root)
    bad: dict[str, list[str]] = {}
    for p in (root / "docs").rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(G7_DIRS_EXCLUDE):
            continue
        problems = _g7_file(p, eols.get(rel) if eols is not None else None)
        if problems:
            bad[rel] = problems
    limit = budget["legacy_format"]
    if len(bad) > limit:
        out.append(f"G7 files with format violations: {len(bad)} > legacy {limit}")
        for rel in sorted(bad):
            out.append(f"G7   {rel}: {', '.join(bad[rel][:8])}")
    elif len(bad) < limit:
        notes.append(f"G7 note: count fell to {len(bad)} (legacy {limit}); lower legacy_format")
    else:
        notes.append(f"G7 ok: {len(bad)} files with format violations (legacy {limit})")


def _tracked_files(root: Path) -> set[str] | None:
    import subprocess

    try:
        res = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=20
        )
    except OSError:
        return None
    if res.returncode != 0:
        return None
    return {line.strip() for line in res.stdout.splitlines() if line.strip()}


def g8(root: Path, budget: dict, out: list[str], notes: list[str]) -> None:
    tracked = _tracked_files(root)
    misses: list[str] = []
    for p in (root / "docs").rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("docs/04_VERSIONS/"):
            continue
        for m in BACKTICK_RE.finditer(p.read_text(encoding="utf-8")):
            tok = m.group(1)
            if any(c in tok for c in G8_SKIP_CHARS):
                continue
            if not tok.startswith(G8_PREFIXES):
                continue
            tok = tok.rstrip(".,;:")
            prefix = tok if tok.endswith("/") else tok + "/"
            if tracked is not None:
                ok = tok in tracked or any(t.startswith(prefix) for t in tracked)
            else:
                ok = (root / tok).exists()
            if not ok:
                misses.append(f"{rel}: {tok}")
    limit = budget["legacy_refs"]
    if len(misses) > limit:
        out.append(f"G8 missing references: {len(misses)} > legacy {limit}")
        for line in sorted(misses):
            out.append(f"G8   {line}")
    elif len(misses) < limit:
        notes.append(f"G8 note: count fell to {len(misses)} (legacy {limit}); lower legacy_refs")
    else:
        notes.append(f"G8 ok: {len(misses)} missing references (legacy {limit})")


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
    notes: list[str] = []
    g1(root, budget, out)
    g2(root, budget, out)
    g3(root, budget, out)
    g4(root, out)
    g5(root, out)
    g6(root, out)
    g7(root, budget, out, notes)
    g8(root, budget, out, notes)
    for line in out + notes:
        print(line)
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
