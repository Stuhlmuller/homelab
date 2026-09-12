# Application Notes

Tags: #workloads #apps #platform

Canonical sources:

- [`clusters/homelab/apps/README.md`](../../../clusters/homelab/apps/README.md)
- `clusters/homelab/apps/*/README.md`
- `clusters/homelab/platform/*/README.md`
- [[inventory]] for ownership, namespaces, dependencies, and state

## Shared Rules

Application desired state lives under `clusters/homelab/apps/<app>`; shared
platform state lives under `clusters/homelab/platform/<service>`. Register both
through `IaC/live/argocd-apps/<name>` and deliver runtime changes through Argo
CD rather than direct cluster mutation.

Human application access normally uses Octelium clientless `WEB` Services.
AFFiNE is the reviewed exception: its Octelium Service is anonymous and
delegates login to the application. AFFiNE public signup remains disabled.
NOFX requires Octelium human browser authentication before its own login.
Reviewed callback hosts use the public Octelium tunnel with explicit path
restrictions.
Tailscale is secondary LAN and egress infrastructure, not the primary app
access plane. `cloudflared` loads its mounted hostname map only at pod startup,
so every `octelium-public/configmap.yaml` routing change must also advance the
Deployment's `homelab.rst.io/cloudflared-config-revision` annotation. Without
that rollout trigger, a new public hostname reaches the tunnel but falls through
to the edge HTTP 404.

Persistent state, migration, backup, and restore behavior belong in each
workload README and [[../architecture/storage-and-state]]. Secret values stay
outside git; repository-owned SSM paths and ExternalSecret contracts are
tracked in [[../architecture/secrets-and-identity]].

## Kiali mesh visibility

The 2026-09-05 read-only probes found cluster-wide namespace and Istio config
listing working, but zero graph connections and no `istio_*` Prometheus series.
Kiali's API reported a startup Prometheus reachability failure retained in
memory, even though its CR enabled Prometheus. Upstream v2.26.0
`cmd/server.go` installs a permanent no-op client in that case.

`clusters/homelab/apps/kiali/values.yaml` waits for Prometheus readiness before
Kiali starts. `clusters/homelab/apps/prometheus/istio-podmonitors.yaml` owns
ztunnel L4, Envoy and Istiod scrape discovery. See the Kiali README for the
operator security flags, rollback and UI namespace selection. Validate rollout
with `python3 scripts/kiali-check.py`; Argo CD health alone is insufficient.
Live recovery remains unverified until the GitOps change rolls out. Grafana's
frontend-settings endpoint also returned 401; dashboard integration is a separate
follow-up requiring its existing authentication contract to be checked.

## Dispatcharr

Dispatcharr runs in upstream modular mode in the `media` namespace and exposes
`https://dispatcharr.stinkyboi.com` through the Octelium app access plane. Its
`data` PVC stores uploads and file-backed runtime data; accounts, including the
first administrator, and database configuration live in the dedicated
`dispatcharr-postgres` StatefulSet and PVC. Do not switch it to upstream
all-in-one mode on `nfs-default`: that image recursively changes ownership
below `/data/db`, which conflicts with the
QNAP export's squashed UID behavior. The web container uses upstream
`PUID`/`PGID` `65534` so nginx and Django match the export's anonymous owner.
The 2026-08-27 rollout produced ready web/database workloads while the protected
hostname returned `503`. On September 6, Octelium Entra login reached
Dispatcharr `0.29.0` on pinned image `df768adc…`; its first-run UI refused setup
for the forwarded public client IP. An authenticated Kubernetes port-forward
bound to `127.0.0.1` returned `superuser_exists: false` and `setup_allowed: true`
from the read-only setup endpoint. No POST or account creation was performed
during that inspection.

The user confirmed Dispatcharr was never configured. Read-only PostgreSQL
inspection found no accounts/admins, channels or streams, and only the default
custom M3U seed without a configured provider URL, file,
username or password, consistent with first-run state. Preserve both existing
data and PostgreSQL claims during setup. Transport and Octelium authentication
are verified; first-admin/provider setup and functional acceptance remain open.
Follow the loopback-only human setup procedure in
`clusters/homelab/apps/dispatcharr/README.md`; do not broaden
public setup access or create an administrator through a shell command.
