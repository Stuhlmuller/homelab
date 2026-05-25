# Research: Argo CD Application Onboarding

## Catalog Module For Argo CD Applications

**Decision**: Use the Terragrunt catalog `argocd-application` module for each
normal Argo CD Application. Use `argocd-application-manifest` only when exact
Application CRD fields are required and the typed provider module cannot express
them.

**Rationale**: The local Terragrunt catalog documents `argocd-application` as a
typed module for metadata, destination, sources, Helm/Kustomize/directory
sources, sync policy, retries, diffing, and app info. It also documents
`argocd-application-manifest` as the raw CRD escape hatch for API fields not
covered by the typed provider. This keeps the common path readable while still
providing a narrow escape path.

**Alternatives considered**:

- Hand-written Argo CD Application manifests only: rejected because the request
  requires adding apps to Argo CD using Terragrunt catalog modules.
- ApplicationSet for all apps: rejected for first rollout because one unit per
  app makes dependencies, ownership, and rollback easier to review.
- Helm provider installs for workloads: rejected because Argo CD must own the
  runtime app reconciliation.

## Terragrunt Dependency Model

**Decision**: Create one Terragrunt unit per application under
`IaC/live/argocd-apps/<app>/terragrunt.hcl` and declare ordering with explicit
Terragrunt `dependencies { paths = [...] }` blocks. Use `dependency` blocks only
if a downstream unit must read outputs from an upstream unit.

**Rationale**: The app registration modules do not require output plumbing for
basic ordering. `dependencies` communicates sequencing directly and avoids
accidental implicit ordering by directory names or manual operator memory.

**Alternatives considered**:

- One large Terragrunt unit containing all applications: rejected because it
  hides dependency edges and makes partial rollback harder.
- Implicit ordering through directory names: rejected because the spec requires
  explicit Terragrunt dependencies.
- Argo CD sync waves only: useful inside Argo CD, but insufficient because the
  requested registration order must be visible in Terragrunt.

## Application Dependency Order

**Decision**: Use this dependency graph for first implementation:

| Application | Explicit Dependencies |
|-------------|-----------------------|
| platform-storage | Existing NFS provisioner prerequisite |
| external-secrets | Argo CD bootstrap only |
| cert-manager | external-secrets |
| istio | cert-manager |
| tailscale | external-secrets, istio |
| prometheus | external-secrets, platform-storage |
| grafana | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| descheduler | prometheus |
| deluge | cert-manager, istio, tailscale, platform-storage |
| prowlarr | cert-manager, istio, tailscale, platform-storage |
| radarr | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage |
| sonarr | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage |
| litellm | external-secrets, cert-manager, istio, tailscale, platform-storage |
| openclaw | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| tines | external-secrets, cert-manager, istio, tailscale, platform-storage |

**Rationale**: Secret and certificate controllers are foundations. Istio must
exist before routes are considered enabled. Tailscale depends on secret material
and the Istio reverse-proxy target. The supporting `platform-storage`
registration owns only the default NFS StorageClass and is a prerequisite for
stateful workloads. Grafana depends on Prometheus. Radarr and Sonarr depend on
Deluge for download-client integration and Prowlarr for indexer integration.
OpenClaw depends on LiteLLM as the model gateway.

**Alternatives considered**:

- Put Prometheus after every workload: rejected because it would make
  observability unavailable during rollout.
- Make descheduler independent: rejected because first rollout should have
  observability available before eviction policy runs.
- Let OpenClaw talk directly to model providers: rejected for this feature so
  LiteLLM can centralize provider secrets and model routing.

## Ingress, DNS, And Reachability

**Decision**: Use Istio as the reverse proxy and Tailscale as the reachability
layer. The first rollout is tailnet-only for all apps and enables zero public
Tailscale Funnel paths. Initial DNS must support future routes without per-app
DNS record edits.

**Rationale**: This matches the clarified operator goal: internal apps live on
the tailnet, public reachability is reserved for future webhook exceptions via
Tailscale Funnel, and DNS churn after initial setup is unacceptable.

**Alternatives considered**:

- Traefik: rejected by clarification; Istio will be the reverse proxy.
- Public app UI routes: rejected for first rollout to keep public surface area
  at zero.
- Per-app DNS records: rejected because the operator wants no DNS edits after
  initial configuration.

## Secret Backend

**Decision**: External Secrets uses AWS SSM Parameter Store for runtime secret
material. Commit only parameter names/paths, ExternalSecret resources, and
non-secret defaults.

**Rationale**: The repository already uses AWS-backed Terragrunt state
configuration, and AWS SSM references are safe to commit when values remain
external. This also keeps application credentials, Tailscale credentials, model
provider keys, admin passwords, and private hostnames out of the public repo.

**Alternatives considered**:

- AWS Secrets Manager: viable, but not selected by clarification.
- 1Password Connect: viable, but adds another controller and credential path.
- Sealed secrets: rejected for this feature because the selected source of
  runtime secret material is AWS SSM Parameter Store.

## Storage, Backup, And Rollback

**Decision**: Add an NFS-backed Kubernetes StorageClass using the existing NFS
provisioner and mark it as the cluster default. The feature does not install,
replace, or take ownership of the NFS provisioner. Implementation must discover
the existing provisioner through read-only cluster inspection, commit only
public-safe provisioner details, and require documented NFS backup coverage
before stateful apps roll out.

Require a stateful workload profile for each app before rollout. Prometheus,
Grafana, Tines, Prowlarr, Radarr, Sonarr, Deluge, OpenClaw, and LiteLLM must
document persistent data, backup coverage, restore behavior, and rollback data
handling.
Platform controllers document whether they are stateless or rely only on
controller-managed runtime objects.

**Rationale**: The constitution requires stateful workload implications before
rollout. This feature includes observability, automation, media, and AI
services where data loss or rollback can surprise an operator. Reusing the
existing provisioner avoids expanding infrastructure ownership while the default
StorageClass gives stateful apps a consistent storage target.

**Alternatives considered**:

- Defer backup decisions to after deployment: rejected by constitution and spec
  requirements.
- Treat all applications as stateless: rejected because several workloads
  clearly persist configuration, history, indexes, downloads, dashboards, or
  model-routing state.
- Install a new NFS provisioner: rejected because clarification selected the
  existing provisioner as an external prerequisite outside feature ownership.
- Assume a provisioner name without inspection: rejected because the repo should
  capture observed desired state rather than guessing live cluster details.

## Descheduler Safety

**Decision**: Start with a conservative descheduler policy that avoids
control-plane, storage-sensitive, and single-replica stateful workloads unless a
future change documents a safer expansion.

**Rationale**: Descheduler can improve cluster hygiene, but a homelab often has
small replica counts and fragile storage locality. A conservative policy lowers
operational risk.

**Alternatives considered**:

- Enable aggressive eviction policies immediately: rejected because it increases
  outage risk.
- Defer descheduler entirely: rejected because the user explicitly added it to
  the Argo CD onboarding scope.

## LiteLLM Onboarding Mode

**Decision**: Onboard LiteLLM as a tailnet-only model gateway with provider
credentials and model-routing secrets referenced from AWS SSM Parameter Store.
Any persistent database or config-store choice must be documented in the
stateful workload profile before rollout.

**Rationale**: LiteLLM centralizes model-provider credentials and routing for
OpenClaw while preserving the public repository's secret-safety rules.

**Alternatives considered**:

- Direct provider credentials in OpenClaw: rejected because it duplicates secret
  and routing configuration.
- Public LiteLLM exposure: rejected for first rollout because all apps are
  tailnet-only.
