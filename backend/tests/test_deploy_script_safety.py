"""
Safety guard for the ops scripts under ``deploy/`` (0.10.0, unit 1).

After the disk incident of 2026-10-24 the rule is: automatic cleanup
touches ONLY the build cache via ``docker builder prune -a -f --filter
until=72h``. Nothing in deploy/ may call ``system prune`` or pass
``--volumes`` — either can destroy the database volume
``goliath_pgdata``. Pure file reads, no database needed.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SH = DEPLOY_DIR / "deploy.sh"

FORBIDDEN = ("system prune", "--volumes")


def _scripts() -> list[Path]:
    scripts = sorted(DEPLOY_DIR.glob("*.sh"))
    assert scripts, "deploy/*.sh not found — wrong REPO_ROOT?"
    return scripts


def test_deploy_sh_prunes_build_cache() -> None:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "builder prune" in text, (
        "deploy.sh lost the automatic build-cache prune "
        "(prune_build_cache, 0.10.0 unit 1)"
    )


def test_deploy_sh_calls_prune_once_after_smoke_check() -> None:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    main_body = text[text.index("main() {") :]
    calls = main_body.count("prune_build_cache")
    assert calls == 1, (
        f"prune_build_cache must be called exactly once in main(), got {calls}"
    )
    assert main_body.index("smoke_check") < main_body.index("prune_build_cache"), (
        "prune_build_cache must run after smoke_check"
    )
    assert main_body.index("prune_build_cache") < main_body.index("==> Deploy OK"), (
        "prune_build_cache must run before the final 'Deploy OK' block"
    )


def test_no_dangerous_prune_in_deploy_scripts() -> None:
    for script in _scripts():
        text = script.read_text(encoding="utf-8")
        for bad in FORBIDDEN:
            assert bad not in text, (
                f"{script.name}: forbidden '{bad}' — it can destroy the "
                f"database volume; use 'docker builder prune' only"
            )
