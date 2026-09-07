#!/bin/sh
# Harmless native regression: attempt console writes through live procfs ancestors.
set -eu
umask 077
mode=$1
case "$mode" in client|server) ;; *) exit 1 ;; esac
marker=OCTELIUM_SYNTHETIC_PRIVATE_CONSOLE_CANARY
pid=$PPID
attempts=0
ancestors=0
writes=0
probe_fd() {
  target=$(readlink "$1" 2>/dev/null) || return 0
  # Never alter psql's input script or another PostgreSQL data descriptor.
  case "$target" in
    'pipe:['*']'|/dev/null|/work/restore-drill/details.log|/work/restore-drill/postgres.log)
      if (printf '%s\n' "$marker" >>"$1") 2>/dev/null; then
        writes=$((writes + 1))
      fi ;;
  esac
}
while [ "$pid" -gt 0 ] && [ "$ancestors" -lt 32 ]; do
  for fd in 0 1 2 3 4; do
    # A private regular file or /dev/null may accept this; neither may reach logs.
    probe_fd "/proc/$pid/fd/$fd"
    attempts=$((attempts + 1))
  done
  [ "$pid" -ne 1 ] || break
  parent=$(awk '/^PPid:/ {print $2}' "/proc/$pid/status")
  case "$parent" in ''|*[!0-9]*) exit 1 ;; esac
  [ "$parent" -ne "$pid" ] || exit 1
  pid=$parent
  ancestors=$((ancestors + 1))
done
# Docker exec ancestry can terminate outside this PID namespace; test PID1 explicitly.
for fd in 0 1 2 3 4; do
  probe_fd "/proc/1/fd/$fd"
  attempts=$((attempts + 1))
done
test "$writes" -ge 3
printf '%s\n' "$attempts" > "/work/console-probe-$mode.executed"
