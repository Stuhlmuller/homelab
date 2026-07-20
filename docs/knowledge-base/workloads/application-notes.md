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
AFFiNE is the reviewed exception: its Octelium Service is anonymous so the
stock native client can use AFFiNE's own login, while public signup remains
disabled. Reviewed callback hosts use the public Octelium tunnel with explicit
path restrictions.
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

## Dispatcharr

Dispatcharr runs in upstream modular mode in the `media` namespace and exposes
`https://dispatcharr.stinkyboi.com` through the Octelium app access plane. Its
`data` PVC stores file-backed runtime data and operator-configured IPTV sources,
while database state lives in the dedicated `dispatcharr-postgres` StatefulSet
and PVC. Do not switch it to upstream all-in-one mode on `nfs-default`: that
image recursively changes ownership below `/data/db`, which conflicts with the
QNAP export's squashed UID behavior. Provider credentials, playlist URLs, and
guide source secrets stay outside git.

Generated or adopted upstream resources must still have one declared owner.
Keep package capture and bootstrap commands in the workload README, and keep
steady-state resources under Argo CD wherever the upstream lifecycle permits.

Use [[inventory]] as the current cross-workload summary and read the named
source README before changing an application.
