# Octelium

Tags: #runbook #octelium #access

Canonical runbook: [`docs/octelium.md`](../../octelium.md)

Octelium is the primary human-app, callback, and CI access backbone. Keep
Cluster bootstrap, Enterprise adoption, public Cloudflare routing, Entra OIDC,
and the end-to-end gate on their repository-owned scripts and manifests. The
catalog also owns the core human session ceiling; apply its `ClusterConfig`
include separately before the normal catalog apply.

See [[../architecture/secrets-and-identity]], [[tailnet-ingress]], and
[[../workloads/inventory]].
