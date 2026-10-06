# Dispatcharr

Dispatcharr runs in the `media` namespace as an Octelium-protected IPTV and EPG
manager at `https://dispatcharr.stinkyboi.com`.

## Capacity and resume

The app and dedicated PostgreSQL StatefulSet each declare one replica for the
IPTV-org USA setup. PostgreSQL starts in wave `-1`, before the app. Both existing
PVCs are reused; PostgreSQL retains its claim on scale-down and deletion.

The October 6, 2026 05:40 UTC preflight found enough capacity for the existing
1.875 GiB combined memory requests. Only `acer` could fit the 1664 MiB app Pod;
placing the 256 MiB database there too would leave about 1552 MiB of requested
memory headroom. All nodes were Ready without pressure. This proves current
scheduling fit, not peak streaming or transcoding capacity. Keep the existing
requests and verify actual usage during playback.

Render the pinned app-template chart and Kustomization before rollout. After
Argo CD reconciles, require database/app readiness and both `dispatcharr` and
`data-dispatcharr-postgres-0` PVCs `Bound`. To suspend again, set both replicas
to zero and restore the app annotation `argocd.argoproj.io/sync-wave: "-3"`
so it stops before PostgreSQL. Preserve both claims; ephemeral Redis queues
are cleared during suspension.

## Runtime Shape

- Image: `ghcr.io/dispatcharr/dispatcharr`
- Mode: upstream modular container with web and Celery containers
- PostgreSQL: dedicated `dispatcharr-postgres` PostgreSQL 17 StatefulSet
- Redis: in-pod sidecar, ephemeral cache/queue state
- HTTP port: `9191`
- Access: private app hostname through Octelium, no public unauthenticated
  route
- Public IP lookup: disabled with `DISPATCHARR_ENABLE_IP_LOOKUP=false`

The modular mode avoids the upstream all-in-one container's embedded PostgreSQL
ownership reconciliation under `/data/db`, which is not compatible with the
QNAP NFS export's squashed UID behavior. PostgreSQL readiness and liveness
execute `SELECT 1`, so accepting a socket without completing database work does
not count as healthy. The Pod still mounts a memory-backed `/dev/shm` volume
larger than the container runtime default for worker and stream-processing
scratch space.

## Storage

The `data` PVC uses `nfs-default` and stores uploads and file-backed runtime
data. Accounts, including the first administrator, and database configuration
live in PostgreSQL on the dedicated `dispatcharr-postgres` PVC. Treat both
claims as production state and include them with normal NFS backup coverage
before relying on the service. The database has 30-minute startup and runtime
liveness windows plus a 120-second termination grace so NFS-backed recovery can
complete without a restart loop.

The QNAP export maps writes from container root to UID/GID `65534`. The web
container sets upstream `PUID`/`PGID` to that owner so nginx and Django can use
the data directories without a forbidden `chown`. Its short wrapper gives the
image's existing `nobody` account a login shell before upstream renames that
account to `dispatcharr`; upstream later drops web processes to that UID.

## First Run

After Argo CD reports the `dispatcharr` Application `Synced` and `Healthy`, use
your authenticated Kubernetes context from a trusted workstation. Octelium
login can succeed while Dispatcharr refuses first-run setup for the forwarded
public client IP. Upstream permits creating the first administrator only when
none exists and its local/private source-IP check passes. Keep that restriction;
do not add a public setup allowlist or run an ad hoc `createsuperuser` command.

Start a temporary tunnel bound only to workstation loopback and leave this
terminal open:

```sh
kubectl -n media port-forward --address 127.0.0.1 service/dispatcharr 19191:9191
```

Wait for `Forwarding from 127.0.0.1:19191 -> 9191`. In a second terminal, check
the read-only setup endpoint:

```sh
(
set -euo pipefail
curl --fail --silent --show-error --max-time 10 --noproxy '*' \
  http://127.0.0.1:19191/api/accounts/initialize-superuser/ |
  jq -se 'length == 1 and .[0].superuser_exists == false and .[0].setup_allowed == true'
)
```

Proceed only when this prints `true` and exits zero. If an administrator already
exists, use normal login/account recovery. If setup remains denied, check the
tunnel and current image behavior before proceeding; preserve the source-IP
restriction.

Open `http://127.0.0.1:19191` in your own browser on that workstation and create
the first administrator through Dispatcharr's form. Choose and store credentials
privately; never put them in CLI arguments, shell history, logs or git. This is
human-owned application data written through the app to PostgreSQL. Close the
tunnel with `Ctrl-C` when finished, then verify Octelium login followed by
Dispatcharr account login at the protected hostname.

