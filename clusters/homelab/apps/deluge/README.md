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
network are intentionally configured for IPv6. The ExternalSecret template
extracts the first IPv4 CIDR from the SSM value before writing the Kubernetes
Secret, and `values.yaml` pins `WIREGUARD_ALLOWED_IPS` to `0.0.0.0/0`, so
AirVPN-provided IPv6 values do not make Gluetun configure IPv6 routing in this
IPv4-only cluster.

The AirVPN forwarded port is not secret desired state. This deployment uses
AirVPN forwarded port `5983`; set Deluge's incoming BitTorrent port to that same
value. Configure it in `values.yaml` through `FIREWALL_VPN_INPUT_PORTS` and the
shared `DELUGE_INCOMING_PORT` value. A `port-config` sidecar shares the Deluge
config volume and applies:

```sh
deluge-console -c /config "config --set random_port false; config --set listen_ports (${DELUGE_INCOMING_PORT}, ${DELUGE_INCOMING_PORT})"
```

The sidecar retries while Deluge starts and verifies that Deluge reports the
configured `listen_ports` value. If it cannot connect to Deluge and apply the
port configuration, the sidecar stays unready instead of killing the main app
container during startup. The Pod becomes ready only after Gluetun is healthy
and the incoming port has been applied.

## Download Paths

Deluge owns the shared `deluge-downloads` PVC. Radarr and Sonarr mount that same
claim at `/downloads`, so their download-client checks can see the files Deluge
creates without remote path mappings.

Use these Deluge paths:

| Setting | Path |
|---------|------|
| Download to | `/downloads/incomplete` |
| Move completed to | `/downloads/complete` |
| Radarr label path | `/downloads/complete/radarr` |
| Sonarr label path | `/downloads/complete/sonarr` |

The `download-dirs` init container creates the incomplete, complete, Radarr,
Sonarr, and manual directories before Deluge starts.

## Pod Security

Gluetun needs `NET_ADMIN` and `/dev/net/tun` to create the WireGuard tunnel.
The `media` namespace is labeled for privileged Pod Security admission by this
app path so Kubernetes can admit the Deluge VPN Pod. Keep privileged workloads
in this namespace limited to repo-reviewed media automation.

Deluge uses a `Recreate` rollout strategy because the app and helper sidecar
share a single `ReadWriteOnce` config PVC. Kubernetes should stop the old
singleton before starting the replacement so two Deluge daemons do not write the
same restored config volume at the same time.

## Mesh Policy

The `media` namespace is enrolled in Istio ambient mode. Ambient is used instead
of sidecar injection so Deluge's Gluetun-managed Pod network namespace does not
also receive an Envoy sidecar.

Deluge has a workload-scoped `PeerAuthentication` that requires STRICT mTLS and
an `AuthorizationPolicy` that allows only these media automation identities to
reach Deluge's web/API port `8112`:

- `media/radarr`
- `media/sonarr`
- `media/prowlarr`

The Deluge tailnet `VirtualService` remains declared for reviewability, but this
policy intentionally does not allow the Istio ingress gateway identity. Add that
principal in the same policy only if operator UI access to Deluge is deliberately
restored.

## Verification

After SSM values are replaced and Argo CD syncs Deluge:

```sh
kubectl -n media get externalsecret deluge-vpn
kubectl -n media get secret deluge-vpn
kubectl -n media get pod -l app.kubernetes.io/name=deluge
kubectl -n media logs deploy/deluge -c gluetun
kubectl -n media get peerauthentication deluge-strict-mtls
kubectl -n media get authorizationpolicy deluge-allow-media-clients
```

The ExternalSecret should be ready, the `deluge-vpn` Secret should exist, the
Pod should be ready, the mesh policy objects should exist, and Gluetun logs
should show a healthy WireGuard session.
This command should return success only while the VPN is healthy:

```sh
kubectl -n media exec deploy/deluge -c gluetun -- /gluetun-entrypoint healthcheck
```

If Gluetun is unhealthy, Deluge should lose readiness and torrent traffic should
fail closed instead of bypassing the VPN.
