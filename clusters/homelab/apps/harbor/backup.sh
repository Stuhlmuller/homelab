#!/bin/sh
set -eu

umask 0077
cp /run/secrets/harbor/pgpass /tmp/pgpass
chmod 0600 /tmp/pgpass
trap 'rm -f /tmp/pgpass' EXIT
connection='host=harbor-postgres port=5432 user=harbor dbname=registry passfile=/tmp/pgpass connect_timeout=15'
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root=/backup/logical-backups
partial="${backup_root}/.${timestamp}.partial"
complete="${backup_root}/${timestamp}"
mkdir -p "$backup_root"
mkdir "$partial"
pg_dumpall --database="$connection" --globals-only \
  --no-role-passwords > "${partial}/globals.sql"
pg_dump --dbname="$connection" --format=custom \
  --file="${partial}/registry.dump"
pg_restore --list "${partial}/registry.dump" >/dev/null
(
  cd "$partial"
  sha256sum globals.sql registry.dump > SHA256SUMS
  sha256sum --check SHA256SUMS
)
mv "$partial" "$complete"
echo "verified Harbor database backup ${timestamp}"
find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20[0-9][0-9][01][0-9][0-3][0-9]T[0-2][0-9][0-5][0-9][0-5][0-9]Z' \
  -mtime +13 -exec rm -r -- {} +
find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '.*.partial' -mtime +1 -exec rm -r -- {} +
