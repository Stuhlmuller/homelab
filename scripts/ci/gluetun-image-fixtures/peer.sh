#!/bin/sh
set -eu
# This address exists only inside the owned internal-network peer namespace.
ip address add 198.18.0.2/32 dev lo
# Alpine 3.22 enables nc server/exec support but omits busybox httpd.
touch /tmp/peer-ready
exec nc -ll -p 8080 -e /bin/sh /fixture/serve.sh
