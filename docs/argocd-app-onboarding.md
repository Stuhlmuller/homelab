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

## Applications

| App                   | Kind                      | Namespace               | GitOps path                                     | Terragrunt path                              | Auto-sync     | Dependencies                                                                                       |
| --------------------- | ------------------------- | ----------------------- | ----------------------------------------------- | -------------------------------------------- | ------------- | -------------------------------------------------------------------------------------------------- |
| platform-dns          | support                   | `kube-system`           | `clusters/homelab/platform/dns`                 | `IaC/live/argocd-apps/platform-dns`          | Yes, no prune | Argo CD bootstrap                                                                                  |
| platform-storage      | support                   | cluster-scoped          | `clusters/homelab/platform/storage`             | `IaC/live/argocd-apps/platform-storage`      | Yes           | QNAP NFS export validation                                                                         |
| metrics-server        | support                   | `kube-system`           | official `metrics-server` Helm chart            | `IaC/live/argocd-apps/metrics-server`        | Yes           | Kubernetes API and node kubelets                                                                   |
| media-postgres        | support                   | `media`                 | `clusters/homelab/apps/media-postgres`          | `IaC/live/argocd-apps/media-postgres`        | Yes           | external-secrets, platform-storage                                                                 |
| n8n-postgres          | support                   | `automation`            | `clusters/homelab/apps/n8n-postgres`            | `IaC/live/argocd-apps/n8n-postgres`          | Yes           | external-secrets, platform-storage                                                                 |
| affine                | requested                 | `affine`                | `clusters/homelab/apps/affine`                  | `IaC/live/argocd-apps/affine`                | Yes           | external-secrets, cert-manager, istio, octelium, octelium-public, platform-storage                 |
| fleet                 | requested                 | `fleet`                 | `clusters/homelab/apps/fleet`                   | `IaC/live/argocd-apps/fleet`                 | Yes           | aws-ssm-parameters, external-secrets, cert-manager, istio, platform-storage, octelium-public       |
| external-secrets      | requested                 | `external-secrets`      | `clusters/homelab/apps/external-secrets`        | `IaC/live/argocd-apps/external-secrets`      | Yes           | platform-dns                                                                                       |
| cert-manager          | requested                 | `cert-manager`          | `clusters/homelab/apps/cert-manager`            | `IaC/live/argocd-apps/cert-manager`          | Yes           | external-secrets                                                                                   |
| istio                 | requested                 | `istio-system`          | `clusters/homelab/apps/istio`                   | `IaC/live/argocd-apps/istio`                 | Yes           | cert-manager                                                                                       |
| tailscale             | requested                 | `tailscale`             | `clusters/homelab/apps/tailscale`               | `IaC/live/argocd-apps/tailscale`             | Yes           | external-secrets                                                                                   |
| octelium              | requested                 | `octelium-client`       | `clusters/homelab/apps/octelium`                | `IaC/live/argocd-apps/octelium`              | Yes           | external-secrets, istio                                                                            |
| octelium-enterprise   | requested                 | `octelium`              | `clusters/homelab/apps/octelium-enterprise`     | `IaC/live/argocd-apps/octelium-enterprise`   | Yes           | octelium-cluster, octelium-storage, platform-storage                                               |
| prometheus            | requested                 | `monitoring`            | `clusters/homelab/apps/prometheus`              | `IaC/live/argocd-apps/prometheus`            | Yes           | external-secrets, platform-storage                                                                 |
| grafana               | requested                 | `monitoring`            | `clusters/homelab/apps/grafana`                 | `IaC/live/argocd-apps/grafana`               | Yes           | external-secrets, cert-manager, istio, prometheus, platform-storage                                |
| kiali                 | requested                 | `monitoring`            | `clusters/homelab/apps/kiali`                   | `IaC/live/argocd-apps/kiali`                 | Yes           | istio, prometheus, grafana                                                                         |
| compass               | requested                 | `monitoring`            | `clusters/homelab/apps/compass`                 | `IaC/live/argocd-apps/compass`               | Yes           | cert-manager, istio, prometheus                                                                    |
| descheduler           | requested                 | `kube-system`           | `clusters/homelab/apps/descheduler/values.yaml` | `IaC/live/argocd-apps/descheduler`           | Yes           | prometheus                                                                                         |
| deluge                | requested                 | `media`                 | `clusters/homelab/apps/deluge`                  | `IaC/live/argocd-apps/deluge`                | Yes           | cert-manager, istio, platform-storage                                                              |
| dispatcharr           | requested                 | `media`                 | `clusters/homelab/apps/dispatcharr`             | `IaC/live/argocd-apps/dispatcharr`           | Yes           | external-secrets, cert-manager, istio, platform-storage                                            |
| prowlarr              | requested                 | `media`                 | `clusters/homelab/apps/prowlarr`                | `IaC/live/argocd-apps/prowlarr`              | Yes           | cert-manager, istio, media-postgres, platform-storage                                              |
| bazarr                | requested                 | `media`                 | `clusters/homelab/apps/bazarr`                  | `IaC/live/argocd-apps/bazarr`                | Yes           | platform-storage, radarr, sonarr                                                                   |
| radarr                | requested                 | `media`                 | `clusters/homelab/apps/radarr`                  | `IaC/live/argocd-apps/radarr`                | Yes           | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                            |
| sonarr                | requested                 | `media`                 | `clusters/homelab/apps/sonarr`                  | `IaC/live/argocd-apps/sonarr`                | Yes           | cert-manager, istio, deluge, media-postgres, prowlarr, platform-storage                            |
| langfuse              | requested                 | `langfuse`              | `clusters/homelab/apps/langfuse`                | `IaC/live/argocd-apps/langfuse`              | Yes           | aws-ssm-parameters, external-secrets, cert-manager, istio, platform-storage, langfuse-blob-storage |
| litellm               | requested                 | `ai`                    | `clusters/homelab/apps/litellm`                 | `IaC/live/argocd-apps/litellm`               | Yes           | external-secrets, cert-manager, istio, platform-storage, langfuse                                  |
| openclaw              | requested                 | `ai`                    | `clusters/homelab/apps/openclaw`                | `IaC/live/argocd-apps/openclaw`              | Yes           | external-secrets, cert-manager, istio, litellm, platform-storage                                   |
| n8n                   | requested                 | `automation`            | `clusters/homelab/apps/n8n`                     | `IaC/live/argocd-apps/n8n`                   | Yes           | external-secrets, cert-manager, istio, platform-storage, n8n-postgres                              |
| nofx                  | requested                 | `nofx`                  | `clusters/homelab/apps/nofx`                    | `IaC/live/argocd-apps/nofx`                  | Yes           | external-secrets, istio, octelium, litellm, platform-storage                                       |
| policy-bot            | requested                 | `automation`            | `clusters/homelab/apps/policy-bot`              | `IaC/live/argocd-apps/policy-bot`            | Yes           | external-secrets, cert-manager, istio                                                              |
| octobot               | requested                 | `finance`               | `clusters/homelab/apps/octobot`                 | `IaC/live/argocd-apps/octobot`               | Yes           | cert-manager, istio, platform-storage                                                              |

