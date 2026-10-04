# RUNNING — Local Dev (HTTPS on localhost, no VK Tunnel)

Prereqs (once): `pip install -e ".[dev]"` in `backend/`, `npm install` in `frontend/`.

## 1. Create `.env` in the repo root (gitignored — never commit)

The backend loads exactly this file — the path is pinned in `src/main.py`
(`load_dotenv(dotenv_path=<repo root>/.env)`), so a `.env` placed anywhere
else, including `backend/.env`, is ignored.

Put the values in `.env`:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./dev.db
DATABASE_URL_TEST=
VK_APP_SECRET=<real secret from dev.vk.com>
JWT_SECRET_KEY=<any random 32+ byte string>
ADMIN_VK_USER_IDS=<comma-separated VK user ids of admins; empty = no admins>
ADMIN_ALLOW_RESET=true
```

`ADMIN_ALLOW_RESET` gates `POST /api/v1/admin/state/reset` (DEP-4): set
`true` locally so the admin panel can reset the world; unset/disabled it
fails closed with 403 `RESET_DISABLED`. On the production server it stays
`false` until a reset is actually needed.

`APP_ENV` controls the production startup guard: `production`/`prod`/
`staging` make the app refuse to boot on a weak `JWT_SECRET_KEY`, a
SQLite/loopback `DATABASE_URL` or a placeholder `VK_APP_SECRET`. Leave it
**unset** locally — unset means no checks.

## 2. Apply migrations (run from `backend/`)

`alembic` reads `DATABASE_URL` from the shell, not from `.env`, so pass it inline.

PowerShell:

```powershell
cd backend
$env:DATABASE_URL="sqlite+aiosqlite:///./dev.db"; alembic upgrade head
```

Bash:

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:///./dev.db" alembic upgrade head
```

Creates `backend/dev.db` with all tables.

## 3. Start the backend (run from `backend/`)

```powershell
cd backend
uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
```

`.env` is loaded automatically from the repo root (`load_dotenv()` in `src/main.py`). Health check: `http://127.0.0.1:8000/health` → `{"status":"ok"}`. Port 8000 matches the Vite proxy target for `/api`.

## 4. Start the frontend (run from `frontend/`)

```powershell
cd frontend
npm run dev
```

Vite prints and serves **`https://localhost:5173/`** (self-signed cert via `@vitejs/plugin-basic-ssl`; accept the browser warning once). Register `https://localhost:5173` as the dev address in the VK Mini App settings.

## 5. PostgreSQL tests (`pytest -m postgres`)

The `postgres`-marked suite verifies the app end-to-end on a real PostgreSQL database: it **drops and rebuilds the public schema** of the target DB, migrates with Alembic, and deletes rows between tests. It is opt-in and destructive — never point it at a dev/prod database.

Create a dedicated throwaway database once (psql as a superuser):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres -c "CREATE DATABASE goliath_test;"
```

Then set `DATABASE_URL_TEST` in the repo-root `.env` (or the shell) — the database name **must** end with `_test` and differ from `DATABASE_URL`'s database:

```dotenv
DATABASE_URL_TEST=postgresql+asyncpg://postgres:<password>@127.0.0.1:5432/goliath_test
```

PowerShell (run from `backend/`):

```powershell
cd backend
$env:DATABASE_URL_TEST="postgresql+asyncpg://postgres:<password>@127.0.0.1:5432/goliath_test"
pytest -m postgres            # only the PG suite
pytest                        # full suite; PG tests included when the URL is set
$env:REQUIRE_POSTGRES_TESTS="1"; pytest -m postgres   # fail instead of skip when unset
```

Without `DATABASE_URL_TEST` the PG tests report as skipped. `PG_TEST_REVISION` (default `head`) overrides the Alembic target the schema fixture migrates to — used to red-check the PG drift guard (e.g. `$env:PG_TEST_REVISION="0004"; pytest -m postgres tests/test_model_migration_drift_pg.py` must fail listing the three `nations` profile columns).

## 6. Production stack: local smoke test

The production topology (Postgres + one-shot `migrate` + backend + Caddy) lives in `docker-compose.prod.yml`. To verify it end-to-end on this machine you need Docker Engine/Desktop with the compose plugin and `curl`, then:

```bash
bash deploy/smoke_local.sh
```

The script generates a throwaway env file, builds both images, boots the stack on an EMPTY database, checks that `/` serves the SPA, `/api/*` reaches the backend, migrations land at head (`game_clock` seeded, `provinces` == manifest nodes), the backend log is clean and the service returns to healthy after a restart — then tears everything down with `down -v`.

On a real server: copy `.env.prod.example` to `.env` (chmod 600), fill in real values, then `docker compose -f docker-compose.prod.yml up -d --build --wait`.

The full production procedure — server setup, `deploy.sh`, backups, rollback, troubleshooting — lives in `docs/deploy_runbook.md` (Russian).

## 7. CI (GitHub Actions)

`.github/workflows/ci.yml` runs four jobs on every pull request and every push to `main`; all must be green to merge:

- `backend` — full `pytest` on Python 3.12 against a real `postgres:16` service container (`DATABASE_URL_TEST=…/goliath_test`, `REQUIRE_POSTGRES_TESTS=1`): the `postgres`-marked suite can never silently skip.
- `frontend` — Node 20: `npm ci`, `npm run typecheck`, `npm test`, `npm run build`.
- `map_pipeline` — `pytest tools/map_pipeline/tests`, including the `real_data` suite on the committed map inputs.
- `docker` — validates `docker-compose.prod.yml` against `.env.prod.example`, then runs the DEP-1 runtime acceptance (`deploy/smoke_local.sh`) on the Linux runner.

No secrets are used; the workflow token has `contents: read` only and jobs run under `pull_request`, never `pull_request_target`.

## 8. Как обновить зависимости бэкенда

Версии всех Python-пакетов зафиксированы в `backend/requirements.lock` (боевые зависимости) и `backend/requirements-dev.lock` (боевые + инструменты разработки). Боевой Docker-образ и CI ставят ровно эти версии — обновление делается только осознанно.

**Lock-файлы никогда не правятся руками** — они пересобираются командой `uv` (установка: `pip install uv`). Выполняется из папки `backend/`:

```bash
cd backend
uv pip compile pyproject.toml --upgrade --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o requirements.lock
uv pip compile pyproject.toml --extra dev --upgrade --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o requirements-dev.lock
```

`--upgrade` поднимает все пакеты до самых свежих версий, разрешённых рамками в `pyproject.toml`. Чтобы обновить только одну библиотеку — поднимите её нижнюю границу в `pyproject.toml` и выполните те же команды без `--upgrade`.

Затем:

1. Прогнать тесты: `pytest` из папки `backend/`.
2. Закоммитить **оба** lock-файла вместе с `pyproject.toml` одним коммитом — CI упадёт, если `pyproject.toml` изменился, а lock'и нет.

Нюанс локальной установки: lock собран под Linux (в нём `uvloop`, которого нет под Windows), поэтому на Windows ставьте зависимости как раньше — `pip install -e ".[dev]"`. На Linux/macOS можно ставить строго по lock: `pip install -e ".[dev]" -c requirements-dev.lock`.
