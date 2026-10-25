# Platform maintenance path probe

This source is staged for T023. The Argo CD Application and Kustomization are
disabled and empty. Before a Talos or Kubernetes stage, measure available CPU
and memory on all four nodes, including the tight Acer and `zimaboard-2`
budgets. The fixture requests 10m CPU and 32 MiB memory per node (40m CPU and
128 MiB across four nodes), with 100m CPU and 64 MiB limits per node. Review
the mirrored Python image and `nfs-default` health. In a separate
protected source change, list `fixture.yaml` in this Kustomization, enable
automated sync in `IaC/homelab/us-west-2/apps/platform-maintenance-probe/stack.hcl`,
and apply only that Application through the exact-main Terragrunt workflow.
Verify its DaemonSet has one Ready Pod on each of `zimaboard-0`, `zimaboard-1`,
`zimaboard-2`, and `acer`, and its 32 MiB RWX NFS claim is Bound. These ordinary
node placements do not use the later network-policy canary. The current nodes
have no taints; a future taint or capacity shortfall requires a reviewed
fixture change before activation. Keep the Application disabled until this
measurement and the separate publication and scoped-apply gates pass.

The protected `platform-maintenance` stage refuses to upgrade without the
fixture. Before each Talos node upgrade and after it recovers, it selects the
DaemonSet Pod on that exact node and checks in-Pod Kubernetes/Grafana DNS and
a 4 KiB fsynced write/read/delete on the dedicated NFS claim. The stage
receipt repeats that node-local I/O check on all four nodes. It selects the
Grafana Service and its sole Ready Pod by exact labels, names and ports, then
reads Grafana's database-backed `/api/health` through a bounded Kubernetes
port-forward to that Pod. It also checks the Octelium CI Kubernetes path,
authenticated Talos TCP path, Policy Bot's app-level GET 404 with a request ID,
and n8n's app-level missing-webhook 404
through the canonical Funnel hosts. Grafana, Octelium, and webhook checks
originate from the protected runner; the per-node evidence covers DNS and NFS
I/O from the named node. Each command has a deadline; only structured results
go into the private per-node/stage receipts. Public CI prints fixed labels.
The staged NetworkPolicy selects only fixture Pods, denies ingress, and permits
TCP/UDP DNS to CoreDNS; rerun the path proof after any policy-enforcer change.
The Pods do not mount ServiceAccount tokens. The Grafana check uses the
workflow's existing Octelium Kubernetes credential and
adds no ingress or mesh authorization grant.
The DaemonSet recreates a Pod after a node drain or reboot; the stage waits at
most five minutes for all four Pods to become Ready and stops if any functional
path still fails. Receipts from an older source SHA or the old single-Pod
proof format cannot verify or skip a node on a newer exact-main run.

The claim has `Prune=false` and `nfs-default` retains PVs. After the version
ladder, remove the DaemonSet through a reviewed GitOps change; retain the
claim until its UID, PV and empty probe path are reviewed for separate cleanup.
No app data is mounted or written by the probe.
