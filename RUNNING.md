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
```

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
