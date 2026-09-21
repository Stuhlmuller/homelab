# Dispatcharr

Dispatcharr runs in the `media` namespace as an Octelium-protected IPTV and EPG
manager at `https://dispatcharr.stinkyboi.com`.

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

Do not commit IPTV provider credentials, playlist URLs, or guide source secrets.
Configure those through the UI or a future ExternalSecret-backed integration.

## Rollback

Revert the Argo CD Application registration and app manifests, then sync the
`dispatcharr` Application. Preserve the `data` PVC and the
`dispatcharr-postgres` PVC unless the operator explicitly chooses to discard
Dispatcharr state.
