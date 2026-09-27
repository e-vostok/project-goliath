# RUNNING — Local Dev (HTTPS on localhost, no VK Tunnel)

Prereqs (once): `pip install -e ".[dev]"` in `backend/`, `npm install` in `frontend/`.

## 1. Create `backend/.env` (gitignored — never commit)

```powershell
Copy-Item .env.example backend\.env
```

Then set the values in `backend/.env`:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./dev.db
DATABASE_URL_TEST=
VK_APP_SECRET=<real secret from dev.vk.com>
JWT_SECRET_KEY=<any random 32+ byte string>
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

`.env` is loaded automatically (`load_dotenv()` in `src/main.py`). Health check: `http://127.0.0.1:8000/health` → `{"status":"ok"}`. Port 8000 matches the Vite proxy target for `/api`.

## 4. Start the frontend (run from `frontend/`)

```powershell
cd frontend
npm run dev
```

Vite prints and serves **`https://localhost:5173/`** (self-signed cert via `@vitejs/plugin-basic-ssl`; accept the browser warning once). Register `https://localhost:5173` as the dev address in the VK Mini App settings.
