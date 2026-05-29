# Deluge VPN

Deluge is intentionally coupled to Gluetun. The `gluetun` container is a
restartable init sidecar, so Kubernetes starts it before the Deluge application
container and keeps it running for the lifetime of the Pod. If the VPN secret is
missing, the WireGuard values are invalid, or the Gluetun healthcheck cannot
pass, Deluge must not become ready.

## Secret Contract

The `deluge-vpn` ExternalSecret reads the AirVPN WireGuard profile from AWS
SSM Parameter Store and publishes it as `wg0.conf`:

| SSM parameter | Kubernetes Secret key |
|---------------|-----------------------|
| `/homelab/deluge/vpn/wireguard-config` | `wg0.conf` |

The `deluge-vpn` ExternalSecret uses `refreshPolicy: OnChange`. After replacing
the AirVPN profile values in SSM, bump the non-secret
`homelab.rst.io/wireguard-profile-ssm-version` annotation in both
`externalsecret.yaml` and `values.yaml`. The ExternalSecret metadata change
causes External Secrets to render a fresh Kubernetes Secret, and the pod
template annotation rolls Deluge so Gluetun reads the new WireGuard profile at
startup.

Gluetun runs this profile through its `custom` WireGuard provider so it uses the
exact AirVPN peer instead of selecting a random AirVPN server from provider
metadata. Gluetun's custom WireGuard path still requires the endpoint host to
be an IP address at startup, while AirVPN profiles can contain an endpoint DNS
name. A `config-wireguard` init container reads the secret profile, resolves a
DNS endpoint to its first IPv4 address when needed, and writes the normalized
profile into an in-memory volume mounted at `/gluetun/wireguard/wg0.conf`.

The AirVPN forwarded port is not secret desired state. This deployment uses
AirVPN forwarded port `5983`; set Deluge's incoming BitTorrent port to that same
value. Configure it in `values.yaml` through `FIREWALL_VPN_INPUT_PORTS` and the
shared `DELUGE_INCOMING_PORT` value. A `port-config` sidecar shares the Deluge
config volume and applies:

```sh
deluge-console -c /config "config --set random_port false; config --set listen_ports (${DELUGE_INCOMING_PORT}, ${DELUGE_INCOMING_PORT}); config --set random_outgoing_ports true; config --set outgoing_ports (0, 0)"
```

The sidecar retries while Deluge starts and verifies that Deluge reports the
configured `listen_ports`, default `outgoing_ports`, and random outgoing port
behavior. Keep the forwarded AirVPN port fixed only for incoming connections;
pinning outgoing connections to the same single port can leave torrents unable
to make enough peer connections. If the sidecar cannot connect to Deluge and
apply the port configuration, it stays unready instead of killing the main app
container during startup. The Pod becomes ready only after Gluetun is healthy
and the port configuration has been applied.

## Download Paths

Deluge owns the shared `media-downloads` PVC backed by the QNAP `/media` NFS
export. Radarr and Sonarr mount that same claim at `/downloads`, so their
download-client checks can see the files Deluge creates without remote path
mappings.

The `media-downloads-migration` Job copies any files from the older
`deluge-downloads` PVC into `/media/downloads` before Deluge switches to the new
claim. The job also creates the expected Servarr subdirectories, sets
write-friendly NFS permissions, and verifies that the target path accepts a
write from inside the cluster. The older `deluge-downloads` claim remains in
desired state as the migration source and rollback reference until the copy is
verified.

Use these Deluge paths:

| Setting | Path |
|---------|------|
| Download to | `/downloads/incomplete` |
| Move completed to | `/downloads/complete` |
| Radarr label path | `/downloads/complete/radarr` |
| Sonarr label path | `/downloads/complete/sonarr` |

The `download-dirs` init container keeps the incomplete, complete, Radarr,
Sonarr, and manual directories present before Deluge starts.

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

The `media` namespace is intentionally not enrolled in Istio ambient mode while
the operator web UIs are exposed through the shared tailnet ingress gateway.
The tailnet gateway must be able to proxy to Deluge, Radarr, Sonarr, and
Prowlarr services without ambient HBONE resets, and the Deluge Pod cannot use
sidecar injection because Gluetun owns the VPN network setup.

Keep media UI access on the Istio reverse proxy ingress path with
`public-funnel=false` Tailscale annotations. Reintroduce ambient mesh only with a
repo-owned waypoint or equivalent gateway policy that preserves HTTPS access to
the `*.stinkyboi.com` operator addresses.

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
