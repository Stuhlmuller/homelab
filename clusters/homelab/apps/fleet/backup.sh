#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root="${1:-/backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pending="$(mktemp -d "${backup_root}/.pending-XXXXXXXX")"
trap 'rm -rf -- "$pending"' EXIT

mysqldump --defaults-extra-file=/run/secrets/fleet-backup/client.cnf \
  --single-transaction --quick --skip-lock-tables \
  --no-tablespaces --set-gtid-purged=OFF --max-allowed-packet=512M \
  --result-file="${pending}/fleet.sql" fleet
test -s "${pending}/fleet.sql"
tail -n 2 "${pending}/fleet.sql" | grep -q '^-- Dump completed on '
(
  cd "$pending"
  sha256sum fleet.sql > fleet.sql.sha256
  sha256sum --check --status fleet.sql.sha256
)

# Rename the whole verified set atomically; an existing set is never replaced.
mv -T -- "$pending" "${backup_root}/fleet-${stamp}"
# Failed backup attempts must never prune earlier recovery sets.
find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name 'fleet-????????T??????Z' -mtime +13 -print0 |
  while IFS= read -r -d '' old; do
    rm -rf -- "$old"
  done
printf 'Published verified Fleet database backup fleet-%s\n' "$stamp"
