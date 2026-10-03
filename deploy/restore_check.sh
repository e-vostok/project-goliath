#!/usr/bin/env bash
# restore_check.sh — репетиция восстановления: поднять дамп во временную
# базу внутри живого контейнера db и сверить её с настоящей базой.
# Живая база НЕ изменяется — только читается; временная база всегда
# удаляется в конце.
#
#   ./deploy/restore_check.sh                 проверить самый свежий дамп
#   ./deploy/restore_check.sh <файл.dump>     проверить конкретный дамп
#
# Выход: 0 = PASS, 1 = FAIL (с указанием причины).
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1
# shellcheck disable=SC1090,SC1091
. "$SCRIPT_DIR/lib.sh"

DUMP=""
TMPDB=""
FAILS=0

ok() { echo "  PASS  $*"; }
not_ok() {
  echo "  FAIL  $*" >&2
  FAILS=$((FAILS + 1))
}
note() { echo "  ПРИМЕЧАНИЕ: $*"; }

usage() {
  cat <<'EOF'
Использование: ./deploy/restore_check.sh [файл дампа]

Без аргумента проверяется самый свежий дамп из ~/backups/daily
(если там пусто — из ~/backups/predeploy).
EOF
}

drop_tmpdb() {
  if [ -n "$TMPDB" ]; then
    "${COMPOSE[@]}" exec -T db psql -U "$(env_get POSTGRES_USER)" -d postgres \
      -qc "DROP DATABASE IF EXISTS \"$TMPDB\"" >/dev/null 2>&1 || true
  fi
}
trap drop_tmpdb EXIT

# Row counts per table: informational, one line per table present in
# either database.
print_table_counts() {
  local live_db="$1" tables t c_rest c_live
  tables="$(
    {
      pg_scalar "$TMPDB" "SELECT tablename FROM pg_tables WHERE schemaname='public'"
      pg_scalar "$live_db" "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    } | grep -v '^$' | sort -u || true
  )"
  echo
  printf '  %-36s %12s %12s\n' "таблица" "в_бэкапе" "в_живой_базе"
  printf '  %-36s %12s %12s\n' "------------------------------------" "------------" "------------"
  while IFS= read -r t; do
    case "$t" in
      '' | *[!a-zA-Z0-9_]*) continue ;;
    esac
    c_rest="$(pg_scalar "$TMPDB" "SELECT count(*) FROM public.\"$t\"" || true)"
    c_live="$(pg_scalar "$live_db" "SELECT count(*) FROM public.\"$t\"" || true)"
    printf '  %-36s %12s %12s\n' "$t" "${c_rest:-—}" "${c_live:-—}"
  done <<< "$tables"
}

main() {
  case "${1:-}" in
    -h | --help) usage; exit 0 ;;
    "") ;;
    *) DUMP="$1" ;;
  esac

  if [ -z "$DUMP" ]; then
    DUMP="$(ls -t "$BACKUP_DIR"/daily/goliath-daily-*.dump 2>/dev/null | head -n 1 || true)"
    if [ -z "$DUMP" ]; then
      DUMP="$(ls -t "$BACKUP_DIR"/predeploy/goliath-predeploy-*.dump 2>/dev/null | head -n 1 || true)"
    fi
  fi
  if [ -z "$DUMP" ]; then
    die "ни одного дампа не найдено в $BACKUP_DIR/daily и $BACKUP_DIR/predeploy — сначала сделайте ./deploy/backup.sh"
  fi
  if [ ! -f "$DUMP" ]; then
    die "файл дампа не найден: $DUMP"
  fi

  need_cmd docker
  local pg_user pg_db
  pg_user="$(env_get POSTGRES_USER)"
  pg_db="$(env_get POSTGRES_DB)"
  if [ -z "$pg_user" ] || [ -z "$pg_db" ]; then
    die "в $ENV_FILE не заданы POSTGRES_USER/POSTGRES_DB."
  fi
  if ! db_running; then
    die "контейнер db не запущен — некуда восстанавливать проверочную копию. Проверьте: ${COMPOSE[*]} ps"
  fi

  TMPDB="restore_check_$(date +%s)_$$"
  echo "==> проверяем дамп: $DUMP"
  echo "==> временная база: $TMPDB (будет удалена автоматически)"

  if ! "${COMPOSE[@]}" exec -T db psql -U "$pg_user" -d postgres -qc "CREATE DATABASE \"$TMPDB\""; then
    die "не удалось создать временную базу $TMPDB в контейнере db"
  fi

  if ! "${COMPOSE[@]}" exec -T db pg_restore -U "$pg_user" -d "$TMPDB" \
       --no-owner --exit-on-error < "$DUMP"; then
    echo "FAIL: pg_restore завершился с ошибкой — дамп повреждён или неполный: $DUMP" >&2
    exit 1
  fi
  echo "Восстановление прошло без ошибок. Сверяем с живой базой '$pg_db':"

  # 1) Same table set — only meaningful when schema versions match.
  local rev_live rev_rest
  rev_live="$(pg_scalar "$pg_db" 'SELECT version_num FROM alembic_version' || true)"
  rev_rest="$(pg_scalar "$TMPDB" 'SELECT version_num FROM alembic_version' || true)"
  if [ -n "$rev_live" ] && [ "$rev_live" = "$rev_rest" ]; then
    local t_live t_rest
    t_live="$(pg_scalar "$pg_db" "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public'" || true)"
    t_rest="$(pg_scalar "$TMPDB" "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public'" || true)"
    if [ -n "$t_rest" ] && [ "$t_live" = "$t_rest" ]; then
      ok "набор таблиц в схеме public совпадает с живой базой"
    else
      not_ok "набор таблиц отличается от живой базы (live: ${t_live:-?}; backup: ${t_rest:-?})"
    fi
  else
    note "версии схемы различаются (живая: ${rev_live:-?}, бэкап: ${rev_rest:-?}) — сверку набора таблиц пропускаем"
  fi

  # 2) game_clock must contain exactly one row.
  local gc
  gc="$(pg_scalar "$TMPDB" 'SELECT count(*) FROM game_clock' || true)"
  if [ "$gc" = "1" ]; then
    ok "game_clock содержит ровно 1 строку"
  else
    not_ok "game_clock содержит '${gc:-?}' строк — должна быть ровно 1"
  fi

  # 3) provinces count equals the live database.
  local p_live p_rest
  p_live="$(pg_scalar "$pg_db" 'SELECT count(*) FROM provinces' || true)"
  p_rest="$(pg_scalar "$TMPDB" 'SELECT count(*) FROM provinces' || true)"
  if [ -n "$p_rest" ] && [ "$p_live" = "$p_rest" ]; then
    ok "provinces: $p_rest строк — как в живой базе"
  else
    not_ok "provinces: в бэкапе ${p_rest:-?}, в живой базе ${p_live:-?}"
  fi

  print_table_counts "$pg_db"

  echo
  if [ "$FAILS" -eq 0 ]; then
    echo "PASS: дамп годится к восстановлению — $DUMP"
    exit 0
  fi
  echo "FAIL: найдено проблем: $FAILS — $DUMP" >&2
  exit 1
}

main "$@"
