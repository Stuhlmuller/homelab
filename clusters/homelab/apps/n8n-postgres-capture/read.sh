#!/bin/bash
# Read only: stdout is an archive; fixed diagnostics go to stderr.
set -euo pipefail
case "$1" in
  n8n) test "$(id -u)" = 1000; test -s /source/config ;;
  postgres)
    test "$(id -u)" = 65534
    test "$(cat /source/pgdata/PG_VERSION)" = 14
    test -d /source/pgdata/pg_wal
    test -z "$(find /source/pgdata/pg_tblspc -mindepth 1 -print -quit)"
    test ! -e /source/pgdata/postmaster.pid
    test "$(LC_ALL=C pg_controldata /source/pgdata | sed -n 's/^Database cluster state: *//p')" = 'shut down'
    ;;
  *) exit 2 ;;
esac
# Refuse links, devices, sockets, FIFOs and nested filesystems. Never fix ownership.
test -z "$(find /source -xdev ! -type f ! -type d -print -quit)"
test "$(find /source -mindepth 1 -type d -printf '%D\n' | sort -u | wc -l)" -le 1
test "$(findmnt -Rrn -o TARGET /source | wc -l)" -eq 1
before="$(find /source -xdev -printf '%P\0%y\0%s\0%T@\0' | sha256sum)"
cd /source
exec 3> >(sha256sum | sed 's/^/archive-sha256: /' >&2)
hash_pid=$!
tar --one-file-system --sort=name --numeric-owner --format=pax -cf - . | tee /dev/fd/3
exec 3>&-
wait "$hash_pid"
after="$(find /source -xdev -printf '%P\0%y\0%s\0%T@\0' | sha256sum)"
test "$before" = "$after"
if [ "$1" = postgres ]; then
  test "$(LC_ALL=C pg_controldata /source/pgdata | sed -n 's/^Database cluster state: *//p')" = 'shut down'
fi
