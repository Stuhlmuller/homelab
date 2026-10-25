# Argo CD App Onboarding

This feature registers requested homelab applications plus supporting
Applications for shared platform dependencies. `platform-dns` owns CoreDNS
resolver policy, `platform-storage` owns the QNAP-backed NFS provisioner and
default StorageClass desired state, and `media-postgres` owns the shared
PostgreSQL instance for Sonarr, Radarr, and Prowlarr. `n8n-postgres` owns the
dedicated PostgreSQL instance for n8n. These support apps are not counted as
requested workloads.

## Project Boundaries

`homelab-workloads` allows only the repository, the pinned app-template chart
repository, three workload namespaces, and no cluster-scoped resources.
Dispatcharr, OpenClaw, Policy Bot, and Prowlarr use it. Their committed overlays
and pinned app-template renders are entirely namespaced.

Platform controllers, storage workloads, and applications with additional
cluster-resource requirements remain in `homelab`. `n8n-postgres` also remains
there because its existing `CreateNamespace` and managed namespace metadata
contract reconciles the cluster-scoped `automation` Namespace. New applications
use the most restrictive existing project that covers their rendered sources,
destination, and resources.

The staged OpenClaw Enterprise Applications use `openclaw-enterprise`, which
allows only this repository, the pinned upstream Git chart repository, the
`openclaw-system`, `openclaw-agents` and `envoy-gateway-system` namespaces, and
the rendered installation resource kinds. Enterprise itself owns agent
Deployments, policies, Secrets and claims in `openclaw-agents`; the foundation
Application owns only the namespace, exact credential projection and three
cross-namespace RoleBindings there.

## Applications

