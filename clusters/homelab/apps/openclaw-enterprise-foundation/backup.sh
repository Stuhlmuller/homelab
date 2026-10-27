#!/usr/bin/env bash
# T051 must mount a quiesced, identity-checked recovery set at /recovery-material
# and provide local scratch plus an age recipient before scheduling this script.
set -euo pipefail
umask 0077

material=/recovery-material
backup_root=/backup/openclaw-enterprise
backup_mount=${backup_root%/*}
scratch_root=/scratch/openclaw-enterprise
scratch_mount=${scratch_root%/*}
recipient_file=/run/backup-recipient/age.pub
recipient_mount=${recipient_file%/*}
max_entries=100000
max_path_bytes=4096
max_components=64
max_component_bytes=255
max_aggregate_path_bytes=16777216
max_unpacked_bytes=34359738368
stopped_marker() {
  jq -es 'length == 1 and (.[0] | type == "object" and .writerStopped == true and
    .continuousFenceVerified == true and
    (.claimUid | type == "string" and length > 0))' "$1" >/dev/null 2>&1
}
material_manifest() (
  root="$1"
  test -d "$root" && test ! -L "$root" || exit 1
  find "$root" ! -type f ! -type d -exec false {} + >/dev/null 2>&1 || exit 1
  find "$root" -type f -links +1 -exec false {} + >/dev/null 2>&1 || exit 1
  cd "$root" || exit 1
  find . -printf '%y %p\0' > "$stage/.material-paths" || exit 1
  LC_ALL=C sort -z "$stage/.material-paths" || exit 1
  find . -type f -exec sha256sum -- {} + > "$stage/.material-hashes" || exit 1
  LC_ALL=C sort "$stage/.material-hashes"
)
stage_preflight() (
  set -euo pipefail
  export LC_ALL=C
  cd "$stage" || exit 1
  find database.dump database-bootstrap.sql material SHA256SUMS \
    -printf '%p\0%s\0%y\0' |
  while IFS= read -r -d '' entry && IFS= read -r -d '' size &&
        IFS= read -r -d '' kind; do
    count=$(( ${count:-0} + 1 ))
    (( count <= max_entries )) || exit 1
    (( ${#entry} <= max_path_bytes )) || exit 1
    total_path_bytes=$(( ${total_path_bytes:-0} + ${#entry} ))
    (( total_path_bytes <= max_aggregate_path_bytes )) || exit 1
    case "$entry" in
      ''|/*|*\\*|*[$'\001'-$'\037'$'\177']*) exit 1 ;;
    esac
    remaining=$entry
    components=0
    while :; do
      component=${remaining%%/*}
      (( ${#component} > 0 && ${#component} <= max_component_bytes )) || exit 1
      case "$component" in .|..) exit 1 ;; esac
      components=$((components + 1))
      (( components <= max_components )) || exit 1
      case "$remaining" in
        */*) remaining=${remaining#*/} ;;
        *) break ;;
      esac
    done
    case "$kind" in
      f)
        case "$size" in ''|*[!0-9]*) exit 1 ;; esac
        (( size <= max_unpacked_bytes - ${total_file_bytes:-0} )) || exit 1
        total_file_bytes=$(( ${total_file_bytes:-0} + size ))
        ;;
      d) ;;
      *) exit 1 ;;
    esac
  done
)
if ! test -d "$backup_mount" || test -L "$backup_mount" ||
   ! mountpoint -q "$backup_mount"; then
  echo 'private backup destination is not mounted' >&2
  exit 1
fi
if test -L "$backup_root"; then
  echo 'private backup directory must not be a symlink' >&2
  exit 1
fi
if ! test -d "$scratch_mount" || test -L "$scratch_mount" ||
   ! mountpoint -q "$scratch_mount"; then
  echo 'private local backup scratch is not mounted' >&2
  exit 1
fi
case "$(stat -f -c %T "$scratch_mount")" in
  tmpfs|ext2/ext3|ext4|xfs|btrfs|overlayfs|zfs|apfs) ;;
  *) echo 'backup scratch filesystem is not local' >&2; exit 1 ;;
esac
if test -L "$scratch_root" || ! test -d "$recipient_mount" ||
   ! mountpoint -q "$recipient_mount" ||
   ! test -s "$recipient_file" || ! test -f "$recipient_file"; then
  echo 'backup recipient is missing or scratch is redirected' >&2
  exit 1
