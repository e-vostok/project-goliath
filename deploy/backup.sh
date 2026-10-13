#!/usr/bin/env bash
# backup.sh — дамп базы PostgreSQL и (опционально) шифрованная копия
# вне сервера.
#
#   ./deploy/backup.sh --tag daily               ежедневный бэкап (из cron),
#                                                с внешней копией
#   ./deploy/backup.sh --tag predeploy --local-only
#                                                быстрый бэкап перед деплоем,
#                                                только локально
#
# Коды выхода: 0 — всё хорошо; 1 — ошибка; 2 — локальный дамп есть, но
# внешняя копия не настроена; 3 — внешняя копия настроена, но не
# установлены age/rclone.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1
# shellcheck disable=SC1090,SC1091
. "$SCRIPT_DIR/lib.sh"

TAG="daily"
LOCAL_ONLY=0
BACKUP_CFG="$HOME/.config/goliath/backup.env"
PARTIAL=""
FINAL=""

usage() {
  cat <<'EOF'
Использование: ./deploy/backup.sh [--tag daily|predeploy] [--local-only]

  --tag daily|predeploy   тип бэкапа (по умолчанию daily); влияет на папку
                          и на срок хранения: daily — 14 штук, predeploy — 7.
  --local-only            не отправлять копию вне сервера.
EOF
}

log_line() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*" >> "$BACKUP_DIR/backup.log" 2>/dev/null || true
}

bfail() {
  log_line "FAIL ($TAG): $*"
  echo "ОШИБКА: $*" >&2
  exit 1
}

on_err() {
  local rc=$?
  trap - ERR
  log_line "FAIL ($TAG): прервано, код $rc"
  echo "ОШИБКА: backup.sh прерван (код $rc). Локальный дамп может быть не создан." >&2
  exit "$rc"
}
trap on_err ERR

cleanup_partial() {
  if [ -n "$PARTIAL" ]; then
    rm -f "$PARTIAL" || true
  fi
}
trap cleanup_partial EXIT

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --tag)
        if [ -z "${2:-}" ]; then die "после --tag нужно значение daily или predeploy"; fi
        TAG="$2"
        shift 2
        ;;
      --tag=*) TAG="${1#*=}"; shift ;;
      --local-only) LOCAL_ONLY=1; shift ;;
      -h | --help) usage; exit 0 ;;
      *) die "неизвестный аргумент: $1 (справка: ./deploy/backup.sh --help)" ;;
    esac
  done
  case "$TAG" in
    daily | predeploy) ;;
    *) die "неизвестный --tag '$TAG': допустимо daily или predeploy" ;;
  esac
}

offsite_send() {
  # Encrypt the local dump with the recipient's PUBLIC age key and stream
  # it into rclone — no plaintext temp file ever touches the disk.
  local remote_name="$FINAL_NAME.dump.age" remote_path remote_size
  remote_path="$BACKUP_RCLONE_REMOTE/$remote_name"
  echo "==> внешняя копия: шифруем и отправляем -> $remote_path"
  if ! age -r "$BACKUP_AGE_RECIPIENT" < "$FINAL" | rclone rcat "$remote_path"; then
    bfail "не удалось отправить копию вне сервера (age | rclone rcat $remote_path). Локальный дамп на месте: $FINAL"
  fi
  remote_size="$(rclone lsl "$remote_path" 2>/dev/null | awk '{print $1}' || true)"
  if ! printf '%s' "$remote_size" | grep -qE '^[1-9][0-9]*$'; then
    bfail "внешняя копия $remote_path пустая или не появилась после загрузки"
  fi
  echo "Внешняя копия загружена ($remote_size байт)."
  if ! rclone delete --min-age "${BACKUP_OFFSITE_KEEP_DAYS}d" --include 'goliath-*.dump.age' "$BACKUP_RCLONE_REMOTE"; then
    echo "ПРЕДУПРЕЖДЕНИЕ: не удалось удалить старые копии в $BACKUP_RCLONE_REMOTE — проверьте вручную." >&2
  fi
}

