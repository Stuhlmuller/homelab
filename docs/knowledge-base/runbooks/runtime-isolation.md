# Runtime Isolation

Tags: #runbook #security #kubernetes

Canonical runbook: [`docs/runtime-isolation.md`](../../runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. NetworkPolicy objects remain intent-only
where the current flannel data plane cannot enforce them.

See [[../operations/validation-gates]] and [[../workloads/inventory]].

## HOME-3 enforcement candidate

[Staged enforcement and recovery containment](../../network-enforcement.md)
adds kube-router 2.11.1 firewall-only manifests without replacing Talos Flannel,
kube-proxy, Multus or Istio. All new runtime resources are unregistered.
Compatibility grants preserve other namespaces while OpenClaw, Multica runtime
and Harbor signing egress receive explicit destination/port rules. Public HTTPS
for agents, shared DNS/gateway and local-node traffic remain explicit exceptions.

Source-union fixtures and the two-round, exact-identity transport harness are
implementation evidence only. Actual engine compatibility, denied/allowed traffic,
operator ingress, rollback and a supported offline archive sandbox are unverified.
An ordinary deny-all Pod is not the recovery specialist's no-network boundary.
OpenClaw's unsupported sandbox remains off. See [[../operations/validation-gates]].
