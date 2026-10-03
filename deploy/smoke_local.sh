#!/usr/bin/env bash
# DEP-1 acceptance: boot the production stack locally on an EMPTY
# database and assert the wiring end-to-end. All secrets are throwaway,
# generated per run — this script never touches a real deployment.
#
# Requires: Docker Engine/Desktop with the compose plugin, curl.
# Usage:    bash deploy/smoke_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."

for tool in docker curl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "FATAL: '$tool' not found"; exit 2; }
done

ENV_FILE_PATH="$(mktemp)"
PASS=0
FAIL=0

ok()  { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

dc() {
  ENV_FILE="$ENV_FILE_PATH" \
    docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE_PATH" "$@"
}

dump_logs() {
  echo "==> failure: tail of each service log"
  for svc in db migrate backend caddy; do
    echo "----- docker compose logs $svc -----"
    dc logs --tail 100 "$svc" 2>&1 || true
  done
}

cleanup() {
  echo "==> tearing down (down -v)"
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$ENV_FILE_PATH"
}
trap cleanup EXIT

# ── throwaway env file ────────────────────────────────────────────────
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    head -c 24 /dev/urandom | od -An -vtx1 | tr -d ' \n'
  fi
}

POSTGRES_USER="goliath"
POSTGRES_DB="goliath"
POSTGRES_PASSWORD="$(gen_secret)"

cat > "$ENV_FILE_PATH" <<EOF
POSTGRES_USER=$POSTGRES_USER
POSTGRES_DB=$POSTGRES_DB
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$POSTGRES_DB
JWT_SECRET_KEY=$(gen_secret)
VK_APP_SECRET=smoke_throwaway_vk_secret
ADMIN_VK_USER_IDS=
DOMAIN=localhost
ACME_EMAIL=smoke@example.invalid
APP_ENV=production
ADMIN_ALLOW_RESET=false
EOF

psql_scalar() {
  dc exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1" | tr -d '[:space:]'
}

echo "==> docker compose config"
dc config -q && ok "compose file is valid" || bad "compose file invalid"

echo "==> building images and starting the stack (empty database)"
if dc up -d --build --wait; then
  ok "stack up: migrate exited 0, backend healthy, caddy healthy"
else
  bad "stack failed to come up (--wait returned non-zero)"
  dump_logs
  echo "RESULT: $PASS passed, $FAIL failed"
  exit 1
fi

# ── check 1: SPA over HTTPS through Caddy ─────────────────────────────
echo "==> check 1: GET https://localhost/ returns the SPA"
code="$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/ || true)"
body="$(curl -sk https://localhost/ || true)"
if [ "$code" = "200" ] && printf '%s' "$body" | grep -q 'id="root"'; then
  ok "GET / -> 200 with SPA html"
else
  bad "GET / -> $code (expected 200 + <div id=\"root\">)"
fi

# ── check 2: API reaches the backend through Caddy ────────────────────
echo "==> check 2: POST /api/v1/auth/vk -> application-level JSON error"
resp="$(curl -sk -w '\n%{http_code}' -X POST https://localhost/api/v1/auth/vk \
  -H 'Content-Type: application/json' \
  -d '{"launch_params":"garbage"}' || true)"
code="${resp##*$'\n'}"
body="${resp%$'\n'*}"
if [ "$code" != "502" ] && [ "$code" != "404" ] && [ "$code" != "000" ] \
   && printf '%s' "$body" | grep -q '"code"'; then
  ok "POST /api/v1/auth/vk -> $code JSON error from the backend (not a proxy error)"
else
  bad "POST /api/v1/auth/vk -> $code: ${body:0:200}"
fi

# ── check 3: database state ───────────────────────────────────────────
echo "==> check 3: alembic at head, game_clock seeded, provinces == manifest"
db_rev="$(psql_scalar 'SELECT version_num FROM alembic_version')"
head_rev="$(dc exec -T backend alembic heads 2>/dev/null | grep -oE '^[0-9a-z]+' | head -1 | tr -d '[:space:]')"
if [ -n "$db_rev" ] && [ "$db_rev" = "$head_rev" ]; then
  ok "alembic_version=$db_rev is at head"
else
  bad "alembic_version='$db_rev' != head '$head_rev'"
fi

gc="$(psql_scalar 'SELECT count(*) FROM game_clock WHERE id = 1')"
if [ "$gc" = "1" ]; then
  ok "game_clock row id=1 exists"
else
  bad "game_clock id=1 count='$gc' (expected 1)"
fi

expected="$(dc exec -T backend python -c \
  "import json; print(len(json.load(open('/app/data/map/manifest.json'))['nodes']))" \
  | tr -d '[:space:]')"
actual="$(psql_scalar 'SELECT count(*) FROM provinces')"
if [ -n "$expected" ] && [ "$actual" = "$expected" ]; then
  ok "provinces=$actual equals manifest nodes"
else
  bad "provinces=$actual != manifest nodes=$expected"
fi

# ── check 4: logs clean + backend restart keeps data ──────────────────
echo "==> check 4: no tracebacks; backend restart returns to healthy"
if dc logs backend 2>&1 | grep -qi 'traceback'; then
  bad "backend log contains a Traceback"
else
  ok "backend log has no Traceback (tick scheduler task did not crash)"
fi

dc restart backend >/dev/null
healthy="no"
for _ in $(seq 1 40); do
  cid="$(dc ps -q backend | head -1)"
  st="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
  if [ "$st" = "healthy" ]; then healthy="yes"; break; fi
  sleep 3
done
after="$(psql_scalar 'SELECT count(*) FROM provinces')"
if [ "$healthy" = "yes" ] && [ "$after" = "$expected" ]; then
  ok "backend restart -> healthy, provinces still $after"
else
  bad "backend restart: healthy=$healthy provinces=$after (expected $expected)"
fi

echo "=================================================="
echo "RESULT: $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
  dump_logs
fi
[ "$FAIL" -eq 0 ]
