#!/bin/sh
set -eu
peer=$1
# No host routing: the only gateway is our owned peer on Docker's internal bridge.
ip route replace default via "$peer"
ip route replace 198.18.0.2/32 via "$peer"
# Keep this one isolated negative-control destination on the same physical route
# before/after VPN setup, so tunnel routing cannot masquerade as firewall denial.
ip rule add priority 1 to 198.18.0.2/32 lookup main
mkdir -p /gluetun/wireguard /run/secrets
for source in /settings/*; do
  name=${source##*/}
  case "$name" in wg0.conf|mode) continue ;; esac
  cp "$source" "/gluetun/$name"
done
# The secret-file profile must override this deliberately invalid lower-priority file.
printf '[Interface]\nPrivateKey = invalid-fixture-key\nAddress = 10.99.0.2/32\n[Peer]\nPresharedKey = invalid-fixture-key\n' > /gluetun/wireguard/wg0.conf
if [ "$(cat /settings/mode)" = valid ]; then
  cp /settings/wg0.conf /run/secrets/wg0.conf
  chmod 600 /run/secrets/wg0.conf
fi
touch /tmp/before-ready
while [ ! -e /tmp/start-gluetun ]; do sleep 0.1; done
exec /gluetun-entrypoint
