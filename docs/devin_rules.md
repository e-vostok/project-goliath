Devin working rules (standing rules for every task)
These rules apply to every TZ. A TZ states only the task-specific facts and may override a rule explicitly. Rules are cited by ID.

Docs-only tasks
- DOC-1. A task that changes only documentation files is docs-only: `docs/**` (version files, handoff and checkpoint files, Bible, Spec, Roadmap, workflow documents, design PNG/HTML in `docs/06_DESIGN/**`), `changelog.md`, `README*`; and a release PR whose only non-document change is the version strings (`backend/pyproject.toml`, `backend/src/main.py`, `frontend/package.json`, `frontend/package-lock.json`).
- DOC-2. For such a task run NO checks of any kind: no test suites (backend, frontend, PostgreSQL), no typecheck, no build, no lint, no `bash -n`, no audit command, no grep proofs, no docker, do not start or wait for CI, do not re-read or re-verify the files after writing them. Commit exactly what the TZ supplies, push, open the PR.
- DOC-3. The only check allowed in a docs-only task is `python tools/docs_guard.py`, and only if the diff touches `docs/devin_rules.md`, `docs/prompts_templates.md`, `docs/development_workflow.md`, `docs/PROJECT_STATE.md`, any `docs/03_ROADMAP/*.md` or `tools/docs_budget.json`. It takes about a second.
- DOC-4. Only other exception: the TZ itself says «verify» about a named statement — check that one thing and nothing else.
- DOC-5. Report, at most 3 lines: PR URL and remote head; what changed (one line, say `no bump` or the version set); `no checks (docs-only)`; last line `ROUTINE: Project Owner may merge now`.
- DOC-6. If the diff touches anything else (code, config, tests, deploy, Docker, migrations), it is not docs-only: the normal rules below apply.
- DOC-7. Handoff PRs (`docs/PROJECT_STATE.md`, `docs/04_VERSIONS/*.md`, the three workflow documents) are docs-only: commit the files exactly as the TZ supplies them (whole files, no rewording), `no bump`, no checks. Only when the TZ explicitly asks you to verify named facts, check those statements against `main`, correct what is wrong in place, and list each correction in the report (one line each).

Git and PR (always, no exceptions)
- GIT-1. One branch per task from the CURRENT `origin/main`, named `<prefix>/<n>-<slug>` (the TZ gives the prefix and name). Commit in small steps and push to `origin` after EVERY commit (`git push -u origin <branch>`).
- GIT-2. One work unit is one PR. Split a unit into several PRs only when the TZ says so (large units: server first, client second).
- GIT-3. At the end ALWAYS open a PR to `main` (squash merge) and put the report into the PR description. Never merge, never deploy, never touch the server or any production `.env`.
- GIT-4. Never conclude that a tool is unavailable without checking. Open the PR with the first method that works: (1) your built-in GitHub/PR tool or integration; (2) `gh pr create` (check `gh --version` and `gh auth status`); (3) the GitHub REST API with `curl` and the token from the environment or the git credential helper (`POST /repos/e-vostok/project-goliath/pulls`). Only if all three fail: report the exact error of each and print the URL `https://github.com/e-vostok/project-goliath/compare/main...<branch>`; this is a failure to report, never a normal outcome.
- GIT-5. The report must contain the PR URL and the remote head hash (`git rev-parse origin/<branch>`). Never claim a PR or a push without them.
- GIT-6. GitHub Actions workflows are manual-only. Do not wait for them and do not report on them. Your own local test run is the quality gate, and the counts in your report are the evidence.
- GIT-7. Commit messages: `<type>(<slug>): <summary>`.
- GIT-8. Report format (at most 8 lines, English, in the PR description and in the chat; docs-only tasks use DOC-5): PR URL and remote head; what changed (at most 3 lines); test lines per TEST-5; `audit: …`; version or `no bump`; production impact in one sentence (what the Project Owner will see after deploy); last line = merge class (SAFE-7). No narration of steps, no restating the task. Show images inline in the chat when the TZ asks for them.
- GIT-9. When a TZ names a work item of the current version (`docs/04_VERSIONS/<X.Y.0>.md`), tick that item in the same PR (like the Roadmap tick). Touch no other line of that file unless the TZ says so.

