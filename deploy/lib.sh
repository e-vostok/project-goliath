#!/usr/bin/env bash
# Shared helpers for deploy/*.sh. This file is SOURCED by each script near
# its top; it is never executed on its own.
# shellcheck shell=bash

# Cron starts scripts with a minimal PATH — pin it explicitly so docker,
# git, age and rclone are found the same way from cron and from SSH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:${HOME}/.local/bin:${HOME}/bin"
umask 077

# Repo root = parent of the directory holding this file. All compose and
# git commands run from there so relative paths always mean the same thing.
GOLIATH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
cd "$GOLIATH_ROOT" || exit 1

if [ "$(id -u)" -eq 0 ]; then
  echo "ОШИБКА: этот скрипт нельзя запускать от root." >&2
  echo "Зайдите на сервер под пользователем deploy и повторите команду." >&2
  exit 1
fi

# Overridable locations (used by smoke_local.sh to point at a throwaway
# env file / backup dir).
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

die() {
  echo "ОШИБКА: $*" >&2
  exit 1
}

need_cmd() {
  # need_cmd <binary> [custom message]
  if ! command -v "$1" >/dev/null 2>&1; then
    die "${2:-Не найдена команда '$1'. Установите её и повторите.}"
  fi
}

env_get() {
  # Read ONE key from $ENV_FILE without sourcing it (the file may contain
  # secrets; sourcing it would also execute whatever is inside). Last
  # occurrence wins, surrounding quotes are stripped. Always exits 0.
  local key="$1" val
  val="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  printf '%s' "$val"
}

db_container_id() {
  "${COMPOSE[@]}" ps -q db 2>/dev/null | head -n 1
}

db_running() {
  local cid running
  cid="$(db_container_id)"
  if [ -z "$cid" ]; then
    return 1
  fi
  running="$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || true)"
  [ "$running" = "true" ]
}

wait_db_healthy() {
  # Wait until the db container reports healthy (compose healthcheck
  # pg_isready). Bounded so a broken container fails the deploy instead
  # of hanging it.
  local cid status i
  for ((i = 1; i <= 60; i++)); do
    cid="$(db_container_id)"
    if [ -n "$cid" ]; then
      status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
      if [ "$status" = "healthy" ]; then
        return 0
      fi
    fi
    sleep 2
  done
  echo "ОШИБКА: контейнер db не стал healthy за 120 секунд." >&2
  return 1
}

pg_scalar() {
  # pg_scalar <database> <sql> -> single value (empty on error)
  "${COMPOSE[@]}" exec -T db psql -U "$(env_get POSTGRES_USER)" -d "$1" \
    -v ON_ERROR_STOP=1 -tAc "$2" 2>/dev/null
}
