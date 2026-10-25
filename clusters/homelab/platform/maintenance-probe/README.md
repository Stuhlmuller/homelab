# Platform maintenance path probe

This source is staged for T023. The Argo CD Application and Kustomization are
disabled and empty. Before a Talos or Kubernetes stage, review current worker
capacity, the mirrored Python image and `nfs-default` health. In a separate
protected source change, list `fixture.yaml` in this Kustomization, enable
automated sync in `IaC/homelab/us-west-2/apps/platform-maintenance-probe/stack.hcl`,
and apply only that Application through the exact-main Terragrunt workflow.
Verify its Pod is Running on `zimaboard-1` and its 32 MiB NFS claim is Bound.
This ordinary worker placement does not use the later network-policy canary.

The protected `platform-maintenance` stage refuses to upgrade without the
fixture. Before each Talos node upgrade, after it recovers, and before each
stage receipt, it checks in-Pod Kubernetes/Grafana DNS and a 4 KiB fsynced
write/read/delete on the dedicated NFS claim. It selects the Grafana Service
and its sole Ready Pod by exact labels, names and ports, then reads Grafana's
database-backed `/api/health` through a bounded, authenticated Kubernetes
port-forward to that Pod. It also checks the Octelium CI Kubernetes path,
authenticated Talos TCP path, Policy Bot's
app-level GET 404 with a request ID, and n8n's app-level missing-webhook 404
through the canonical Funnel hosts. Each command has a deadline; only
structured results go into the private per-node/stage receipts. Public CI
prints fixed labels. The Pod does not mount a ServiceAccount token. The
Grafana check uses the workflow's existing Octelium Kubernetes credential and
adds no ingress or mesh authorization grant.
The Pod may restart during the `zimaboard-1` hop; the stage waits at most five
minutes for it to become Ready and stops if any functional path still fails.

The claim has `Prune=false` and `nfs-default` retains PVs. After the version
ladder, remove the Pod through a reviewed GitOps change; retain the claim until
its UID, PV and empty probe path are reviewed for separate cleanup. No app data
is mounted or written by the probe.
