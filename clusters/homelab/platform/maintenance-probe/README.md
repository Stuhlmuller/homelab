# Platform maintenance path probe

This source declares a four-node DaemonSet and one 32 MiB RWX `nfs-default`
claim for T023. Each Pod requests 10m CPU and 32 MiB memory (40m CPU and
128 MiB across the cluster), with a 100m CPU and 64 MiB memory limit per Pod.
Source merge alone does not register or deploy the Application. Before the
reviewed exact-main Terragrunt apply of only this Application, require:

- The dormant Application registration from the preceding source change and a
  terminal T004 full-catalog mirror receipt with an authenticated pull of the
  pinned Python image.
- Fresh memory, CPU and restart headroom on all four nodes, especially Acer and
  `zimaboard-2`; Ready nodes without pressure; and a healthy `nfs-default`
  provisioner. A request-only calculation or old peak sample cannot admit
  placement. The nodes had no taints at the 2026-10-25 read-only inspection;
  recheck before apply and review any required toleration in source.
- A Kustomize render of exactly this DaemonSet and claim, server-side dry run,
  and a scoped protected plan showing only the intended Application update.

After the declared apply, verify one Ready DaemonSet Pod on each of
`zimaboard-0`, `zimaboard-1`, `zimaboard-2`, and `acer`, and a Bound claim to an
NFS PV. A protected functional DNS/NFS I/O probe on every node plus runner
access, webhook and Grafana checks must pass before T024. These node placements
do not use the later network-policy canary. Keep Talos/Kubernetes stages
disabled until direct recovery and a fresh off-node etcd backup are verified.

The protected `platform-maintenance` stage refuses to upgrade without the
fixture. Before each Talos node upgrade and after it recovers, it selects the
DaemonSet Pod on that exact node and checks in-Pod Kubernetes/Grafana DNS and
a 4 KiB fsynced write/read/delete on the dedicated NFS claim. The stage
receipt repeats that node-local I/O check on all four nodes. It selects the
Grafana Service and its sole Ready Pod by exact labels, names and ports, then
reads Grafana's database-backed `/api/health` through a bounded Kubernetes
port-forward to that Pod. It also checks the Octelium CI Kubernetes path,
authenticated Talos TCP path, Policy Bot's app-level GET 404 with a request ID,
and n8n's app-level missing-webhook 404 through the canonical Funnel hosts.
Grafana, Octelium, and webhook checks
originate from the protected runner; the per-node evidence covers DNS and NFS
I/O from the named node. Each command has a deadline; only structured results
go into the private per-node/stage receipts. Public CI prints fixed labels.
The Pods do not mount ServiceAccount tokens. The Grafana check uses the
workflow's existing Octelium Kubernetes credential and adds no ingress or mesh
authorization grant.
The DaemonSet recreates a Pod after a node drain or reboot; the stage waits at
most five minutes for all four Pods to become Ready and stops if any functional
path still fails. Receipts from an older source SHA or the old single-Pod
proof format cannot verify or skip a node on a newer exact-main run.

The claim has `Prune=false` and `nfs-default` retains PVs. After the version
ladder, remove the DaemonSet through a reviewed GitOps change that enables
pruning; the claim annotation keeps the PVC. Retain that claim until its UID,
PV and empty probe path are reviewed for separate cleanup.
No app data is mounted or written by the probe.