## Dependency Readiness

`dependencies` blocks in Terragrunt order Argo CD Application registration.
They do not prove runtime readiness by themselves. An app is considered
available for a dependent app only after:

1. The upstream Argo CD Application is registered by Terragrunt.
2. Argo CD reports the upstream app `Synced`.
3. Argo CD reports the upstream app `Healthy`, or an exception is recorded in
   `docs/validation-runbook.md`.

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
`IaC/modules/argocd-application-kubernetes` module. The module writes Argo CD
`Application` CRDs through the Kubernetes provider, so routine registration does
not require an exposed Argo CD API endpoint, an auth token in operator
environment variables, or a manual local `argocd login`. The shared unit
generates a raw CRD-shaped `manifest`; app overrides use Argo CD field names.

## Register With Shared Defaults

Register the unit in `IaC/terragrunt.stack.hcl` and keep its settings in
`IaC/stacks/<app>/stack.hcl`. All active workload and platform Applications use
`IaC/.catalog/units/live/argocd-app`. Do not edit ignored generated files under
`IaC/live/argocd-apps`.

Add the unit to the root index:

```hcl
unit "argocd_apps_example" {
  source                 = "./.catalog/units/live/argocd-app"
  path                   = "live/argocd-apps/example"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/example/stack.hcl").inputs
}
```

Create `IaC/stacks/example/stack.hcl`:

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
for another Application and `../../aws-ssm-parameters` for that shared AWS unit.
Bootstrap installs Argo CD before its CRDs exist. Argo's self-management, Cordium's bootstrap
child, and the two storage provisioner children retain their existing lifecycle
owners; their parent deployments are registered by this same stack.

Generate and inspect one application before running the repository gate:

```sh
terragrunt --working-dir IaC stack generate
terragrunt --log-disable --working-dir IaC/live/argocd-apps/example \
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
