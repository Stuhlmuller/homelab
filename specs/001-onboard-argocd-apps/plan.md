# Implementation Plan: Argo CD Application Onboarding

**Branch**: `001-onboard-argocd-apps` | **Date**: 2026-05-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-onboard-argocd-apps/spec.md`

## Summary

Onboard 15 homelab applications into Argo CD through Terragrunt catalog modules:
Istio, external-secrets, certificates-manager, Grafana, Prometheus, OpenClaw,
Tines, Prowlarr, Radarr, Sonarr, Deluge, descheduler, Tailscale, LiteLLM, and
Argo CD Image Updater. The
implementation will create one Terragrunt unit per requested Argo CD
Application plus one supporting `platform-storage` registration for the default
StorageClass, source the `argocd-application` catalog module by default, wire
all cross-app ordering with explicit Terragrunt `dependencies`, and keep
runtime configuration in repo-owned values/manifests with secret values
referenced from AWS SSM Parameter Store.

Argo CD Applications enable automated prune and self-heal by default. Argo CD
Image Updater is installed as an opt-in controller that requires per-Application
labels and image annotations before changing image references.

The first rollout is tailnet-only: Istio is the reverse proxy, Tailscale is the
reachability layer, and no Tailscale Funnel paths are enabled. DNS must be
configured once so future internal app routes and explicitly approved Funnel
webhook paths do not require per-app DNS record edits.

Stateful workloads use an NFS-backed default Kubernetes StorageClass. This
feature does not install or replace the NFS provisioner; implementation must
discover the existing provisioner through read-only inspection, commit only
public-safe provisioner details, and document NFS backup coverage before
stateful applications roll out.

## Technical Context

**Language/Version**: HCL for Terragrunt/OpenTofu; Kubernetes YAML and Helm values for GitOps desired state
**Primary Dependencies**: Terragrunt catalog modules `argocd-application` and, only when exact CRD control is required, `argocd-application-manifest`; Argo CD; Argo CD Image Updater; Helm/Kustomize-compatible application sources; AWS SSM Parameter Store through external-secrets
**Storage**: Default NFS-backed Kubernetes StorageClass using an existing provisioner discovered via read-only inspection; Kubernetes persistent volumes for stateful apps that require data retention: Prometheus, Grafana, Tines, Prowlarr, Radarr, Sonarr, Deluge, OpenClaw, and LiteLLM when configured with persistent state; no persistent storage expected for cert-manager, external-secrets, Istio, Tailscale, or descheduler except controller-managed runtime objects
**Testing**: Terragrunt HCL formatting and planning; OpenTofu validation through Terragrunt; Helm rendering or Argo CD source rendering for each app; Kubernetes server-side dry-run or `kubectl diff` for repo-owned manifests; post-rollout Argo CD sync/health checks
**Target Platform**: Talos Linux Kubernetes homelab cluster reachable at the documented Kubernetes API endpoint
**Project Type**: Infrastructure-as-code and GitOps Kubernetes application onboarding
**Infrastructure Entry Point**: `IaC/live/argocd-apps/**/terragrunt.hcl` with shared settings from `IaC/root.hcl`; repo-owned app values under `clusters/homelab/apps/**`; cluster storage desired state under `clusters/homelab/platform/storage/**` registered by `IaC/live/argocd-apps/platform-storage/terragrunt.hcl`
**Delivery Mechanism**: Terragrunt/OpenTofu registers Argo CD Applications; Argo CD reconciles Helm/Kustomize/raw manifest app desired state
**Secrets Model**: External Secrets reads runtime secret material from AWS SSM Parameter Store; public repository commits only ExternalSecret resources, parameter names/paths, and non-secret defaults
**Performance Goals**: Argo CD reaches the documented sync/health expectation for all 15 applications within 30 minutes after rollout; reviewers can identify each app path and dependency edge in under 5 minutes
**Constraints**: Zero committed secrets; zero public Tailscale Funnel paths in first rollout; no DNS record additions or edits after initial DNS setup; no manual Argo CD UI creation or one-off live Kubernetes edits; explicit Terragrunt dependencies for every app ordering relationship; automated prune and self-heal by default; no NFS provisioner ownership; stateful readiness blocked until NFS backup coverage is documented
**Scale/Scope**: 15 requested Argo CD Applications plus one supporting storage Application registration for the default NFS StorageClass, supporting values, route manifests, secret references, storage notes, image update policy, validation, and rollback documentation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Repository Source of Truth**: PASS. All persistent changes are planned as
  committed Terragrunt units, Argo CD application definitions, repo-owned values
  or manifests, and documentation.
- **OpenTofu/Terragrunt**: PASS. Argo CD application registration is performed
  with Terragrunt catalog modules from `IaC/live/argocd-apps/**`.
- **GitOps Kubernetes Delivery**: PASS. Kubernetes runtime behavior is delivered
  by Argo CD Applications that point at Helm/Kustomize/raw manifest sources.
- **Secret Safety**: PASS. Runtime secrets are represented only as AWS SSM
  Parameter Store references and ExternalSecret manifests; no plaintext secret
  values are planned.
- **Modularity**: PASS. Repeated app registration uses one unit shape and shared
  app defaults, with one short per-app configuration surface.
- **Validation**: PASS. The plan names Terragrunt/OpenTofu planning, Argo CD or
  Helm rendering, server-side dry-run/diff where applicable, and post-rollout
  health checks.
- **Operations Documentation**: PASS. Storage, backup, ingress, DNS, rollback,
  dependency, and failure-mode decisions are documented in the generated design
  artifacts and must be carried into implementation docs.

## Project Structure

### Documentation (this feature)

```text
specs/001-onboard-argocd-apps/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── argocd-app-onboarding.md
└── tasks.md
```

### Repository Paths (repository root)

```text
IaC/root.hcl
IaC/live/argocd-apps/
├── platform-storage/terragrunt.hcl
├── argocd-image-updater/terragrunt.hcl
├── external-secrets/terragrunt.hcl
├── cert-manager/terragrunt.hcl
├── istio/terragrunt.hcl
├── tailscale/terragrunt.hcl
├── prometheus/terragrunt.hcl
├── grafana/terragrunt.hcl
├── descheduler/terragrunt.hcl
├── deluge/terragrunt.hcl
├── prowlarr/terragrunt.hcl
├── radarr/terragrunt.hcl
├── sonarr/terragrunt.hcl
├── litellm/terragrunt.hcl
├── openclaw/terragrunt.hcl
└── tines/terragrunt.hcl
clusters/homelab/apps/
├── argocd-image-updater/
├── external-secrets/
├── cert-manager/
├── istio/
├── tailscale/
├── prometheus/
├── grafana/
├── descheduler/
├── deluge/
├── prowlarr/
├── radarr/
├── sonarr/
├── litellm/
├── openclaw/
└── tines/
clusters/homelab/platform/storage/
├── default-nfs-storageclass.yaml
├── kustomization.yaml
└── README.md
docs/argocd-app-onboarding.md
docs/networking-tailnet-ingress.md
docs/storage-nfs.md
```

**Structure Decision**: Use `IaC/live/argocd-apps/<app>/terragrunt.hcl` as the
operator entry point for app registration and `clusters/homelab/apps/<app>/` as
the GitOps source for values, overlays, ExternalSecrets, Istio routing, and app
documentation. The current checkout does not yet contain these directories, so
implementation will create them without moving existing runtime files.
Use `clusters/homelab/platform/storage/` for the default NFS StorageClass and
its public-safe provisioner notes, registered through the supporting
`platform-storage` Argo CD Application, without taking ownership of the existing
NFS provisioner.

## Phase 0: Research Summary

See [research.md](research.md).

Resolved decisions:

- Use the catalog `argocd-application` module for normal app registration.
- Use `argocd-application-manifest` only if the typed provider schema blocks a
  required Application field.
- Use one Terragrunt unit per Argo CD Application so dependencies are explicit
  and reviewable.
- Use Istio as the reverse proxy and Tailscale as the reachability layer.
- Keep first rollout tailnet-only with no public Funnel paths.
- Use AWS SSM Parameter Store as the External Secrets backend.
- Treat storage and backup decisions as required per-app documentation before
  rollout.
- Use an existing NFS provisioner discovered by read-only inspection; add only
  the default NFS-backed StorageClass through a supporting `platform-storage`
  registration and require documented backup coverage before stateful rollout.

## Phase 1: Design Summary

See [data-model.md](data-model.md), [quickstart.md](quickstart.md), and
[contracts/argocd-app-onboarding.md](contracts/argocd-app-onboarding.md).

Design outputs define:

- Application onboarding fields and dependency edges.
- Per-app namespace, dependency, ingress, storage, and secret expectations.
- Terragrunt unit contract for catalog-backed Argo CD Applications.
- Route and secret-reference contracts for tailnet-only first rollout.
- Default NFS StorageClass and backup-gated stateful workload requirements.
- Validation and rollback runbook for planning and implementation.

## Post-Design Constitution Check

- **Repository Source of Truth**: PASS. Planned code paths are concrete:
  `IaC/live/argocd-apps/**`, `clusters/homelab/apps/**`, and docs under
  `docs/**`.
- **OpenTofu/Terragrunt**: PASS. Every Argo CD Application is registered from a
  Terragrunt catalog module and includes explicit dependency declarations.
- **GitOps Kubernetes Delivery**: PASS. Terragrunt owns Argo CD Application
  registration; Argo CD owns runtime app reconciliation.
- **Secret Safety**: PASS. The design permits AWS SSM parameter names and
  ExternalSecret references only; plaintext provider keys, Tailscale credentials,
  application passwords, and certificates remain external.
- **Modularity**: PASS. The app contract standardizes metadata, destinations,
  sources, sync policy, info fields, dependency blocks, storage notes, and
  route policy.
- **Validation**: PASS. Quickstart lists formatting, planning, rendering,
  server-side dry-run/diff where applicable, and live health checks.
- **Operations Documentation**: PASS. Data model and quickstart capture
  dependency order, tailnet ingress, Funnel future-use rules, storage, backup,
  restore, and rollback expectations.

## Complexity Tracking

No constitution violations are planned.
