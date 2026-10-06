---
type: overview
title: "Source Map"
description: "Maps wiki topics to canonical repository guides, operational runbooks, workload READMEs, and source ownership."
tags: ["knowledge-base", "source-map"]
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
| `docs/rollback-argocd-apps.md` | [Argo CD App Rollback](runbooks/rollback.md) |
| `docs/runtime-isolation.md` | [Runtime Isolation](runbooks/runtime-isolation.md) |
| `docs/secrets-aws-ssm.md` | [AWS SSM Secret References](runbooks/secrets-aws-ssm.md) |
| `docs/storage-nfs.md` | [NFS Storage](runbooks/storage-nfs.md) |
| `docs/talos-control-plane-maintenance.md` | [Talos Control-Plane Maintenance](runbooks/talos-control-plane-maintenance.md) |
| `docs/validation-runbook.md` | [Validation](runbooks/validation.md) |

## App And Platform Notes

| Source | Wiki page |
| --- | --- |
| `clusters/homelab/apps/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/apps/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `clusters/homelab/platform/*/README.md` | [Application Notes](workloads/application-notes.md) |
| `IaC/live/argocd-apps/README.md` | [Argo CD App Onboarding](runbooks/argocd-app-onboarding.md) |
