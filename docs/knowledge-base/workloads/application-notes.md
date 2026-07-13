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

Human application access uses Octelium clientless `WEB` Services. Reviewed
callback hosts use the public Octelium tunnel with explicit path restrictions.
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

Generated or adopted upstream resources must still have one declared owner.
Keep package capture and bootstrap commands in the workload README, and keep
steady-state resources under Argo CD wherever the upstream lifecycle permits.

Use [[inventory]] as the current cross-workload summary and read the named
source README before changing an application.
