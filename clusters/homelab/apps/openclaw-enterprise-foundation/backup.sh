#!/bin/sh
# T051 must mount a quiesced, identity-checked recovery set at /recovery-material
# and an encrypted off-node destination at /backup before scheduling this script.
set -eu
umask 0077

material=/recovery-material
backup_root=/backup/openclaw-enterprise
for file in recovery.json postgres-root/tls.crt postgres-root/tls.key \
  postgres-admin/password postgres-migrator/password postgres-app/password \
  postgres-backup/password auth/secret gateway/occ bootstrap/output.json \
  journal/journal.json tenant/metadata.json agent/identity.json; do
  test -s "$material/$file" || { echo "incomplete recovery material: $file" >&2; exit 1; }
done
for directory in tenant/secrets agent/state; do
  test -d "$material/$directory" || exit 1
  test -n "$(find "$material/$directory" -type f -print -quit)" || exit 1
done
test ! -L "$material"
test -z "$(find "$material" ! -type f ! -type d -print -quit)" || exit 1
test -s /run/secrets/occ-postgres-backup/password
test -s /run/postgres-ca/tls.crt
mkdir -p /tmp /backup/openclaw-enterprise
password="$(cat /run/secrets/occ-postgres-backup/password)"
case "$password" in
  *[!A-Za-z0-9]*|'') echo 'invalid backup credential shape' >&2; exit 1 ;;
esac
printf 'occ-postgres.openclaw-system.svc.cluster.local:5432:*:occ_backup:%s\n' "$password" > /tmp/occ-pgpass
unset password
chmod 0600 /tmp/occ-pgpass
trap 'rm -f /tmp/occ-pgpass' EXIT
connection='host=occ-postgres.openclaw-system.svc.cluster.local port=5432 user=occ_backup dbname=openclaw_enterprise sslmode=verify-full sslrootcert=/run/postgres-ca/tls.crt passfile=/tmp/occ-pgpass connect_timeout=15'
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$backup_root/.$timestamp.partial"
complete="$backup_root/$timestamp"
mkdir "$partial"
trap 'rm -f /tmp/occ-pgpass; rm -rf "$partial"' EXIT
pg_dump --dbname="$connection" --format=custom --file="$partial/database.dump"
pg_restore --list "$partial/database.dump" >/dev/null
cp /scripts/database-bootstrap.sql "$partial/database-bootstrap.sql"
cp -a "$material" "$partial/material"
(
  cd "$partial"
  find database.dump database-bootstrap.sql material -type f -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)
mv "$partial" "$complete"
trap 'rm -f /tmp/occ-pgpass' EXIT
echo "verified OpenClaw Enterprise recovery set $timestamp"
