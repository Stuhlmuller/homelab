#!/bin/sh
# T051 must mount a quiesced, identity-checked recovery set at /recovery-material
# and an encrypted off-node destination at /backup before scheduling this script.
set -eu
umask 0077

material=/recovery-material
backup_root=/backup/openclaw-enterprise
stopped_marker() {
  jq -es 'length == 1 and (.[0] | type == "object" and .writerStopped == true and
    (.claimUid | type == "string" and length > 0))' "$1" >/dev/null 2>&1
}
material_manifest() (
  root="$1"
  test -d "$root" && test ! -L "$root" || exit 1
  find "$root" ! -type f ! -type d -exec false {} + >/dev/null 2>&1 || exit 1
  find "$root" -type f -links +1 -exec false {} + >/dev/null 2>&1 || exit 1
  cd "$root" || exit 1
  find . -printf '%y %p\0' > "$partial/.material-paths" || exit 1
  LC_ALL=C sort -z "$partial/.material-paths" || exit 1
  find . -type f -exec sha256sum -- {} + > "$partial/.material-hashes" || exit 1
  LC_ALL=C sort "$partial/.material-hashes"
)
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
stopped_marker "$material/recovery.json" || {
  echo 'recovery material lacks a stopped, identified writer' >&2
  exit 1
}
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
if test -e "$complete" || test -L "$complete"; then
  echo "backup destination already exists: $timestamp" >&2
  exit 1
fi
mkdir "$partial"
trap 'rm -f /tmp/occ-pgpass; rm -rf "$partial"' EXIT
# Reject a changed or replaced recovery tree instead of publishing a mixed snapshot.
material_manifest "$material" > "$partial/.material-before" || {
  echo 'recovery material changed during backup' >&2; exit 1;
}
pg_dump --dbname="$connection" --format=custom --file="$partial/database.dump"
pg_restore --list "$partial/database.dump" >/dev/null
cp /scripts/database-bootstrap.sql "$partial/database-bootstrap.sql"
cp -a "$material" "$partial/material"
if ! material_manifest "$material" > "$partial/.material-after" ||
   ! material_manifest "$partial/material" > "$partial/.material-copied" ||
   ! cmp -s "$partial/.material-before" "$partial/.material-after" ||
   ! cmp -s "$partial/.material-before" "$partial/.material-copied" ||
   ! stopped_marker "$partial/material/recovery.json"; then
  echo 'recovery material changed during backup' >&2
  exit 1
fi
rm -f "$partial/.material-before" "$partial/.material-after" \
  "$partial/.material-copied" "$partial/.material-paths" "$partial/.material-hashes"
(
  cd "$partial"
  find database.dump database-bootstrap.sql material -type f -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)
mv -T "$partial" "$complete"
trap 'rm -f /tmp/occ-pgpass' EXIT
echo "verified OpenClaw Enterprise recovery set $timestamp"
