#!/bin/sh
# Harmless native regression: attempt console writes through live procfs ancestors.
set -eu
umask 077
mode=$1
case "$mode" in client|server) ;; *) exit 1 ;; esac
marker=OCTELIUM_SYNTHETIC_PRIVATE_CONSOLE_CANARY
pid=$(awk '/^PPid:/ {print $2}' "/proc/$$/status")
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
  process=$(cat "/proc/$pid/comm")
  case "$process" in
    sh|dash|bash)
      # PostgreSQL ancestors have protocol/death-watch pipes that are not logs.
      # Inspect only shell ancestors that can retain the script's console handles.
      descriptors="1 2"
      # SQL-created shells can inherit PostgreSQL death-watch pipes in fd3/4.
      # Extra descriptors are console candidates only on the known entry script.
      if tr '\000' '\n' < "/proc/$pid/cmdline" | grep -qx /tests/restore-drill.sh; then
        descriptors="1 2 3 4"
      fi
      for fd in $descriptors; do
        probe_fd "/proc/$pid/fd/$fd"
        attempts=$((attempts + 1))
      done ;;
  esac
  [ "$pid" -ne 1 ] || break
  parent=$(awk '/^PPid:/ {print $2}' "/proc/$pid/status")
  case "$parent" in ''|*[!0-9]*) exit 1 ;; esac
  [ "$parent" -ne "$pid" ] || exit 1
  pid=$parent
  ancestors=$((ancestors + 1))
done
# Docker exec ancestry can terminate outside this PID namespace; test PID1 explicitly.
for fd in 1 2; do
  probe_fd "/proc/1/fd/$fd"
  attempts=$((attempts + 1))
done
test "$writes" -ge 2
printf '%s\n' "$attempts" > "/work/console-probe-$mode.executed"