| App                             | Kind              | Namespace               | GitOps path                                                                | Terragrunt path                                        | Auto-sync     | Dependencies                                                                                       |
| ------------------------------- | ----------------- | ----------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------ | ------------- | -------------------------------------------------------------------------------------------------- |
| platform-image-policy           | support           | cluster-scoped          | `clusters/homelab/platform/image-policy`                                   | `IaC/homelab/us-west-2/apps/platform-image-policy/argocd`           | Yes           | none (audit-only)                                                                                  |
| platform-network-policy         | staged            | `kube-system`           | `clusters/homelab/platform/network-policy`                                 | `IaC/homelab/us-west-2/apps/platform-network-policy/argocd`         | No, no prune  | platform-dns; admission and canary qualification before activation                                 |
| platform-network-policy-canary  | staged            | `network-policy-canary` | `clusters/homelab/platform/network-policy/canary`                          | `IaC/homelab/us-west-2/apps/platform-network-policy-canary/argocd`  | No, no prune  | platform-network-policy; tainted node and mirrored fixtures before activation                      |
| platform-network-policy-cleanup | staged            | `kube-system`           | `clusters/homelab/platform/network-policy/cleanup`                         | `IaC/homelab/us-west-2/apps/platform-network-policy-cleanup/argocd` | No, no prune  | platform-network-policy; reviewed owner-only cleanup after tenant quiescence                       |
| platform-dns                    | support           | `kube-system`           | `clusters/homelab/platform/dns`                                            | `IaC/homelab/us-west-2/apps/platform-dns/argocd`                    | Yes, no prune | Argo CD bootstrap                                                                                  |
| platform-envoy-gateway          | staged            | `envoy-gateway-system`  | `clusters/homelab/platform/envoy-gateway`                                  | `IaC/homelab/us-west-2/apps/platform-envoy-gateway/argocd`          | No, no prune  | istio, cert-manager; image publication and Gateway API qualification before activation             |
| platform-storage                | support           | cluster-scoped          | `clusters/homelab/platform/storage`                                        | `IaC/homelab/us-west-2/apps/platform-storage/argocd`                | Yes           | QNAP NFS export validation                                                                         |
| metrics-server                  | support           | `kube-system`           | official `metrics-server` Helm chart                                       | `IaC/homelab/us-west-2/apps/metrics-server/argocd`                  | Yes           | Kubernetes API and node kubelets                                                                   |
| media-postgres                  | support           | `media`                 | `clusters/homelab/apps/media-postgres`                                     | `IaC/homelab/us-west-2/apps/media-postgres/argocd`                  | Yes           | external-secrets, platform-storage                                                                 |
| n8n-postgres                    | support           | `automation`            | `clusters/homelab/apps/n8n-postgres`                                       | `IaC/homelab/us-west-2/apps/n8n-postgres/argocd`                    | Yes           | external-secrets, platform-storage                                                                 |
| affine                          | requested         | `affine`                | `clusters/homelab/apps/affine`                                             | `IaC/homelab/us-west-2/apps/affine/argocd`                          | Yes           | external-secrets, cert-manager, istio, octelium, octelium-public, platform-storage                 |
| fleet                           | requested         | `fleet`                 | `clusters/homelab/apps/fleet`                                              | `IaC/homelab/us-west-2/apps/fleet/argocd`                           | Yes           | aws-ssm-parameters, external-secrets, cert-manager, istio, platform-storage, octelium-public       |
| external-secrets                | requested         | `external-secrets`      | `clusters/homelab/apps/external-secrets`                                   | `IaC/homelab/us-west-2/apps/external-secrets/argocd`                | Yes           | platform-dns                                                                                       |
| cert-manager                    | requested         | `cert-manager`          | `clusters/homelab/apps/cert-manager`                                       | `IaC/homelab/us-west-2/apps/cert-manager/argocd`                    | Yes           | external-secrets                                                                                   |
| istio                           | requested         | `istio-system`          | `clusters/homelab/apps/istio`                                              | `IaC/homelab/us-west-2/apps/istio/argocd`                           | Yes           | cert-manager                                                                                       |
| tailscale                       | requested         | `tailscale`             | `clusters/homelab/apps/tailscale`                                          | `IaC/homelab/us-west-2/apps/tailscale/argocd`                       | Yes           | external-secrets                                                                                   |
| octelium                        | requested         | `octelium-client`       | `clusters/homelab/apps/octelium`                                           | `IaC/homelab/us-west-2/apps/octelium/argocd`                        | Yes           | external-secrets, istio                                                                            |
| octelium-enterprise             | requested         | `octelium`              | `clusters/homelab/apps/octelium-enterprise`                                | `IaC/homelab/us-west-2/apps/octelium-enterprise/argocd`             | Yes           | octelium-cluster, octelium-storage, platform-storage                                               |
| prometheus                      | requested         | `monitoring`            | `clusters/homelab/apps/prometheus`                                         | `IaC/homelab/us-west-2/apps/prometheus/argocd`                      | Yes           | external-secrets, platform-storage                                                                 |
| grafana                         | requested         | `monitoring`            | `clusters/homelab/apps/grafana`                                            | `IaC/homelab/us-west-2/apps/grafana/argocd`                         | Yes           | external-secrets, cert-manager, istio, prometheus, platform-storage                                |
| kiali                           | requested         | `monitoring`            | `clusters/homelab/apps/kiali`                                              | `IaC/homelab/us-west-2/apps/kiali/argocd`                           | Yes           | istio, prometheus, grafana                                                                         |
| compass                         | requested         | `monitoring`            | `clusters/homelab/apps/compass`                                            | `IaC/homelab/us-west-2/apps/compass/argocd`                         | Yes           | cert-manager, istio, prometheus                                                                    |
| descheduler                     | requested         | `kube-system`           | `clusters/homelab/apps/descheduler/values.yaml`                            | `IaC/homelab/us-west-2/apps/descheduler/argocd`                     | Yes           | prometheus                                                                                         |
| deluge                          | requested         | `media`                 | `clusters/homelab/apps/deluge`                                             | `IaC/homelab/us-west-2/apps/deluge/argocd`                          | Yes           | cert-manager, istio, platform-storage                                                              |
| dispatcharr                     | requested         | `media`                 | `clusters/homelab/apps/dispatcharr`                                        | `IaC/homelab/us-west-2/apps/dispatcharr/argocd`                     | Yes           | external-secrets, cert-manager, istio, platform-storage                                            |
| prowlarr                        | requested         | `media`                 | `clusters/homelab/apps/prowlarr`                                           | `IaC/homelab/us-west-2/apps/prowlarr/argocd`                        | Yes           | cert-manager, istio, media-postgres, platform-storage                                              |
| bazarr                          | requested         | `media`                 | `clusters/homelab/apps/bazarr`                                             | `IaC/homelab/us-west-2/apps/bazarr/argocd`                          | Yes           | platform-storage, radarr, sonarr                                                                   |
| radarr                          | requested         | `media`                 | `clusters/homelab/apps/radarr`                                             | `IaC/homelab/us-west-2/apps/radarr/argocd`                          | Yes           | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                            |
| sonarr                          | requested         | `media`                 | `clusters/homelab/apps/sonarr`                                             | `IaC/homelab/us-west-2/apps/sonarr/argocd`                          | Yes           | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                            |
| langfuse                        | requested         | `langfuse`              | `clusters/homelab/apps/langfuse`                                           | `IaC/homelab/us-west-2/apps/langfuse/argocd`                        | Yes           | aws-ssm-parameters, external-secrets, cert-manager, istio, platform-storage, langfuse-blob-storage |
| litellm                         | requested         | `ai`                    | `clusters/homelab/apps/litellm`                                            | `IaC/homelab/us-west-2/apps/litellm/argocd`                         | Yes           | external-secrets, cert-manager, istio, platform-storage, langfuse                                  |
| openclaw                        | requested         | `ai`                    | `clusters/homelab/apps/openclaw`                                           | `IaC/homelab/us-west-2/apps/openclaw/argocd`                        | Yes           | external-secrets, cert-manager, istio, litellm, platform-storage                                   |
| openclaw-enterprise-foundation  | staged            | `openclaw-system`       | `clusters/homelab/apps/openclaw-enterprise-foundation`                     | `IaC/homelab/us-west-2/apps/openclaw-enterprise-foundation/argocd`  | No, no prune  | aws-ssm-parameters, external-secrets, cert-manager, platform-storage                               |
| openclaw-enterprise             | staged            | `openclaw-system`       | pinned upstream Git chart plus `clusters/homelab/apps/openclaw-enterprise` | `IaC/homelab/us-west-2/apps/openclaw-enterprise/argocd`             | No, no prune  | openclaw-enterprise-foundation, platform-envoy-gateway                                             |
| n8n                             | requested         | `automation`            | `clusters/homelab/apps/n8n`                                                | `IaC/homelab/us-west-2/apps/n8n/argocd`                             | Yes           | external-secrets, cert-manager, istio, platform-storage, n8n-postgres                              |
| mastodon                        | requested (draft) | `mastodon`              | `clusters/homelab/apps/mastodon`                                           | `IaC/homelab/us-west-2/apps/mastodon/argocd`                        | Yes           | aws-ssm-parameters, external-secrets, cert-manager, istio, octelium-public, platform-storage       |
| nofx                            | requested         | `nofx`                  | `clusters/homelab/apps/nofx`                                               | `IaC/homelab/us-west-2/apps/nofx/argocd`                            | Yes           | external-secrets, istio, octelium, litellm, platform-storage                                       |
| policy-bot                      | requested         | `automation`            | `clusters/homelab/apps/policy-bot`                                         | `IaC/homelab/us-west-2/apps/policy-bot/argocd`                      | Yes           | external-secrets, cert-manager, istio                                                              |
| renovate                        | requested         | `automation`            | `clusters/homelab/apps/renovate`                                           | `IaC/homelab/us-west-2/apps/renovate/argocd`                        | Yes           | aws-ssm-parameters, external-secrets, platform-storage                                             |

