#!/usr/bin/env bash
# Inspect Plex, or start an enabled package whose main process is absent.
set -euo pipefail

case "${1:-}" in
  "" | --start) ;;
  *) echo "Usage: bash scripts/qnap-plex-recover.sh [--start]" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || exit 2

nas="themanofrod@10.1.0.2"
url="http://10.1.0.2:32400"
ssh_options=(-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes)

# Shared by the read-only probe and the privileged start to recheck at execution.
preflight=$(cat <<'REMOTE'
set -eu
install=$(/sbin/getcfg PlexMediaServer Install_Path -f /etc/config/qpkg.conf)
case "$install" in /share/*/.qpkg/PlexMediaServer) ;; *) exit 70;; esac
[ "$(readlink -f /etc/init.d/plex.sh)" = "$install/plex.sh" ] || exit 71
[ -x /etc/init.d/plex.sh ] || exit 72
[ -x /bin/setsid ] || exit 75
[ "$(/sbin/getcfg PlexMediaServer Enable -f /etc/config/qpkg.conf)" = TRUE ] || exit 73
running=false
for comm in /proc/[0-9]*/comm; do
  name=$(cat "$comm" 2>/dev/null) || continue
  if [ "$name" = 'Plex Media Serv' ]; then running=true; break; fi
done
REMOTE
)

healthy() {
  curl --noproxy '*' --fail --silent --max-time 5 --output /dev/null "$url/identity" &&
    curl --noproxy '*' --fail --silent --max-time 5 --output /dev/null "$url/web/index.html"
}

# Expand running on the NAS, not on the operator machine.
# shellcheck disable=SC2016
state=$(printf '%s\nprintf "%%s\\n" "$running"\n' "$preflight" |
  ssh -T "${ssh_options[@]}" "$nas" /bin/sh -s)
case "$state" in true | false) ;; *) echo 'Unexpected NAS response.' >&2; exit 1;; esac

if healthy; then
  echo 'Plex identity and web respond; no recovery needed.'
  exit 0
fi
if [[ "$state" == true ]]; then
  echo 'Plex main process exists but HTTP health failed; inspect logs before recovery.' >&2
  exit 1
fi
if [[ "${1:-}" != --start ]]; then
  echo 'Plex main process absent and HTTP health failed. Recovery available with --start.'
  exit 1
fi

# A real operator terminal allows sudo to prompt without exposing a password.
# Without a terminal, fail promptly if administrative access is unavailable.
if [[ -t 0 ]]; then
  tty_options=(-t)
  auth='sudo -v'
else
  tty_options=(-T)
  auth='sudo -n -v'
fi
recovery="$preflight"$'\n'
# shellcheck disable=SC2016
recovery+='[ "$(id -u)" = 0 ] || exit 74
if [ "$running" = false ]; then
  /bin/setsid /etc/init.d/plex.sh start </dev/null >/dev/null 2>&1
fi'
# The script contains no single quotes except the process name; quote for sh.
quoted_recovery="'${recovery//\'/\'\\\'\'}'"
# auth and the shell-quoted recovery program are intentionally composed locally.
# shellcheck disable=SC2029
ssh "${tty_options[@]}" "${ssh_options[@]}" "$nas" \
  "$auth && sudo -n /bin/sh -c $quoted_recovery"

echo 'Start requested. Waiting for Plex to become ready...'
for ((attempt = 0; attempt < 30; attempt++)); do
  if healthy; then
    echo "Plex identity and web respond: $url/web/"
    exit 0
  fi
  sleep 3
done
echo 'Plex did not become healthy; inspect startup logs. No automatic retry performed.' >&2
exit 1
