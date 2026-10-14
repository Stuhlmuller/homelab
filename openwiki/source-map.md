---
type: overview
title: "Source Map"
description: "Maps wiki topics to canonical repository guides, operational runbooks, workload READMEs, and source ownership."
tags: ["knowledge-base", "source-map"]
sources:
  - id: openwiki-source-efd15335758af38c6e6af9ab
    resource: repo://clusters/homelab/apps/deluge/daemon-status.py
  - id: openwiki-source-9f4d1b63d947cd42e3af68b2
    resource: repo://clusters/homelab/apps/deluge/README.md
  - id: openwiki-source-58caddf8069d72479935ea1e
    resource: repo://clusters/homelab/apps/fleet/FREE-ENTRA.md
  - id: openwiki-source-fbaccd01ca51226fa9e5324d
    resource: repo://clusters/homelab/apps/traefik/README.md
  - id: openwiki-source-e038674a313521b0f6eadc03
    resource: repo://docs/cordium-ci.md
  - id: openwiki-source-1247eded2dab9841fec2a345
    resource: repo://docs/nix-cache.md
  - id: openwiki-source-3eda5d2b85501c78fc0ba02d
    resource: repo://flake.nix
  - id: openwiki-source-0ea5376c0684f2dd735ec9d4
    resource: repo://IaC/modules/entra-google-workspace-federation/README.md
  - id: openwiki-source-b17e212516ed4cf97993dd01
    resource: repo://IaC/modules/entra-owner-mail/README.md
  - id: openwiki-source-6b5e63b8e249f20dfe916d9f
    resource: repo://IaC/modules/tailscale-access/README.md
  - id: openwiki-source-0f1996b7e0fc35047d4f05dd
    resource: repo://scripts/ci/install-kubeconfig.sh
  - id: openwiki-source-c7852b586f8f1a45684f7ab4
    resource: repo://scripts/ci/offline-checks.sh
  - id: openwiki-source-020791e1237c864b31f43a39
    resource: repo://scripts/ci/offline-static-checks.sh
  - id: openwiki-source-2f1cb193abf8d2f74ad8d8ad
    resource: repo://scripts/ci/tailscale-identity-check.py
  - id: openwiki-source-4bbfe00c406fec8a213babcb
    resource: repo://scripts/nix-builder.py
  - id: openwiki-source-74dcbb88cca2d854985d0d67
    resource: repo://scripts/nix-cache.py
  - id: openwiki-source-45cdc02b9fdef209e9d530d7
    resource: repo://scripts/octelium-entra-oidc.sh
  - id: openwiki-source-ff63d9d82b2370adf56a5f28
    resource: repo://scripts/octelium-nofx-reconcile.py
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
  - id: openwiki-source-81658af78f4007503983579d
    resource: repo://scripts/tailscale-ingress-sign.py