## Dependency Readiness

`dependencies` blocks in Terragrunt order Argo CD Application registration.
They do not prove runtime readiness by themselves. An app is considered
available for a dependent app only after:

1. The upstream Argo CD Application is registered by Terragrunt.
2. Argo CD reports the upstream app `Synced`.
3. Argo CD reports the upstream app `Healthy`, or an exception is recorded in
   `docs/validation-runbook.md`.

The Enterprise declarations keep automatic sync, pruning, self-heal and sync
retries disabled. Before release, verify the foundation is `Synced`/`Healthy`
and check PostgreSQL TLS/roles and ExternalSecret readiness separately. The
shared Argo controller bounds each sync operation to 15 minutes; Enterprise
preflight adds a 180-second dependency check before migration. Registration
order alone does not satisfy these gates. The protected fixed `full-sync` stage
is source-tested but remains unavailable until both Applications are registered
and prerequisites pass. Selective sync and `ApplyOutOfSyncOnly` are outside the
declared release path.

The legacy `openclaw` Application remains registered for retained recovery,
with its gateway at zero replicas and backup CronJob suspended. The separate
Enterprise journal-operator bundle is source-only and has no Argo or Terragrunt
registration; its reconciliation stages remain disabled pending placement,
image and private bootstrap-key proof.

