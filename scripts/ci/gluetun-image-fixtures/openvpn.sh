#!/bin/sh
set -eu
binary=$1
nc -ll -p 8080 -e /bin/sh /fixture/serve.sh &
while [ ! -f /settings/openvpn.conf ]; do sleep 0.1; done
exec "$binary" --config /settings/openvpn.conf
