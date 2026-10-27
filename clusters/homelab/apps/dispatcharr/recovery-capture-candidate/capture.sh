#!/bin/sh
set -eu
umask 077

# A reviewed GitOps fence must stop the app, Celery and Redis before this Job is included.
printf '%s\n' "${FENCE_REF:-}" | grep -Eq '^[a-f0-9]{40}$' || {
  echo 'missing reviewed Dispatcharr writer-fence commit' >&2
  exit 1
}
# Bound any single failed output file to the publisher's 5 GiB limit.
ulimit -f 10485760

data_root="${CAPTURE_DATA_ROOT:-/data}"
backup_root="${CAPTURE_BACKUP_ROOT:-/backup/logical-backups}"
secret_file="${CAPTURE_SECRET_FILE:-/run/secrets/dispatcharr-postgres/POSTGRES_PASSWORD}"
test -d "$data_root" && test ! -L "$data_root"
test -r "$secret_file" && test ! -L "$secret_file"
password="$(cat "$secret_file")"
test -n "$password" && test "$password" != REPLACE_ME
export PGPASSWORD="$password"
unset password

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_root"
partial="$backup_root/.$timestamp.partial"
complete="$backup_root/$timestamp"
test ! -e "$complete"
mkdir "$partial"

# Refuse links and special files: the later restore must not follow archive escapes.
find "$data_root" -xdev \( -type l -o -type b -o -type c -o -type p -o -type s \) -print -quit >"$partial/unsafe-path"
if test -s "$partial/unsafe-path"; then
  echo 'Dispatcharr data contains an unsupported link or special file' >&2
  exit 1
fi
rm "$partial/unsafe-path"

pg_dumpall --host=dispatcharr-postgres --port=5432 --username=dispatcharr \
  --no-role-passwords --globals-only >"$partial/globals.sql"
pg_dump --host=dispatcharr-postgres --port=5432 --username=dispatcharr \
  --format=custom --file="$partial/dispatcharr.dump" dispatcharr
unset PGPASSWORD
pg_restore --list "$partial/dispatcharr.dump" >/dev/null
tar --create --file="$partial/data.tar" --directory="$data_root" \
  --one-file-system --numeric-owner --acls --xattrs .
# This Job cannot verify live writer state; a protected external receipt must do that.
printf '{"captured_at":"%s","writers_fenced":false,"requested_fence_reference":"%s","source_claims":["dispatcharr","data-dispatcharr-postgres-0"]}\n' \
  "$timestamp" "$FENCE_REF" >"$partial/capture.json"
(
  cd "$partial"
  sha256sum globals.sql dispatcharr.dump data.tar capture.json >SHA256SUMS
  sha256sum --check --status SHA256SUMS
)
bytes=0
for name in globals.sql dispatcharr.dump data.tar capture.json; do
  test -s "$partial/$name"
  size="$(wc -c <"$partial/$name")"
  bytes=$((bytes + size))
done
test "$bytes" -gt 0 && test "$bytes" -le 5368709120 || {
  echo 'Dispatcharr recovery set exceeds the 5 GiB publisher budget' >&2
  exit 1
}
mv "$partial" "$complete"
echo "completed paired Dispatcharr capture $timestamp"
