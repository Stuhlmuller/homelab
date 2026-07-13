# Runtime Isolation

Tags: #runbook #security #kubernetes

Canonical runbook: [`docs/runtime-isolation.md`](../../runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. NetworkPolicy objects remain intent-only
where the current flannel data plane cannot enforce them.

See [[../operations/validation-gates]] and [[../workloads/inventory]].
