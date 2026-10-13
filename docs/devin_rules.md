Devin working rules (standing rules for every task)
These rules apply to every TZ. A TZ states only the task-specific facts and may override a rule explicitly.
Git and PR (always, no exceptions)
- One branch per task from the CURRENT `origin/main`, named `<prefix>/<n>-<slug>` (the TZ gives the prefix and name). Commit in small steps and push to `origin` after EVERY commit (`git push -u origin <branch>`).
- At the end ALWAYS open a PR to `main` (squash merge) and put the report into the PR description. Never merge, never deploy, never touch the server or any production `.env`.
- Never conclude that a tool is unavailable without checking. Open the PR with the first method that works: (1) your built-in GitHub/PR tool or integration; (2) `gh pr create` (check `gh --version` and `gh auth status`); (3) the GitHub REST API with `curl` and the token from the environment or the git credential helper (`POST /repos/e-vostok/project-goliath/pulls`). Only if all three fail: report the exact error of each and print the URL `https://github.com/e-vostok/project-goliath/compare/main...<branch>`; this is a failure to report, never a normal outcome.
- The report must contain the PR URL and the remote head hash (`git rev-parse origin/<branch>`). Never claim a PR or a push without them.
No GitHub CI GitHub Actions workflows are manual-only. Do not wait for them and do not report on them. Your own local test run is the quality gate, and the counts in your report are the evidence.
Tests: scope by what you touched
- Write at most ONE new test per changed behaviour (a new rule, a new patch type, a bug fix = failing test first). No test matrices, no coverage target. Tests that touch the database or the tick use the real in-memory database and the fixtures in `backend/tests/fixtures/` (Anti-Mock Guard); never mock repositories or sessions.
- Run, once at the end, only the suites that the diff touches:
  - `backend/**`: the backend suite on SQLite; the PostgreSQL run only if models, migrations, queries or the startup sync were touched.
  - `frontend/**`: `npm test` and `npm run build`.
  - `tools/map_pipeline/**` or `data/map/**`: the map_pipeline tests and the pipeline `--check` (INV-M1…M10).
  - `configs/**`: `pytest tests/test_configs_validity.py`.
  - `deploy/**`, `docker*`, `Dockerfile*`, dependency or lock files: a local `docker compose build`.
  - Docs-only: nothing.
- If a suite fails, fix and re-run the failed tests, then the touched-area set once. Do not re-run suites that the diff does not touch.
Guard rails (unchanged)
- Foreign keys only to `00_core` tables; no direct SQL mutation of another module's tables (use its `service.py`); all balance numbers live in `configs/<slug>.yaml` and are validated by `config_schema.py`; tick calculations are registered only through `TickOrchestrator` in one of the 5 `TickPhase` values; map ids are never reused or renumbered (`ids.lock.json` is append-only in spirit).
- No new Alembic revision, environment variable or dependency unless the TZ says so.
- Forbidden paths unless the TZ explicitly allows them: `deploy/`, `docker*`, `Dockerfile*`, `.env*`, `*.lock`, `backend/pyproject.toml` (except the version line), `frontend/package.json` and its lock (except the version line), `.github/`.
- Commit messages: `<type>(<slug>): <summary>`.
Audit (one command, one line in the report) `git diff --stat origin/main...HEAD -- deploy docker* Dockerfile* '.env*' '*.lock' backend/pyproject.toml frontend/package.json frontend/package-lock.json .github` Report `audit: clean` or list the files. Version-line-only changes in the pyproject/package files are fine.
Versions
- Only a PR that changes shipped behaviour, config or data bumps the version; tools-only and docs-only PRs do not (say `no bump`).
- Read the current version and the top of `changelog.md` on `main` first (the `02_bot` line also uses 0.5.x numbers). Take the next free PATCH (MINOR only if the TZ says), keep `backend/pyproject.toml`, `backend/src/main.py`, `frontend/package.json` + lock and `changelog.md` in sync, one changelog line.
Merge class (last line of every report)
- `ROUTINE: Project Owner may merge and deploy now` only if: the audit is clean, your suites are green, no map data / ids / database rows / startup sync / auth / tick engine changed, no new migration, env variable or dependency.
- Otherwise `NEEDS LEAD AI REVIEW: <one sentence why>`.
Rehearsal (only for tasks that change `data/map/**`, provinces or startup sync) Start the backend on PostgreSQL from the previous manifest and quote the line `01_map started (… added, … present, … retired removed)`.
When to STOP and ask Only if a prerequisite of the TZ is missing, a forbidden path must change, an invariant would break, or the TZ says STOP. Otherwise decide yourself and state the assumption in one line.
Report format (at most 8 lines, English, in the PR description and in the chat) PR URL and remote head; what changed (at most 3 lines); suites run with pass/fail counts (one line); `audit: …`; version or `no bump`; production impact in one sentence (what the Project Owner will see after deploy); last line = merge class. No narration of steps, no restating the task. Show images inline in the chat when the TZ asks for them.