main() {
  parse_args "$@"

  # Offsite settings live in the user's own config file, NOT in .env —
  # it contains no app secrets and may be safely sourced.
  BACKUP_AGE_RECIPIENT=""
  BACKUP_RCLONE_REMOTE=""
  BACKUP_OFFSITE_KEEP_DAYS="30"
  if [ -f "$BACKUP_CFG" ]; then
    # shellcheck disable=SC1090,SC1091
    . "$BACKUP_CFG"
    BACKUP_OFFSITE_KEEP_DAYS="${BACKUP_OFFSITE_KEEP_DAYS:-30}"
  fi

  need_cmd docker

  local pg_user pg_db
  pg_user="$(env_get POSTGRES_USER)"
  pg_db="$(env_get POSTGRES_DB)"
  if [ -z "$pg_user" ] || [ -z "$pg_db" ]; then
    die "в $ENV_FILE не заданы POSTGRES_USER/POSTGRES_DB — без них дамп не сделать."
  fi
  if ! db_running; then
    die "контейнер db не запущен — нечего бэкапить. Проверьте: ${COMPOSE[*]} ps"
  fi

  mkdir -p "$BACKUP_DIR/$TAG"
  chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/$TAG" 2>/dev/null || true

  local stamp keep
  stamp="$(date '+%Y%m%d-%H%M%S')"
  FINAL_NAME="goliath-$TAG-$stamp"
  PARTIAL="$BACKUP_DIR/$TAG/$FINAL_NAME.dump.partial"
  FINAL="$BACKUP_DIR/$TAG/$FINAL_NAME.dump"

  echo "==> снимаем дамп базы '$pg_db' -> $FINAL"
  # The dump contains player data: it must be 600 from the moment it is
  # created, not only after the final chmod — umask 077 in a subshell so
  # the rest of the script keeps the shared default (see lib.sh).
  if ! ( umask 077; "${COMPOSE[@]}" exec -T db pg_dump -U "$pg_user" -d "$pg_db" --no-owner --format=custom > "$PARTIAL" ); then
    bfail "pg_dump внутри контейнера db завершился с ошибкой — дамп не создан."
  fi
  if [ ! -s "$PARTIAL" ]; then
    bfail "pg_dump вернул пустой файл ($PARTIAL) — дамп не создан."
  fi
  # Prove the dump is readable BEFORE it gets its final name.
  if ! "${COMPOSE[@]}" exec -T db pg_restore --list < "$PARTIAL" > /dev/null; then
    bfail "дамп не читается: 'pg_restore --list' по $PARTIAL завершился с ошибкой."
  fi
  mv "$PARTIAL" "$FINAL"
  PARTIAL=""
  chmod 600 "$FINAL" 2>/dev/null || true
  local size
  size="$(du -h "$FINAL" | cut -f1)"
  echo "Дамп готов: $FINAL ($size)"

  # Retention by count: keep the newest N dumps of this tag.
  case "$TAG" in
    daily) keep=14 ;;
    predeploy) keep=7 ;;
  esac
  ls -t "$BACKUP_DIR/$TAG/goliath-$TAG-"*.dump 2>/dev/null \
    | tail -n "+$((keep + 1))" \
    | while IFS= read -r old; do
        rm -f "$old"
        echo "Удалён старый дамп (храним $keep): $old"
      done || true

  # The local dump is good — record it even if the offsite leg fails.
  date '+%Y-%m-%dT%H:%M:%S%z' > "$BACKUP_DIR/LAST_OK"

  if [ "$LOCAL_ONLY" -eq 1 ]; then
    log_line "OK ($TAG): $FINAL ($size), локально"
    echo "Готово (только локальная копия)."
    return 0
  fi

  if [ -z "$BACKUP_AGE_RECIPIENT" ] || [ -z "$BACKUP_RCLONE_REMOTE" ]; then
    log_line "WARN ($TAG): внешняя копия не настроена; локальный дамп $FINAL"
    {
      echo "==================== ВНИМАНИЕ ===================="
      echo "ВНЕШНЯЯ КОПИЯ НЕ НАСТРОЕНА. Локальный дамп есть"
      echo "($FINAL), но при гибели сервера данные будут потеряны."
      echo "Настройка: docs/deploy_runbook.md, раздел 8 (файл $BACKUP_CFG)."
      echo "================================================="
    } >&2
    exit 2
  fi

  local tool
  for tool in age rclone; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      log_line "FAIL ($TAG): нет команды $tool"
      echo "ОШИБКА: внешняя копия настроена, но команда '$tool' не найдена." >&2
      echo "Установите: sudo apt-get install -y age rclone" >&2
      exit 3
    fi
  done

  offsite_send
  log_line "OK ($TAG): $FINAL ($size), внешняя копия $BACKUP_RCLONE_REMOTE/$FINAL_NAME.dump.age"
  echo "Бэкап завершён: локальная копия + внешняя."
}

main "$@"
