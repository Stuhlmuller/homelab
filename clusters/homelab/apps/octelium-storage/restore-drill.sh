#!/bin/sh
# Internal CronJob entry point: read-only backup root, disposable work directory.
set -eu
umask 0077

backup_root="$1"
work="$2/restore-drill"
mkdir "$work"
exec 3>&1 4>&2
stage="backup-selection"
postgres_started=false
cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  if [ "$postgres_started" = true ]; then
    pg_ctl --pgdata="$work/pgdata" --mode=immediate --wait --timeout=30 stop >/dev/null 2>&1 || result=1
  fi
  if [ "$result" -eq 0 ]; then
    printf '%s\n' 'Octelium PostgreSQL restore drill passed' >&3
  else
    printf 'Octelium PostgreSQL restore drill failed at %s; private diagnostics remain in disposable scratch\n' "$stage" >&4
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
exec >"$work/details.log" 2>&1

# Completed backup directories are published by atomic rename. Never fall back
# to an older set when the newest set is stale, malformed, or corrupt.
find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20[0-9][0-9][01][0-9][0-3][0-9]T[0-2][0-9][0-5][0-9][0-5][0-9]Z' \
  -printf '%f\n' > "$work/backup-ids"
LC_ALL=C sort "$work/backup-ids" > "$work/sorted-backup-ids"
backup_id="$(tail -n 1 "$work/sorted-backup-ids")"
test -n "$backup_id"
# The daily drill must validate today's recovery point. Yesterday's successful
# set cannot mask a missing, delayed, or invalid current-day backup.
test "${backup_id%T*}" = "$(date -u +%Y%m%d)"
backup="$backup_root/$backup_id"
test ! -L "$backup"
backup_date="$(printf '%s' "$backup_id" | sed 's/^\(....\)\(..\)\(..\)T\(..\)\(..\)\(..\)Z$/\1-\2-\3 \4:\5:\6 UTC/')"
backup_epoch="$(date -u --date="$backup_date" +%s)"
age_seconds=$(( $(date -u +%s) - backup_epoch ))
test "$age_seconds" -ge -300
test "$age_seconds" -le 108000

stage="archive-verification"
mkdir "$work/backup"
for file in globals.sql octelium.dump SHA256SUMS; do
  test -f "$backup/$file"
  test ! -L "$backup/$file"
  cp --no-dereference "$backup/$file" "$work/backup/$file"
  test -f "$work/backup/$file"
  test ! -L "$work/backup/$file"
done
cd "$work/backup"
# Permit only the exact two files emitted by the backup CronJob. A checksum
# manifest must never redirect reads outside this copied recovery set.
awk '
  NF == 2 && length($1) == 64 && $1 !~ /[^0-9a-f]/ &&
    ($2 == "globals.sql" || $2 == "octelium.dump") { seen[$2]++; next }
  { bad = 1 }
  END { exit bad || NR != 2 || seen["globals.sql"] != 1 || seen["octelium.dump"] != 1 }
' SHA256SUMS
sha256sum --check SHA256SUMS
pg_restore --list octelium.dump >/dev/null

stage="isolated-database-start"
socket="$work/socket"
mkdir "$socket"
initdb --pgdata="$work/pgdata" --username=restore_drill \
  --auth-local=trust --auth-host=reject --encoding=UTF8 --locale=C
postgres_started=true
pg_ctl --pgdata="$work/pgdata" --log="$work/postgres.log" --wait --timeout=60 \
  --options="-c listen_addresses= -c unix_socket_directories=$socket -c shared_buffers=32MB -c max_connections=10 -c maintenance_work_mem=64MB" start

stage="globals-restore"
psql --host="$socket" --username=restore_drill --dbname=postgres \
  --no-psqlrc --set=ON_ERROR_STOP=1 --file=globals.sql
createdb --host="$socket" --username=restore_drill --owner=octelium \
  --template=template0 octelium

stage="database-restore"
pg_restore --host="$socket" --username=restore_drill --dbname=octelium \
  --exit-on-error octelium.dump

stage="restored-data-invariants"
psql --host="$socket" --username=restore_drill --dbname=octelium \
  --no-psqlrc --set=ON_ERROR_STOP=1 <<'SQL'
DO $drill$
BEGIN
  -- Core resources plus Enterprise encrypted resources and their wrapped keys
  -- are a required recovery set for this deployed Octelium cluster.
  IF NOT EXISTS (SELECT 1 FROM public.octelium_resources)
     OR NOT EXISTS (SELECT 1 FROM public.octelium_encrypted_resources)
     OR NOT EXISTS (SELECT 1 FROM public.octelium_data_encryption_keys) THEN
    RAISE EXCEPTION 'required Octelium recovery table is empty';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.octelium_resources
    WHERE resource IS NULL OR jsonb_typeof(resource) <> 'object'
       OR resource->'metadata'->>'uid' IS DISTINCT FROM uid
  ) THEN
    RAISE EXCEPTION 'restored resource identity is inconsistent';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.octelium_encrypted_resources r
    WHERE r.ciphertext IS NULL OR octet_length(r.ciphertext) = 0
       OR NOT EXISTS (
         SELECT 1 FROM public.octelium_data_encryption_keys k
         WHERE k.uid = r.key_uid
           AND k.ciphertext IS NOT NULL AND octet_length(k.ciphertext) > 0
       )
  ) THEN
    RAISE EXCEPTION 'restored encrypted resource lacks its wrapped key';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public' AND (NOT i.indisvalid OR NOT i.indisready)
  ) THEN
    RAISE EXCEPTION 'restored application index is invalid';
  END IF;
END
$drill$;
SQL
stage="database-stop"
pg_ctl --pgdata="$work/pgdata" --mode=fast --wait --timeout=30 stop
postgres_started=false
