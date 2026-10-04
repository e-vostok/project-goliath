#!/usr/bin/env bash
# deploy.sh — обновить боевой сервер до нужного тега или ветки.
#
#   ./deploy/deploy.sh                 последний origin/main
#   ./deploy/deploy.sh --ref v0.5.0    конкретный тег
#   ./deploy/deploy.sh --ref main      ветка (берётся её состояние на GitHub)
#   ./deploy/deploy.sh --check         только предполётные проверки, без деплоя
#   ./deploy/deploy.sh --force         разрешить деплой в окне 23:55–00:10 МСК
#
# При любом сбое после старта скрипт печатает БЛОК ОТКАТА с точными
# командами. Автоматического отката нет — решение принимает человек.
#
# Весь код — в функциях, а `main "$@"` стоит в самом конце: так bash
# прочитывает файл целиком до начала работы, и `git checkout` на новую
# версию не может «подменить» скрипт прямо во время его выполнения.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1
# shellcheck disable=SC1090,SC1091
. "$SCRIPT_DIR/lib.sh"

LOCK_FILE="/tmp/goliath-deploy.lock"
FREE_KB_MIN=3145728 # 3 ГБ на корневом разделе, в килобайтах

REF=""
FORCE=0
CHECK_ONLY=0
PROBLEMS=0
DEPLOY_STARTED=0
PREV_SHA=""
PREDEPLOY_DUMP=""

usage() {
  cat <<'EOF'
Использование: ./deploy/deploy.sh [--ref <тег|ветка>] [--force] [--check]

  без аргументов   обновиться до последнего origin/main
  --ref v0.5.0     конкретный тег;  --ref main — ветка (её состояние на GitHub)
  --check          только предполётные проверки, без деплоя
  --force          разрешить деплой в окне 23:55–00:10 по Москве
EOF
}

problem() {
  echo "  - $*" >&2
  PROBLEMS=$((PROBLEMS + 1))
}

print_rollback() {
  if [ "$DEPLOY_STARTED" -ne 1 ]; then
    return 0
  fi
  {
    echo
    echo "================ ЧТО ДЕЛАТЬ: ОТКАТ ================="
    echo "Деплой прерван. Автоматического отката НЕТ — решение за вами."
    echo "Предыдущий коммит: ${PREV_SHA:-неизвестен}"
    echo "Бэкап базы перед деплоем: ${PREDEPLOY_DUMP:-не создавался}"
    echo
    echo "1) Откат КОДА (обычно этого достаточно):"
    echo "     cd $GOLIATH_ROOT"
    echo "     git checkout --detach ${PREV_SHA:-<sha>}"
    echo "     docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --build"
    echo
    echo "2) Откат БАЗЫ (если миграции успели пройти и данные испорчены):"
    echo "     docs/deploy_runbook.md, раздел 7 «Откат» — восстановление"
    echo "     из бэкапа, указанного выше."
    echo "===================================================="
  } >&2
}

deploy_fail() {
  echo "ОШИБКА: $*" >&2
  print_rollback
  exit 1
}

on_err() {
  local rc=$?
  trap - ERR
  echo "ОШИБКА: deploy.sh прерван — команда завершилась с кодом $rc." >&2
  print_rollback
  exit "$rc"
}
trap on_err ERR

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --ref)
        if [ -z "${2:-}" ]; then die "после --ref нужен тег или ветка"; fi
        REF="$2"
        shift 2
        ;;
      --ref=*) REF="${1#*=}"; shift ;;
      --force) FORCE=1; shift ;;
      --check) CHECK_ONLY=1; shift ;;
      -h | --help) usage; exit 0 ;;
      *) die "неизвестный аргумент: $1 (справка: ./deploy/deploy.sh --help)" ;;
    esac
  done
}

take_lock() {
  need_cmd flock "не найдена команда 'flock' (пакет util-linux)."
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    die "деплой уже выполняется (блокировка $LOCK_FILE занята). Дождитесь окончания текущего деплоя."
  fi
}

check_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    problem "файл $ENV_FILE не найден. Создайте его из шаблона: cp .env.prod.example .env && chmod 600 .env"
    return
  fi
  local mode val key
  mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo '?')"
  if [ "$mode" != "600" ]; then
    problem "права на $ENV_FILE сейчас $mode, нужно 600 — выполните: chmod 600 $ENV_FILE"
  fi
  if [ ! -O "$ENV_FILE" ]; then
    problem "файл $ENV_FILE принадлежит другому пользователю — выполните: sudo chown $(id -un) $ENV_FILE"
  fi
  for key in DOMAIN ACME_EMAIL POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD \
             DATABASE_URL JWT_SECRET_KEY VK_APP_SECRET ADMIN_VK_USER_IDS; do
    val="$(env_get "$key")"
    if [ -z "$val" ]; then
      problem "в $ENV_FILE не задан $key"
    elif printf '%s' "$val" | grep -qi 'CHANGE_ME'; then
      problem "в $ENV_FILE значение $key — заглушка CHANGE_ME: впишите настоящее"
    fi
  done
  val="$(env_get APP_ENV)"
  if [ "$val" != "production" ]; then
    problem "APP_ENV должен быть равен production, а в $ENV_FILE: '${val:-пусто}'"
  fi
  echo "  ADMIN_ALLOW_RESET = $(env_get ADMIN_ALLOW_RESET) (информация: при true из админ-панели доступен сброс мира)"
}

check_git_clean() {
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    problem "в репозитории есть незакоммиченные изменения (git status). Их нужно убрать или закоммитить вручную."
  fi
}

