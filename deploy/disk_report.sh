#!/usr/bin/env bash
# disk_report.sh — read-only отчёт о занятом месте на боевом сервере.
#
#   bash deploy/disk_report.sh
#
# Скрипт ТОЛЬКО читает и печатает размеры: ничего не удаляет, не двигает,
# не пишет никуда, кроме stdout. Разделы, которым нужен root, идут через
# `sudo -n` (без запроса пароля): если sudo не настроен, вместо раздела
# печатается строка «needs sudo: ...». Выполните `sudo -v` перед запуском,
# чтобы получить полный отчёт.
#
# Не запускайте в окне 23:55–00:10 по Москве (в это время идёт суточный ход).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1
# shellcheck disable=SC1090,SC1091
. "$SCRIPT_DIR/lib.sh"

# lib.sh уже задаёт GOLIATH_ROOT (папка проекта, обычно /opt/goliath) и
# BACKUP_DIR (по умолчанию ~/backups, на сервере /home/deploy/backups).

SUDO_OK=0
if sudo -n true 2>/dev/null; then
  SUDO_OK=1
fi

section() {
  printf '\n===== %s =====\n' "$1"
}

# Команда без root: ошибку печатаем строкой, отчёт продолжается.
run() {
  "$@" 2>&1 || echo "(команда завершилась с ошибкой: $*)"
}

# Команда с root через sudo -n: при отказе — одна понятная строка,
# скрипт никогда не ждёт ввода пароля.
run_sudo() {
  if [ "$SUDO_OK" -eq 1 ]; then
    sudo -n "$@" 2>&1 || echo "(команда завершилась с ошибкой: sudo $*)"
  else
    echo "needs sudo: sudo $*"
  fi
}

echo "disk_report.sh — только чтение. $(date '+%Y-%m-%d %H:%M:%S %z')"
echo "Проект: $GOLIATH_ROOT | Бэкапы: $BACKUP_DIR | sudo: $([ "$SUDO_OK" -eq 1 ] && echo есть || echo нет)"

section "df -h /"
run df -h /

section "docker system df"
run docker system df

section "docker system df -v (образы, контейнеры, тома, кэш сборки)"
run docker system df -v

section "docker ps -a --size"
run docker ps -a --size

section "/var/lib/docker и подпапки"
run_sudo du -xsh /var/lib/docker
run_sudo bash -c 'for d in overlay2 volumes containers image buildkit; do du -xsh "/var/lib/docker/$d" 2>/dev/null; done'

section "Журналы контейнеров (json-логи, по убыванию)"
run_sudo bash -c 'du -sh /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -rh'

section "Данные и журналы Caddy"
run docker volume ls
run_sudo bash -c 'for v in goliath_caddy_data goliath_caddy_config; do du -xsh "/var/lib/docker/volumes/$v" 2>/dev/null || echo "(тома нет: $v)"; done'
echo "(журналы Caddy — в json-логе контейнера, раздел выше)"

section "Папка проекта и бэкапов"
run du -xsh "$GOLIATH_ROOT"
run du -xsh "$BACKUP_DIR"
run bash -c 'for d in "$1"/daily "$1"/predeploy; do du -xsh "$d" 2>/dev/null; done' _ "$BACKUP_DIR"
run bash -c 'ls -lhS "$1"/daily "$1"/predeploy 2>/dev/null | head -20 || true' _ "$BACKUP_DIR"

section "20 самых тяжёлых папок на /"
run_sudo bash -c 'du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -20'

section "Журнал системы и /var/log"
run_sudo journalctl --disk-usage
run_sudo du -xsh /var/log

section "Кэш apt"
run_sudo du -xsh /var/cache/apt

section "Файлы больше 200 МБ (20 самых тяжёлых)"
run_sudo bash -c 'find / -xdev -type f -size +200M -exec du -h {} + 2>/dev/null | sort -rh | head -20'

section "Готово"
echo "Пришлите весь вывод целиком разработчику. Ничего не было удалено."