On September 6, the pinned `df768adc…` image reported version `0.29.0`; the
loopback GET returned `superuser_exists: false` and `setup_allowed: true`. No
setup POST or account creation was performed during that inspection. The user
confirmed Dispatcharr was never configured. The public authenticated route
reached the app, but
first-run setup and functional acceptance remain open.
See [the workload note](../../../../docs/knowledge-base/workloads/application-notes.md#dispatcharr)
for the observed first-run state. Confirm account login, provider/EPG
configuration, channel loading and playback before claiming full acceptance.

Do not commit IPTV provider credentials, private playlist URLs, or guide secrets.
Configure those through the UI or a future ExternalSecret-backed integration.

## IPTV-org USA source

The selected source is the public [IPTV-org USA playlist](https://iptv-org.github.io/iptv/countries/us.m3u).
Configure it through the authenticated native UI after first-run setup:

| Setting | Value |
| --- | --- |
| Account name | `IPTV-org USA` |
| Account type | Standard M3U |
| URL | `https://iptv-org.github.io/iptv/countries/us.m3u` |
| Active | Yes |
| Refresh interval | 24 hours |
| Max streams | `0` (no provider-wide limit) |
| Credentials | None |

Edit an existing account with this exact URL instead of adding a duplicate.
After group discovery, open **Groups**, enable the USA groups, leave
**Auto Channel Sync** off, then **Save and Refresh**. In the Streams table,
filter to this account with **Only Unassociated** and **Hide Stale**, select
all matching streams and use **Create Channels → Auto-Assign Sequential**.
The header checkbox includes matching rows across pages. Daily refresh updates
the source streams; review new streams and create their channels separately.

Manual channels preserve control of future EPG mappings and failover streams.
Upstream [recommends bulk creation for regular lineups](https://dispatcharr.github.io/Dispatcharr-Docs/troubleshooting/#use-of-auto-channel-sync);
reserve auto-sync for event groups whose channel identities follow the source.

The playlist currently supplies no XMLTV URL. Leave EPG unconfigured until a
compatible guide is selected; channel import does not establish programme data
or premium-event coverage. Verify nonempty Channels, `/output/m3u` and
`/hdhr/lineup.json`, then play a sample channel. Media-server connections remain
pending private routing. To remove this source, disable its
account first; use the native UI to review associated channels before deleting.

## Live TV for Jellyfin and Plex

Dispatcharr needs an operator-supplied M3U/Xtream source and guide data; it does
not supply channels or PPV access. Confirm the provider includes the desired
baseball, football and purchased events and exposes compatible streams. A
subscription limited to the provider's own player is not an M3U source.

October 6 inspection located both media servers on QNAP `10.1.0.2`.
Plex responds on port `32400`; Jellyfin is deliberately disabled and its port
`8096` is unavailable. Neither the cluster-only Service IP nor the protected
browser-login route currently provides an unattended tuner connection from
the NAS. Preserve the operator's Jellyfin stop while completing source setup.

After the capacity and first-run checks above:

1. Add the provider in **M3U & EPG Manager**, set its actual concurrent-stream
   allowance, and import only the required sports, local broadcast and event
   groups. Add its XMLTV guide privately.
2. Create channels from the imported streams, map their guide entries, and
   collect them in a `sports` Channel Profile. Copy the profile's output URLs
   from **Channels**; an imported stream alone is not an exported channel.
3. Choose a stable Dispatcharr address reachable from each media server. For
   servers inside this cluster, the base is
   `http://dispatcharr.media.svc.cluster.local:9191`. Outside the cluster, add
   the appropriate private route through reviewed repository configuration
   after identifying the server hosts. The existing Octelium browser-login
   hostname and a temporary workstation port-forward are not unattended tuner
   connections. Preserve the protected administrative route.
4. Restrict Dispatcharr's **Network Access** allowlists for M3U/EPG/HDHR and
   streams to the actual server source addresses. These exports use network
   access rules; they are not protected by the administrator's login.

Use the same profile for tuner and guide. With the reachable base above, the
native connections are:

| Server | Tuner | XMLTV guide |
| --- | --- | --- |
| Jellyfin | **Live TV → Tuner Devices → M3U Tuner**: `/output/m3u/sports` | **TV Guide Data Providers → XMLTV**: `/output/epg/sports` |
| Plex | **Live TV & DVR → network tuner**, enter manually: `/hdhr/sports` | `/output/epg/sports?cachedlogos=false` |

Leave Jellyfin's stream limit at `0` when Dispatcharr enforces the provider's
limit. Plex DVR recording requires Plex Pass. Prefer source passthrough where
clients support it; verify capacity before enabling server transcoding.

Before acceptance, fetch the playlist, XMLTV and HDHR discovery/lineup from
the media servers' network context. Require actual playlist/XML/JSON responses,
not an HTML login page; check that exported playback URLs are also reachable.
Refresh both guides, verify event times in `America/Los_Angeles`, then play an
available channel in each real client. Test two different channels together
only when the provider allowance permits. PPV acceptance requires playback
during an entitled event window; a channel name or guide listing is insufficient.

References: [Dispatcharr setup](https://dispatcharr.github.io/Dispatcharr-Docs/getting-started/),
[network access](https://dispatcharr.github.io/Dispatcharr-Docs/system/#network-access),
[Jellyfin Live TV](https://jellyfin.org/docs/general/server/live-tv/setup-guide/),
[Plex Live TV/DVR](https://support.plex.tv/articles/226463767-frequently-asked-questions-dvr-live-tv/).

## Rollback

Revert the Argo CD Application registration and app manifests, then sync the
`dispatcharr` Application. Preserve the `data` PVC and the
`dispatcharr-postgres` PVC unless the operator explicitly chooses to discard
Dispatcharr state.
