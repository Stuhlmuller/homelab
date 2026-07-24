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
DNS endpoint to its first IPv4 address when needed, strips IPv6 `Address` and
`AllowedIPs` entries, and writes the normalized profile into an in-memory
volume mounted at `/gluetun/wireguard/wg0.conf`. Keep
`homelab.rst.io/wireguard-profile-renderer-revision` in the pod template so
renderer-only changes roll the singleton and clear stale Gluetun network rules.

The AirVPN forwarded port is not secret desired state. This deployment uses
AirVPN forwarded port `5983`; set Deluge's incoming BitTorrent port to that same
value. Configure it in `values.yaml` through `FIREWALL_VPN_INPUT_PORTS` and the
shared `DELUGE_INCOMING_PORT` value. A `port-config` sidecar shares the Deluge
config volume and applies:

```sh
deluge-console -c /config "config --set random_port false; config --set listen_ports (${DELUGE_INCOMING_PORT}, ${DELUGE_INCOMING_PORT}); config --set random_outgoing_ports true; config --set outgoing_ports (0, 0)"
```

The sidecar retries while Deluge starts and verifies that Deluge reports the
configured `listen_ports` and random outgoing port behavior. It still asks
Deluge to reset `outgoing_ports` to the default range, but verification only
depends on random outgoing mode because Deluge can keep reporting its prior
stored range while honoring `random_outgoing_ports: True`. Keep the forwarded
AirVPN port fixed only for incoming connections; pinning outgoing connections
to the same single port can leave torrents unable to make enough peer
connections. If the sidecar cannot connect to Deluge and apply the port
configuration immediately, it keeps retrying in the background instead of
blocking the UI service endpoint. Pod readiness is gated by Gluetun, so traffic
still fails closed when the VPN healthcheck fails. Deluge daemon health is
covered separately by the app liveness probe and exported RPC metric.

A `daemon-metrics` sidecar runs `deluge-console -c /config status` and probes
Gluetun's local health endpoint every 30 seconds. It exposes
`deluge_daemon_rpc_healthy` and `deluge_vpn_healthy` on the service `metrics`
port as Prometheus text format. Prometheus scrapes them through
`clusters/homelab/apps/prometheus/deluge-servicemonitor.yaml`, and Grafana
alerts when either metric is missing or failing. This catches both a failed VPN
sidecar and the case where Kubernetes and Gluetun look healthy but `deluged`
cannot restore state or accept console connections.

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

The app asks s6 to stop the Deluge daemon during its Kubernetes `preStop` hook
and waits up to 20 seconds so libtorrent can write clean state without s6
restarting the daemon before `/init` receives termination. Abrupt node power
loss can still interrupt a write, so startup validation and automatic backup
recovery remain the final safety net.

## Mesh Policy

The `media` namespace is intentionally not enrolled in Istio ambient mode while
the operator web UIs are exposed through the shared Istio ingress path published
by Octelium. The Istio gateway must be able to proxy to Deluge, Radarr, Sonarr,
and Prowlarr services without ambient HBONE resets, and the Deluge Pod cannot
use sidecar injection because Gluetun owns the VPN network setup.

Keep media UI access on the Octelium service catalog path that forwards TCP/443
to the Istio reverse proxy. Reintroduce ambient mesh only with a repo-owned
waypoint or equivalent gateway policy that preserves HTTPS access to the
`*.stinkyboi.com` operator addresses.

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

The Gluetun container also removes stale IPv4 and IPv6 WireGuard policy rules
in a `postStart` hook. This follows the upstream Kubernetes recovery for
`adding IPv6 rule ... file exists`, where an abrupt container exit can leave a
pod-shared rule behind before the restartable sidecar starts again.

## Troubleshooting

If the Pod is `Ready` and Gluetun is healthy but Deluge is not usable, check
the daemon before restarting Kubernetes resources:

```sh
kubectl -n media logs deploy/deluge -c app --tail=120
kubectl -n media logs deploy/deluge -c port-config --tail=120
kubectl -n media exec deploy/deluge -c app -- \
  timeout 10s deluge-console -c /config info
```

Repeated `libtorrent::libtorrent_exception` messages such as
`invalid type requested from entry`, together with `port-config` reporting
connection refusals, mean the Deluge daemon could not restore its persisted
session state. Deluge 2.0.5 attempts to load both `session.state` and
`session.state.bak`; individually valid files can still be incompatible when
loaded sequentially. Startup reproduces that sequential load, archives an
invalid current file or incompatible backup, and restores or refreshes only
from a state file that passes libtorrent validation.

The separate `/config/state/torrents.state` file is Deluge's active torrent
catalog. If that catalog is empty or invalid while `.torrent` metadata remains,
startup first restores a non-empty validated catalog backup. When both catalog
copies are unusable, the repo-owned recovery script rebuilds the catalog only
if every `.torrent` info hash has an exact fast-resume match and every recovered
save path stays under `/downloads`. It checks the live fast-resume file first,
then retained `/config/archive/*.tar.xz` snapshots from newest to oldest. It
archives the old catalogs, atomically restores the complete fast-resume data
and catalog, and stops without changing state if validation fails. Downloaded
data and `.torrent` files remain untouched.