Stateful apps auto-sync by default, but they are not considered operationally
ready until `platform-storage` is synced, the `nfs-default` StorageClass is
verified, and `docs/storage-nfs.md` records backup coverage.

Sonarr, Deluge, and Radarr keep active config on retained local volumes pinned
to `zimaboard-0` and archive it nightly to their retained NFS claims. All three
apps use static claims against the QNAP `/media` export for media-library
paths. Read-only
`showmount -e 10.1.0.2` verifies the required `/media` export before rollout.

Bazarr keeps its SQLite database and config on a retained local volume on
`zimaboard-0`, with a separate retained NFS backup claim. It reuses
`media-tv` at `/tv` and `media-movies` at `/movies`; Sonarr and Radarr retain
ownership of those claims. Acceptance requires both library synchronizations,
an English subtitle beside an existing media file, and a verified backup.
See [the Bazarr runbook](../clusters/homelab/apps/bazarr/README.md).

Sonarr, Radarr, and Prowlarr are also not considered ready until
`media-postgres` is synced, the `media-postgres-auth` and
`media-postgres-arr-env` ExternalSecrets are ready, the six logical databases
exist, `media-postgres-local-0` is Ready on `acer`, and the Service EndpointSlice
contains only the local pod. Require a verified scheduled backup and successful
indexer searches in Prowlarr, Sonarr, and Radarr. Each app's `config.xml` must
also contain the official Servarr PostgreSQL fields, and any required
SQLite-to-PostgreSQL data migration must be complete.

n8n is not considered ready until `n8n-postgres` is synced and healthy, the
`n8n-postgres-auth` and `n8n-postgres-client` ExternalSecrets are ready, the
`n8n` database exists, and any required SQLite export/import migration has been
completed.

Renovate registration initially creates a suspended, full dry-run CronJob.
Readiness requires its App ExternalSecret, retained cache claim, and a successful
dry-run parity check. The separate GitHub Actions runner remains the only writer
until its complete workflow is removed, every unfinished run drains, and its
repository Actions private key is retired through the guarded receipt. See the
[Renovate runbook](../clusters/homelab/apps/renovate/README.md) for cutover and
rollback.

AFFiNE is not considered ready until its ExternalSecret, PostgreSQL 16 with the
pgvector extension, authenticated Redis, migration init container, four
retained NFS claims, Istio route, Octelium `WEB` Service, Cloudflare Tunnel
ingress, and public DNS record have all reconciled successfully.

