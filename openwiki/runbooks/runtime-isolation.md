---
type: runbook
title: "Runtime Isolation"
description: "Pod Security, service accounts, Istio authorization, workload security contexts, and unenforced NetworkPolicy limits on flannel."
tags: ["runbook", "security", "kubernetes"]
---

# Runtime Isolation

Canonical runbook: [`docs/runtime-isolation.md`](../../docs/runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. NetworkPolicy objects remain intent-only
where the current flannel data plane cannot enforce them.

See [Validation Gates](../operations/validation-gates.md) and [Workload Inventory](../workloads/inventory.md).