fi
resolved_recipient="$(realpath -e "$recipient_file")"
resolved_recipient_mount="$(realpath -e "$recipient_mount")"
case "$resolved_recipient" in
  "$resolved_recipient_mount"/*) ;;
  *) echo 'backup recipient leaves its projected mount' >&2; exit 1 ;;
esac
recipient="$(cat "$recipient_file")"
if [[ ! "$recipient" =~ ^age1[0-9a-z]+$ ]]; then
  echo 'backup recipient is invalid' >&2
  exit 1
fi
command -v age >/dev/null
if ! age --version | grep -qx v1.3.1; then
  echo 'backup age runtime is not the reviewed version' >&2
  exit 1
fi
test -s /run/secrets/occ-postgres-backup/password
test -s /run/postgres-ca/tls.crt
stage=
partial=
logged=false
phase=setup
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if test -n "$stage"; then rm -rf -- "$stage" || status=1; fi
  if test -n "$partial"; then rm -f -- "$partial" || status=1; fi
  if test "$logged" = true; then
    if test "$status" -eq 0; then
      printf 'encrypted OpenClaw Enterprise recovery set %s; restore unverified\n' "$timestamp" >&4
    else
      printf 'OpenClaw Enterprise encrypted backup failed at %s\n' "$phase" >&3
    fi
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
candidate_partial="$backup_root/.$timestamp.tar.age.partial"
complete="$backup_root/$timestamp.tar.age"
if test -e "$complete" || test -L "$complete"; then
  echo "backup destination already exists: $timestamp" >&2
  exit 1
fi
if test -e "$candidate_partial" || test -L "$candidate_partial"; then
  echo "backup partial destination already exists: $timestamp" >&2
  exit 1
fi
mkdir -p "$scratch_root"
test -d "$scratch_root" && test ! -L "$scratch_root"
chmod 0700 "$scratch_root"
stage="$(mktemp -d "$scratch_root/.$timestamp.XXXXXXXX")"
exec 3>&2 4>&1
exec </dev/null >"$stage/details.log" 2>&1
logged=true
phase=material
for file in recovery.json postgres-root/tls.crt postgres-root/tls.key \
  postgres-admin/password postgres-migrator/password postgres-app/password \
  postgres-backup/password auth/secret gateway/occ \
  gateway-ca/tls.crt gateway-ca/tls.key bootstrap/output.json \
  bootstrap/initial-admin-password bootstrap/initial-admin-service-key.json \
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
phase=credential
password="$(cat /run/secrets/occ-postgres-backup/password)"
case "$password" in
  *[!A-Za-z0-9]*|'') echo 'invalid backup credential shape' >&2; exit 1 ;;
esac
printf 'occ-postgres.openclaw-system.svc.cluster.local:5432:*:occ_backup:%s\n' \
  "$password" > "$stage/.pgpass"
unset password
chmod 0600 "$stage/.pgpass"
connection="host=occ-postgres.openclaw-system.svc.cluster.local port=5432 user=occ_backup dbname=openclaw_enterprise sslmode=verify-full sslrootcert=/run/postgres-ca/tls.crt passfile=$stage/.pgpass connect_timeout=15"
# Reject a changed or replaced recovery tree instead of publishing a mixed snapshot.
material_manifest "$material" > "$stage/.material-before" || {
  echo 'recovery material changed during backup' >&2; exit 1;
}
phase=database
pg_dump --dbname="$connection" --format=custom --file="$stage/database.dump"
pg_restore --list "$stage/database.dump" >/dev/null
phase=copy
cp /scripts/database-bootstrap.sql "$stage/database-bootstrap.sql"
cp -a "$material" "$stage/material"
if ! material_manifest "$material" > "$stage/.material-after" ||
   ! material_manifest "$stage/material" > "$stage/.material-copied" ||
   ! cmp -s "$stage/.material-before" "$stage/.material-after" ||
   ! cmp -s "$stage/.material-before" "$stage/.material-copied" ||
   ! stopped_marker "$stage/material/recovery.json"; then
  echo 'recovery material changed during backup' >&2
  exit 1
fi
rm -f "$stage/.material-after" "$stage/.material-copied" \
  "$stage/.material-paths" "$stage/.material-hashes"
(
  cd "$stage"
  find database.dump database-bootstrap.sql material -type f -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)
phase=preflight
stage_preflight
# Plaintext stays on reviewed local scratch; the off-node mount receives only
# ciphertext. A separate private decrypt and restore must verify this set.
phase=encrypt
mkdir -p "$backup_root"
test -d "$backup_root" && test ! -L "$backup_root"
chmod 0700 "$backup_root"
partial="$candidate_partial"
tar -C "$stage" -cf - database.dump database-bootstrap.sql material SHA256SUMS \
  | age --recipient "$recipient" --output "$partial"
test -s "$partial"
if ! material_manifest "$material" > "$stage/.material-after-encryption" ||
   ! cmp -s "$stage/.material-before" "$stage/.material-after-encryption"; then
  echo 'recovery material changed during encryption' >&2
  exit 1
fi
rm -rf -- "$stage"
stage=
phase=publish
mv -T "$partial" "$complete"
partial=
