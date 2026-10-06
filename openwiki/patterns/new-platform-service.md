---
type: pattern
title: "New Platform Service Pattern"
description: "Shared platform-service ownership, downstream dependencies, readiness checks, and required architecture and validation updates."
tags: ["pattern", "platform", "argocd"]
---

# New Platform Service Pattern

Use this checklist before adding a shared platform service such as DNS, storage,
ingress, certificate management, secret management, observability plumbing, or a
cluster-wide controller.

## Read First

- [GitOps Flow](../architecture/gitops-flow.md)
- [Storage And State](../architecture/storage-and-state.md) when state or storage is involved
- [Secrets And Identity](../architecture/secrets-and-identity.md) when credentials or identity are
  involved
- [Validation Gates](../operations/validation-gates.md)
- Relevant runbook under `docs/`

## Implementation Shape

1. Put desired state under `clusters/homelab/platform/<service>` unless the
   service is intentionally application-scoped.
2. Register the parent Application under
   `IaC/live/argocd-apps/platform-<service>`.
3. Document downstream apps that depend on the service.
4. Add readiness checks before dependent workloads rely on the service.
5. Keep rollback notes close to the runbook.
6. Update the source docs that teach the service before or with the code change.

## Knowledge-Base Update

Update the affected architecture note, [Workload Inventory](../workloads/inventory.md) if dependencies
change, and [Validation Gates](../operations/validation-gates.md) if validation changes.
