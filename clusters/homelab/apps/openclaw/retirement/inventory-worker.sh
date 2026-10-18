#!/bin/sh
# Run the read-only full-tree inventory inside the reader Pod, beyond exec stream lifetime.
set -eu
umask 077

run_id="${1:-}"
case "$run_id" in ''|*[!0-9]*) exit 2 ;; esac
directory=/private/legacy
lock="$directory/inventory.lock"
marker="$directory/inventory-${run_id}.state"
result="$directory/baseline-${run_id}.json"
log="$directory/inventory-${run_id}.log"
if ! { test -d "$lock" && test ! -L "$lock" &&
       test ! -e "$marker" && test ! -L "$marker" &&
       test ! -e "$result" && test ! -L "$result" &&
       test ! -e "$log" && test ! -L "$log"; }; then
  exit 1
fi

finish() {
  status=$?
  if rmdir "$lock"; then
    if test "$status" -eq 0; then
      printf 'success\n' >"$marker"
    else
      printf 'failure\n' >"$marker"
    fi
  fi
}
trap finish EXIT
trap 'exit 1' HUP INT TERM

python3 /etc/openclaw-retirement/retirement.py inventory \
  --config "$directory/config.json" --status "$directory/status.json" \
  --output "$result" >"$log" 2>&1