Langfuse is not ready until its ExternalSecret is Ready, its three retained
`nfs-default` claims are Bound, PostgreSQL, Valkey, and ClickHouse are Healthy,
the S3 credential parameters exist, and the protected UI responds through
Octelium. LiteLLM registration follows Langfuse, but that does not gate runtime
readiness. Existing caller runtime remains unchanged while these prerequisites
reconcile. Activate telemetry only in a follow-up after the
[caller readiness gates](../clusters/homelab/apps/langfuse/README.md#caller-activation)
pass.

## Registration Provider

Terragrunt registers Applications through the repository-local
`IaC/terragrunt-catalog/modules/argocd-application-kubernetes` module. The module writes Argo CD
`Application` CRDs through the Kubernetes provider, so routine registration does
not require an exposed Argo CD API endpoint, an auth token in operator
environment variables, or a manual local `argocd login`. The shared unit
generates a raw CRD-shaped `manifest`; app overrides use Argo CD field names.

## Register With Shared Defaults

Register the unit in `IaC/homelab/us-west-2/apps/<app>/terragrunt.stack.hcl` and keep its settings in
`IaC/homelab/us-west-2/apps/<app>/stack.hcl`. All active workload and platform Applications use
`IaC/terragrunt-catalog/units/live/argocd-app`. Do not edit ignored generated files under
`IaC/homelab/us-west-2/apps`.

Add the unit to the app stack:

```hcl
unit "argocd_apps_example" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/argocd-app"
  path                    = "argocd"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}
```

Create `IaC/homelab/us-west-2/apps/example/stack.hcl`:

```hcl
locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets"]
  spec = {
    project = "homelab-workloads"
  }
}
```

These app files are ordinary Terragrunt configuration fragments. Keep the name
`stack.hcl`: only the root `terragrunt.stack.hcl` declares generated units.

This example assumes the selected AppProject already permits the app's sources,
namespace, and rendered resources. The directory basename supplies the
Application name, destination namespace, and default
`clusters/homelab/apps/<name>` source. `IaC/stack-defaults.hcl` owns shared
repository/revision, metadata labels, destination server, project, automated
sync, retry, and sync options. Add `spec.destination.namespace` or `spec.sources` for exceptions.
Keep existing unit paths stable: they determine remote-state keys.

The app file's `inputs.metadata` and `inputs.spec` become sparse CRD overrides
in the generated unit's `values`. The template merges
metadata labels, destination, sync policy, automated sync, retry, and backoff
maps. Other fields replace their defaults; lists always replace, including
`sources`, `syncOptions`, `info`, and `ignoreDifferences`. Use
`syncPolicy.automated.enabled = false` to disable automatic sync. Do not use
`null` to remove the required merge maps.

Helm applications keep explicit chart repository, chart, pinned revision,
release name, and values files in `spec.sources`; see
[Helm chart organization](../openwiki/patterns/helm-chart-organization.md).
Dependencies are relative to the sibling application directory: use an app name
for another Application and `../aws-ssm-parameters` for that shared AWS unit.
Bootstrap installs Argo CD before its CRDs exist. Argo's self-management, Cordium's bootstrap
child, and the two storage provisioner children retain their existing lifecycle
owners; their parent deployments are registered by this same stack.

Generate and inspect one application before running the repository gate:

```sh
terragrunt --working-dir IaC stack generate
terragrunt --log-disable --working-dir IaC/homelab/us-west-2/apps/example/argocd \
  render --json --write=false --no-color \
  | jq '{manifest: .inputs.manifest, dependencies: .dependencies.paths}'
terragrunt hcl fmt --check
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

OpenTofu initialization generates local `.terraform.lock.hcl` files, which are
ignored; do not copy or commit them. Exact provider versions live in
module/template HCL; CI regenerates locks and checksums during init. The protected
pipeline still plans and applies those units. Roll back a registration refactor
by reverting the stack/template changes together and regenerating; no backend
migration is needed when the unit paths remain unchanged.

## Image Updates

Renovate manages repo-declared workload image tags and digests through reviewed
pull requests against `main`. All committed images must be pinned as
`tag@sha256:digest`; do not add live-only Argo CD parameter overrides for image
drift. See `docs/image-automation.md` for update policy.

## Sync And Health Exception Record

Use this format for every exception:

```text
App:
Observed status:
Blocking dependency:
Operator action:
Rollback decision:
Follow-up issue or PR:
```
