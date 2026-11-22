#!/bin/sh
# Start the existing AirVPN profile only while the gateway controller grants a live lease.
set -eu

profile_value() {
    awk -F= -v key="$1" '
        tolower($1) ~ "^[[:space:]]*" key "[[:space:]]*$" {
            value = substr($0, index($0, "=") + 1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print value
            exit
        }
    ' /vpn-source/wg0.conf
}

wireguard_private_key="$(profile_value privatekey)"
wireguard_preshared_key="$(profile_value presharedkey)"
wireguard_addresses="$(
    profile_value address | tr ',' '\n' | awk '
        /^[[:space:]]*[0-9]+([.][0-9]+){3}\/[0-9]+[[:space:]]*$/ {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "")
            print
            exit
        }
    '
)"
test -n "$wireguard_private_key"
test -n "$wireguard_preshared_key"
test -n "$wireguard_addresses"

lease_active() {
    deadline="$(cat /run/deluge-vpn/leader 2>/dev/null)" || return 1
    case "$deadline" in ''|*[!0-9]*) return 1 ;; esac
    read -r uptime _ < /proc/uptime || return 1
    [ "${uptime%%.*}" -lt "$deadline" ]
}

child=''
stop_gluetun() {
    if [ -z "$child" ]; then
        return
    fi
    kill -TERM "$child" 2>/dev/null || true
    for _ in 1 2 3; do
        if ! kill -0 "$child" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    kill -KILL "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
    child=''
}

trap 'stop_gluetun; exit 0' TERM INT
while true; do
    if lease_active; then
        ip rule del table 51820 2>/dev/null || true
        ip -6 rule del table 51820 2>/dev/null || true
        WIREGUARD_PRIVATE_KEY="$wireguard_private_key" \
            WIREGUARD_PRESHARED_KEY="$wireguard_preshared_key" \
            WIREGUARD_ADDRESSES="$wireguard_addresses" /gluetun-entrypoint &
        child=$!
        while kill -0 "$child" 2>/dev/null && lease_active; do
            sleep 1
        done
        stop_gluetun
    fi
    sleep 1
done