generated: { by: "codex", at: "2026-10-11T06:23:22.000Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-14T03:16:04.839Z
---

# Source Map

This wiki summarizes repository source files; it does not replace them. Use
this map to jump from wiki pages back to canonical files before changing
desired state.

## Top-Level Guidance

| Source | Wiki page | Purpose |
| --- | --- | --- |
| `README.md` | [Homelab Knowledge Base](quickstart.md) | Project overview, repository map, and first-read navigation |
| `AGENTS.md` | [Continuous Improvement](operations/continuous-improvement.md) | Agent workflow, safety boundaries, ownership, ongoing stewardship |
| `ONBOARDING.md` | [Homelab Onboarding](runbooks/homelab-onboarding.md) | Talos and cluster onboarding |

## Runbooks

| Source | Wiki page |
| --- | --- |
| `docs/argocd-bootstrap.md` | [Argo CD Bootstrap](runbooks/argocd-bootstrap.md) |
| `docs/argocd-app-onboarding.md` | [Argo CD App Onboarding](runbooks/argocd-app-onboarding.md) |
| `docs/image-automation.md` | [Image Automation](runbooks/image-automation.md) |
| `docs/ci-cd.md` | [CI/CD](runbooks/ci-cd.md) |
| `docs/nix-cache.md` | [Signed offline CI checks](architecture/gitops-flow.md#signed-offline-ci-checks) |
| `flake.nix`, `scripts/ci/nix-checks.sh`, `offline-checks.sh`, `offline-static-checks.sh` | [Offline validation ownership](operations/validation-gates.md#default-gate) |
| `scripts/nix-cache.py`, `scripts/nix-builder.py`, `clusters/homelab/apps/nix-builder/README.md` | [Builder and local signing boundaries](architecture/secrets-and-identity.md#signed-nix-cache-trust) |
| `clusters/homelab/apps/traefik/README.md` and `routes.yaml` | [Staged mesh ingress and callbacks](runbooks/tailnet-ingress.md) |
| `IaC/modules/tailscale-access/README.md` and `scripts/config/tailscale-policy.json` | [Tailscale provider and signed CI key ownership](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `scripts/tailscale-ingress-sign.py` | [Fixed proxy Tailnet Lock signing](runbooks/tailnet-ingress.md#tailnet-lock) |
| `scripts/tailscale-ci-configure.py` | [Scoped CI signing, interrupted-signature recovery and authority retirement](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `clusters/homelab/apps/traefik/CUTOVER.md` | [Ordered DNS, Mac, callback and CI acceptance](runbooks/tailnet-ingress.md#cutover-utilities) |
| `scripts/ci/tailscale-identity-check.py` and `install-kubeconfig.sh` | [CI joined identity and tokenless API transport](runbooks/ci-cd.md#tailscale-ci-cutover) |
| `scripts/octelium-nofx-reconcile.py` and `scripts/octelium-api-response.py` | [Verified direct native mesh transport](runbooks/octelium.md) |
| `scripts/talos-harbor-mirrors.py` | [Private node registry path](operations/harbor-oci.md#private-node-registry-foundation) |
| `docs/networking-tailnet-ingress.md` | [Tailnet And App Ingress](runbooks/tailnet-ingress.md) |
| `docs/octelium.md` | [Octelium](runbooks/octelium.md) |
| `scripts/octelium-entra-oidc.sh` | [Immutable Entra identity bindings](architecture/secrets-and-identity.md) |
| `IaC/modules/entra-owner-mail/README.md` | [Owner-mail migration boundary](architecture/secrets-and-identity.md) |
| `IaC/modules/entra-google-workspace-federation/README.md` | [Operator federation boundary](architecture/secrets-and-identity.md#google-workspace-federation-boundary) |
| `clusters/homelab/apps/fleet/FREE-ENTRA.md` | [Mac SSO recovery and acceptance](operations/validation-gates.md#entra-owner-mail-and-octelium-identity-checks) |
| `docs/rollback-argocd-apps.md` | [Argo CD App Rollback](runbooks/rollback.md) |
| `docs/runtime-isolation.md` | [Runtime Isolation](runbooks/runtime-isolation.md) |
| `docs/secrets-aws-ssm.md` | [AWS SSM Secret References](runbooks/secrets-aws-ssm.md) |
| `docs/storage-nfs.md` | [NFS Storage](runbooks/storage-nfs.md) |
| `scripts/langfuse-valkey-recovery.py` | [Valkey offline capture](architecture/storage-and-state.md) |
| `clusters/homelab/apps/litellm/native_keys.py` | [Native service-key migration](architecture/ai-observability.md) |
| `docs/talos-control-plane-maintenance.md` | [Talos Control-Plane Maintenance](runbooks/talos-control-plane-maintenance.md) |
| `docs/validation-runbook.md` | [Validation](runbooks/validation.md) |

## App And Platform Notes

| Source | Wiki page |
| --- | --- |
| `clusters/homelab/apps/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/apps/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/apps/deluge/daemon-status.py` and Deluge `README.md` | [Daemon health incident](operations/deluge-cpu-audit-2026-09-05.md#october-8-daemon-health-failure), [health verification](operations/validation-gates.md#deluge-daemon-health) |
| `clusters/homelab/platform/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `IaC/live/argocd-apps/README.md` | [Argo CD App Onboarding](runbooks/argocd-app-onboarding.md) |

## CI transport ownership

Phase 2b workflows join through fixed pre-signed Tailscale keys, verify the
joined identity, then use tokenless operator API access or independent native
Cordium authorization. The old CI connector/disconnector helpers are removed;
shared native callers retain their catalog and credential lifecycle through
`octelium-nofx-reconcile.py`. Live acceptance and later retirement remain
separate from this source preparation; see [CI/CD](runbooks/ci-cd.md).