The startup probe gives NFS-backed initialization and guarded state recovery up
to 30 minutes before liveness begins. Runtime liveness also requires 30 minutes
of continuous daemon RPC failures before restarting the app, so a transient NFS
stall can clear without forcing another state archive and reload.

The wrapper removes the pinned image's `/etc/cont-init.d/30-config` hook before
LinuxServer initialization. That hook recursively changes ownership across
`/config`, which cannot succeed on the QNAP root-squashed export and turns every
restart into a large NFS metadata scan. The PVC's existing world-writable
permissions remain the write-access contract for Deluge's configured UID/GID.
When no persisted state exists on a new config volume, the wrapper lets Deluge
perform its normal first-run setup.

Before Deluge Web starts, the same wrapper normalizes legacy daemon hostlist
entries from `localhost` to Deluge's default `127.0.0.1`. Sonarr's Deluge
adapter selects the local daemon by that literal address; leaving the legacy
alias in place lets Sonarr authenticate to Deluge Web but prevents it from
connecting Web to the healthy daemon.

If automatic recovery cannot validate the backup, the app container stops
instead of overwriting more state. Preserve torrent metadata and downloaded
data; do not delete the `.torrent` files under `/config/state` or the
`/downloads` tree. Catalog recovery archives are written under
`/config/archive/torrent-catalog-recovery-*`. After explicit operator approval,
inspect the archived files before using the manual session-state fallback:

```sh
kubectl -n media exec deploy/deluge -c app -- /bin/sh -c '
set -eu
s6-svc -d /var/run/s6/services/deluged || true
stamp=$(date -u +%Y%m%dT%H%M%SZ)
cp -a /config/session.state /config/session.state.broken-$stamp
cp -a /config/session.state.bak /config/session.state
s6-svc -u /var/run/s6/services/deluged || true
ls -l /config/session.state /config/session.state.bak /config/session.state.broken-$stamp
'
```

Verify the daemon, port settings, directories, and VPN gate after recovery:

```sh
kubectl -n media exec deploy/deluge -c app -- \
  timeout 10s deluge-console -c /config config listen_ports
kubectl -n media exec deploy/deluge -c app -- \
  timeout 10s deluge-console -c /config config random_outgoing_ports
kubectl -n media exec deploy/deluge -c app -- \
  timeout 10s deluge-console -c /config info
kubectl -n media exec deploy/deluge -c daemon-metrics -- \
  python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:9797/metrics", timeout=5).read().decode(), end="")'
kubectl -n media exec deploy/deluge -c gluetun -- \
  /gluetun-entrypoint healthcheck
```

The expected port state is `listen_ports: (5983, 5983)` and
`random_outgoing_ports: True`. Both `deluge_daemon_rpc_healthy` and
`deluge_vpn_healthy` should be `1`; `deluge_torrents_total` should match the
expected catalog count. The archived `session.state.broken-*` file is the
rollback reference if the backup state is worse.

If a retained fast-resume snapshot points completed torrents back at
`/downloads/incomplete`, use the mounted reconciliation script. It selects only
incomplete catalog entries whose complete-root files all exist at their exact
expected sizes. Dry-run first:

```sh
kubectl -n media exec deploy/deluge -c app -- \
  python3 /scripts/reconcile-completed.py
```

After reviewing the count and byte total, apply the native libtorrent recovery:

```sh
kubectl -n media exec deploy/deluge -c app -- \
  python3 /scripts/reconcile-completed.py --apply
```

The apply path pauses the selected torrents, adopts existing target files with
libtorrent's `dont_replace` storage move, and forces a piece-hash recheck. It
checks entries one at a time so queue transitions cannot start a redownload:
verified entries resume for seeding, while entries that fail their hashes
remain paused. Target files are never replaced; stale source copies may be
removed by libtorrent. Exact sizes are only the selection guard—the hash
recheck is the integrity decision. See the upstream
[move-storage contract](https://www.libtorrent.org/reference-Storage.html).

If Sonarr and Radarr both have empty queues after recovery, remove paused
catalog entries whose expected complete-root files are missing or the wrong
size:

```sh
kubectl -n media exec deploy/deluge -c app -- \
  python3 /scripts/reconcile-completed.py --prune-skipped
```

This cleanup refuses entries that are not paused under `/downloads/complete`
and calls Deluge with `remove_data=false`, so it removes only stale catalog
records and never downloaded files.

If `deluge-vpn` is ready and the Kubernetes Secret exists but the Gluetun
container repeatedly fails startup health checks with DNS lookup timeouts, treat
that as an unhealthy WireGuard tunnel rather than a missing Kubernetes secret.
The usual repair is to generate a fresh AirVPN WireGuard profile, replace
`/homelab/deluge/vpn/wireguard-config` in SSM, then bump
`homelab.rst.io/wireguard-profile-ssm-version` in both `externalsecret.yaml`
and `values.yaml` so External Secrets renders the new Secret and Argo CD rolls
the Pod. Do not patch or restart the live Pod as the durable fix.

If Gluetun loops on `adding IPv6 rule ... file exists`, verify the rendered
profile is still IPv4-only. AirVPN profiles can include IPv6 interface and
allowed-route entries even when the homelab only needs IPv4; passing those
through can leave the restartable Gluetun init sidecar stuck in the same pod
network namespace while Deluge's daemon itself still answers RPC.