check_docker() {
  if ! docker info > /dev/null 2>&1; then
    problem "docker недоступен текущему пользователю (команда 'docker info' не сработала). Проверьте, что пользователь состоит в группе docker и перелогиньтесь."
  fi
}

check_disk() {
  local avail
  avail="$(df -Pk / 2>/dev/null | awk 'NR==2{print $4}')"
  if [ -z "$avail" ] || [ "$avail" -lt "$FREE_KB_MIN" ]; then
    problem "на диске / мало места (свободно ${avail:-?} КБ, нужно минимум 3 ГБ). Освободите место: docker system prune, старые бэкапы."
  fi
}

check_time_window() {
  local hm
  hm="$(TZ=Europe/Moscow date '+%H%M')"
  if [ "$FORCE" -eq 1 ]; then
    return 0
  fi
  if [ "$((10#$hm))" -ge 2355 ] || [ "$((10#$hm))" -le 10 ]; then
    problem "сейчас $hm по Москве — запретное окно 23:55–00:10 вокруг суточного хода. Подождите до 00:11 МСК или повторите с флагом --force."
  fi
}

preflight() {
  echo "==> предполётные проверки"
  need_cmd git
  need_cmd docker
  need_cmd curl
  check_env_file
  check_git_clean
  check_docker
  check_disk
  check_time_window
  if [ "$PROBLEMS" -ne 0 ]; then
    echo "Найдено проблем: $PROBLEMS. Исправьте пункты выше и запустите команду снова." >&2
    exit 1
  fi
  echo "Проверки пройдены — ok to deploy."
}

resolve_ref() {
  # Tags win over branches, then origin/<name>, then the literal value
  # (covers 'origin/main', full SHAs and other revisions).
  local want="$1" cand sha
  if [ -z "$want" ]; then
    want="origin/main"
  fi
  for cand in "refs/tags/$want" "refs/remotes/origin/$want" "$want"; do
    if sha="$(git rev-parse -q --verify "$cand^{commit}" 2>/dev/null)"; then
      printf '%s' "$sha"
      return 0
    fi
  done
  return 1
}

predeploy_backup() {
  if db_running; then
    echo "==> бэкап базы перед деплоем (predeploy, только локально)"
    bash "$SCRIPT_DIR/backup.sh" --tag predeploy --local-only
    PREDEPLOY_DUMP="$(ls -t "$BACKUP_DIR"/predeploy/goliath-predeploy-*.dump 2>/dev/null | head -n 1 || true)"
  else
    echo "==> контейнер db не запущен — бэкап перед деплоем пропускаем"
    echo "    (это нормально при ПЕРВОМ деплое: базы ещё нет)."
  fi
}

checkout_ref() {
  local target
  git fetch --tags --prune origin
  if ! target="$(resolve_ref "$REF")"; then
    deploy_fail "неизвестный ref '$REF' — нет ни тега, ни ветки с таким именем на GitHub."
  fi
  git checkout --detach "$target"
  git log -1 --format='==> обновляемся на %h — %s'
}

rebuild_stack() {
  "${COMPOSE[@]}" build
  "${COMPOSE[@]}" stop backend
  "${COMPOSE[@]}" up -d db
  wait_db_healthy
  echo "==> миграции базы (alembic upgrade head)"
  if ! "${COMPOSE[@]}" run --rm -T migrate; then
    deploy_fail "миграции не прошли: '${COMPOSE[*]} run --rm migrate' завершился с ошибкой. Код уже новый, база — в прежнем виде."
  fi
  "${COMPOSE[@]}" up -d --wait --wait-timeout 300
}

smoke_check() {
  local domain body i code ok_health=0
  domain="$(env_get DOMAIN)"
  echo "==> проверяем https://$domain/api/v1/health (до 12 попыток по 10 с;"
  echo "    при первом деплое выпуск сертификата занимает около минуты)"
  body=""
  for ((i = 1; i <= 12; i++)); do
    body="$(curl -fsS --max-time 10 "https://$domain/api/v1/health" 2>/dev/null || true)"
    if printf '%s' "$body" | grep -q '"status":"ok"'; then
      ok_health=1
      echo "    health: ok (попытка $i)"
      break
    fi
    if [ "$i" -lt 12 ]; then
      sleep 10
    fi
  done
  if [ "$ok_health" -ne 1 ]; then
    echo "---- последние логи caddy и backend ----" >&2
    "${COMPOSE[@]}" logs --tail=50 caddy backend >&2 || true
    echo "-----------------------------------------" >&2
    deploy_fail "https://$domain/api/v1/health не ответил \"status\":\"ok\" за 2 минуты."
  fi
  code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 10 "https://$domain/" 2>/dev/null || echo '000')"
  if [ "$code" != "200" ]; then
    echo "---- последние логи caddy и backend ----" >&2
    "${COMPOSE[@]}" logs --tail=50 caddy backend >&2 || true
    echo "-----------------------------------------" >&2
    deploy_fail "https://$domain/ ответил кодом $code, ожидали 200."
  fi
  echo "    главная страница отвечает 200"
}

main() {
  parse_args "$@"
  take_lock
  preflight
  if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "Режим --check: деплой не запускался."
    exit 0
  fi

  DEPLOY_STARTED=1
  PREV_SHA="$(git rev-parse HEAD)"
  predeploy_backup
  checkout_ref
  rebuild_stack
  smoke_check

  echo "==> Deploy OK"
  git log -1 --format='Текущий коммит: %h — %s'
  "${COMPOSE[@]}" ps
  echo "Деплой завершён успешно."
}

main "$@"
