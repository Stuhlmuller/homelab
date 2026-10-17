---
type: runbook
title: "Runbooks Index"
description: "Task routes through Talos onboarding, Argo CD, storage, secrets, Octelium access, validation, rollback, and recovery runbooks."
tags: ["runbooks", "onboarding", "operations"]
---

# Runbooks Index

This section pulls the top-level onboarding docs and operational runbooks into
OpenWiki. The source files remain canonical; these notes are compact maps of
what to read, what facts matter, and what must be updated with future changes.

## Onboarding Path

1. [Homelab Onboarding](homelab-onboarding.md) for the Talos cluster shape, worker bring-up, and
   cluster source-of-truth rules.
2. [Argo CD Bootstrap](argocd-bootstrap.md) to install Argo CD and hand steady-state ownership to
   GitOps.
3. [Argo CD App Onboarding](argocd-app-onboarding.md) to register workload Applications through
   Terragrunt and Argo CD.
4. [NFS Storage](storage-nfs.md) before any stateful workload is treated as ready.
5. [AWS SSM Secret References](secrets-aws-ssm.md) before any ExternalSecret or runtime credential contract
   is added.
6. [Octelium](octelium.md) before changing private access, an app route, or the Octelium
   service catalog.
7. [Tailnet And App Ingress](tailnet-ingress.md) before changing the temporary Talos/LAN fallback or a
   public callback route.
8. [Validation](validation.md) before any live mutation or rollout.

## Operations

- [Continuous Improvement](../operations/continuous-improvement.md) records the standing security and
  reliability stewardship loop.
- [CI/CD](ci-cd.md) records the GitHub Actions plan/apply model.
- [Runtime Isolation](runtime-isolation.md) records current Pod Security and network isolation
  assumptions.
- [Octelium](octelium.md) records the Octelium client bridge and private service catalog.
- [Argo CD App Rollback](rollback.md) records dependency-aware app rollback order.
- [Talos Control-Plane Maintenance](talos-control-plane-maintenance.md) records issuer drift repair and upgrade
  gates.
- [Image Automation](image-automation.md) records Renovate policy and digest requirements.
- [QNAP Plex Recovery](../operations/plex-recovery-2026-10-05.md) records QNAP Plex crash evidence
  and the bounded server recovery path.

- [Recovery exercise](../operations/recovery-exercise-2026-10-01.md) records
  restore evidence and remaining live gates.
- [Octelium capability research](../operations/octelium-capability-research-2026-09-05.md)
  records the security and agent execution expansion.

## Supporting Maps

- [Cluster Topology](../architecture/cluster-topology.md)
- [GitOps Flow](../architecture/gitops-flow.md)
- [Storage And State](../architecture/storage-and-state.md)
- [Secrets And Identity](../architecture/secrets-and-identity.md)
- [Workload Inventory](../workloads/inventory.md)
- [Application Notes](../workloads/application-notes.md)
- [Source Map](../source-map.md)
