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
  - id: openwiki-source-b17e212516ed4cf97993dd01
    resource: repo://IaC/modules/entra-owner-mail/README.md
  - id: openwiki-source-45cdc02b9fdef209e9d530d7
    resource: repo://scripts/octelium-entra-oidc.sh
generated: { by: "codex", at: "2026-10-09T05:26:38.825Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T19:29:29.016Z
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
