#!/usr/bin/env bash
set -euo pipefail

archive="${1:-/config/archive/torrent-recovery-20260720T062234Z.tar.xz}"
mode="${2:---dry-run}"

if [[ "${mode}" != "--dry-run" && "${mode}" != "--execute" && "${mode}" != "--readd" ]]; then
  echo "usage: $0 [/config/archive/restore.tar.xz] [--dry-run|--execute|--readd]" >&2
  exit 2
fi

kubectl -n media exec deploy/deluge -c app -- /bin/sh -ec '
archive="$1"
mode="$2"

test -s "$archive"
echo "Archive: $archive"
echo "Torrent files in archive:"
tar -tJf "$archive" | grep -c "[.]torrent$" || true

if [ "$mode" = "--dry-run" ]; then
  tar -tJf "$archive" | sed -n "1,80p"
  exit 0
fi

if [ "$mode" = "--readd" ]; then
  for torrent in /config/state/*.torrent; do
    [ -e "$torrent" ] || continue
    deluge-console -c /config "add -p /downloads/incomplete -m /downloads/complete $torrent" || true
  done
  deluge-console -c /config status
  exit 0
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
state_dir=/config/state
backup_dir=/config/state.pre-restore-$stamp

echo "Stopping deluged"
s6-svc -d /var/run/s6/services/deluged || true
timeout 20s s6-svwait -d /var/run/s6/services/deluged || true

if [ -e "$state_dir" ]; then
  mv "$state_dir" "$backup_dir"
else
  mkdir -p "$backup_dir"
fi

if [ -e /config/session.state ]; then cp -a /config/session.state "/config/session.state.pre-restore-$stamp"; fi
if [ -e /config/session.state.bak ]; then cp -a /config/session.state.bak "/config/session.state.bak.pre-restore-$stamp"; fi

tar -xJf "$archive" -C /config

torrent_count=$(find /config/state -maxdepth 1 -type f -name "*.torrent" | wc -l | tr -d " ")
echo "Restored $torrent_count torrent metadata files"
test "$torrent_count" -gt 0

if [ -s /config/state/torrents.state.bak ]; then
  cp -a /config/state/torrents.state.bak /config/state/torrents.state
fi
if [ -s /config/session.state.bak ]; then
  cp -a /config/session.state.bak /config/session.state
fi

echo "Starting deluged"
s6-svc -u /var/run/s6/services/deluged || true
ls -ld "$backup_dir" /config/state
ls -lh /config/state/torrents.state /config/state/torrents.fastresume
' sh "$archive" "$mode"
