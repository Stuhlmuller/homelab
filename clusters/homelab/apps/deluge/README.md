# Deluge VPN

Deluge is intentionally coupled to Gluetun. The `gluetun` container is a
restartable init sidecar, so Kubernetes starts it before the Deluge application
container and keeps it running for the lifetime of the Pod. If the VPN secret is
missing, the WireGuard values are invalid, or the Gluetun healthcheck cannot
pass, Deluge must not become ready.

## Secret Contract

The `deluge-vpn` ExternalSecret reads AirVPN WireGuard values from AWS SSM
Parameter Store:

| SSM parameter | WireGuard config field |
|---------------|------------------------|
| `/homelab/deluge/vpn/wireguard-private-key` | `PrivateKey` |
| `/homelab/deluge/vpn/wireguard-preshared-key` | peer `PresharedKey` |
| `/homelab/deluge/vpn/wireguard-addresses` | interface `Address` |

Use only the IPv4 CIDR in `WIREGUARD_ADDRESSES` unless the cluster and Pod
network are intentionally configured for IPv6.

The AirVPN forwarded port is not secret desired state. This deployment uses
AirVPN forwarded port `5983`; set Deluge's incoming BitTorrent port to that same
value in the Deluge UI. The setting is stored on the retained Deluge config PVC,
so it should persist across Pod restarts without being copied into SSM.

## Pod Security

Gluetun needs `NET_ADMIN` and `/dev/net/tun` to create the WireGuard tunnel.
The `media` namespace is labeled for privileged Pod Security admission by this
app path so Kubernetes can admit the Deluge VPN Pod. Keep privileged workloads
in this namespace limited to repo-reviewed media automation.

Deluge uses a one-pod rolling update strategy even though it runs one desired
replica. That lets Kubernetes start a replacement Pod when an older failed VPN
sidecar is stuck terminating; steady state still converges back to one Pod.

## Verification

After SSM values are replaced and Argo CD syncs Deluge:

```sh
kubectl -n media get externalsecret deluge-vpn
kubectl -n media get secret deluge-vpn
kubectl -n media get pod -l app.kubernetes.io/name=deluge
kubectl -n media logs deploy/deluge -c gluetun
```

The ExternalSecret should be ready, the `deluge-vpn` Secret should exist, the
Pod should be ready, and Gluetun logs should show a healthy WireGuard session.
This command should return success only while the VPN is healthy:

```sh
kubectl -n media exec deploy/deluge -c gluetun -- /gluetun-entrypoint healthcheck
```

If Gluetun is unhealthy, Deluge should lose readiness and torrent traffic should
fail closed instead of bypassing the VPN.