Tests
- TEST-1. At most ONE new test per changed behaviour; no matrices, no coverage target; real in-memory DB and `backend/tests/fixtures/` (Anti-Mock Guard); never mock repositories or sessions.
- TEST-2. Run once, at the end, after the last edit, only this tier set:
  - Always: the tests that cover the touched module (`backend/tests/modules/<module>/`, or the files that import the touched code) plus the guard files `backend/tests/test_configs_validity.py`, `test_model_migration_drift.py`, `test_admin_table_coverage.py`, `test_lock_files.py`, `test_alembic_env.py`, `test_app_startup.py`, `test_docs_guard.py` (find the real paths; `docs_guard` verifies they exist).
  - The full backend SQLite suite only if the diff touches shared code: `backend/src/core/**`, `backend/src/main.py`, `backend/tests/conftest.py`, `backend/tests/fixtures/**`, `backend/alembic/**`, dependency or lock files.
  - PostgreSQL: only if models, migrations, locking or numbering queries, or the startup sync were touched; run the `*_pg.py` tests of the touched module plus the PostgreSQL drift test, not all PostgreSQL tests.
  - Frontend: one final command from `frontend/`: `npm run typecheck && npm test -- <touched paths> && npm run build` (use the runner's path filter; check `package.json`). Full `npm test` only if `frontend/src/shared/**`, `frontend/src/app/**`, the API client, the token file or `package.json` changed.
  - `tools/map_pipeline/**` or `data/map/**`: map_pipeline tests and `--check`. `configs/**`: `pytest tests/test_configs_validity.py`. Deploy, Docker or dependency files: `docker compose build` (`UNVERIFIED` if Docker is missing).
- TEST-3. Only the release PR runs everything once: full backend on SQLite and PostgreSQL, full frontend, map_pipeline, docker build, `python tools/docs_guard.py`.
- TEST-4. On failure: fix, re-run the failed tests, then the tier set once. Never re-run a suite that already passed after the last edit or that the diff does not touch. Never wait for GitHub CI (manual, release only).
- TEST-5. Report one line per command: command, counts, wall time. Nothing else about tests.

Guard rails
- SAFE-1. Foreign keys only to `00_core` tables; no direct SQL mutation of another module's tables (use its `service.py`); all balance numbers live in `configs/<slug>.yaml` and are validated by `config_schema.py`; tick calculations are registered only through `TickOrchestrator` in one of the 5 `TickPhase` values; map ids are never reused or renumbered (`ids.lock.json` is append-only in spirit).
- SAFE-2. No new Alembic revision, environment variable or dependency unless the TZ says so.
- SAFE-3. Forbidden paths unless the TZ explicitly allows them: `deploy/`, `docker*`, `Dockerfile*`, `.env*`, `*.lock`, `backend/pyproject.toml` (except the version line), `frontend/package.json` and its lock (except the version line), `.github/`.
- SAFE-4. Audit (one command, one line in the report; not for docs-only tasks): `git diff --stat origin/main...HEAD -- deploy docker* Dockerfile* '.env*' '*.lock' backend/pyproject.toml frontend/package.json frontend/package-lock.json .github`. Report `audit: clean` or list the files. Version-line-only changes in the pyproject/package files are fine.
- SAFE-5. Rehearsal (only for tasks that change `data/map/**`, provinces or startup sync): start the backend on PostgreSQL from the previous manifest and quote the line `01_map started (… added, … present, … retired removed)`.
- SAFE-6. STOP and ask only if a prerequisite of the TZ is missing, a forbidden path must change, an invariant would break, or the TZ says STOP. Otherwise decide yourself and state the assumption in one line.
- SAFE-7. Merge class (last line of every report): `ROUTINE: Project Owner may merge and deploy now` only if the audit is clean, your suites are green, no map data / ids / database rows / startup sync / auth / tick engine changed, no new migration, env variable or dependency. Otherwise `NEEDS LEAD AI REVIEW: <one sentence why>`.
- SAFE-8. If TEST-2 requires the PostgreSQL tier and no PostgreSQL is reachable, run every other tier, write `PostgreSQL: UNVERIFIED (<reason>)` in the report, set the class to `NEEDS LEAD AI REVIEW`, and add the line `Owner: run CI on this branch before merging` (Actions → CI → Run workflow). Never mark such a task `ROUTINE`.

UI
- UI-1. Every app window except the map fits exactly into 910 px of width — no horizontal scrollbar, nothing sticking out; design columns and controls to shrink and wrap, not to scroll sideways.
- UI-2. Build every window by `docs/02_SYSTEM_SPECS/00_core_ui.md` (four window types, sizes, tokens, states, texts) and only from the shared components in `frontend/src/shared/ui/`; no hard-coded colours, sizes or fonts outside the token file; never set the window height anywhere except the shell. A TZ that builds or changes a window names the approved mockup; if it does not, STOP and ask (SAFE-6). A new custom element is added to the UI Spec first, then to code.
- UI-3. Mockups live in the repo: any task that changes how a window looks is built against the PNG files in `docs/06_DESIGN/<version>/`. The report contains a table «экран → совпадает / расхождения» with the PNG name. If the PNG and the text of the task disagree, the PNG wins; report the difference.
- UI-4. Any change of a form or a filter layout is checked in a real browser at the window's width (910 px): screenshots + the measurement of overflow and control heights are part of the report; jsdom tests do not prove layout.

Versions
- VER-1. A normal PR does not change any version string. It adds one line (player- or operator-visible effect, at most 140 chars; no line for pure refactor, tests or docs) under `## [Unreleased]` of `changelog.md`.
- VER-2. Only the release PR sets the same version in `backend/pyproject.toml`, `backend/src/main.py`, `frontend/package.json`, `frontend/package-lock.json` and turns `[Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD — <Title>` (at most 8 bullets, merged). A hotfix release is a PATCH with its own release PR and tag. `tag` and `deploy` stay Owner commands.
- VER-3. Tag: only when the Project Owner says `tag` after the release PR is merged. Then `git fetch origin`, create the annotated tag `vX.Y.Z` on the head of `origin/main`, push it, confirm with `git ls-remote --tags origin vX.Y.Z` and quote that line in the report. Never move or delete an existing tag.
