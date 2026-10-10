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
  - id: openwiki-source-b17e212516ed4cf97993dd01
    resource: repo://IaC/modules/entra-owner-mail/README.md
  - id: openwiki-source-6b5e63b8e249f20dfe916d9f
    resource: repo://IaC/modules/tailscale-access/README.md
  - id: openwiki-source-45cdc02b9fdef209e9d530d7
    resource: repo://scripts/octelium-entra-oidc.sh
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
  - id: openwiki-source-81658af78f4007503983579d
    resource: repo://scripts/tailscale-ingress-sign.py
generated: { by: "codex", at: "2026-10-10T21:24:31.626Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T21:39:58.912Z
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
| `clusters/homelab/apps/traefik/README.md` and `routes.yaml` | [Staged mesh ingress and callbacks](runbooks/tailnet-ingress.md) |
| `IaC/modules/tailscale-access/README.md` and `scripts/config/tailscale-policy.json` | [Tailscale provider and signed CI key ownership](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `scripts/tailscale-ingress-sign.py` | [Fixed proxy Tailnet Lock signing](runbooks/tailnet-ingress.md#tailnet-lock) |
| `scripts/tailscale-ci-configure.py` | [Scoped CI key publication and authority retirement](architecture/secrets-and-identity.md#tailscale-provider-foundation) |
| `scripts/talos-harbor-mirrors.py` | [Private node registry path](operations/harbor-oci.md#private-node-registry-foundation) |
| `docs/networking-tailnet-ingress.md` | [Tailnet And App Ingress](runbooks/tailnet-ingress.md) |
| `docs/octelium.md` | [Octelium](runbooks/octelium.md) |
| `scripts/octelium-entra-oidc.sh` | [Immutable Entra identity bindings](architecture/secrets-and-identity.md) |
| `IaC/modules/entra-owner-mail/README.md` | [Owner-mail migration boundary](architecture/secrets-and-identity.md) |
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
