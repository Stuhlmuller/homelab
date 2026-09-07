# Kubernetes Patch Maintenance, September 2026

Tags: #operations #kubernetes #talos #monitoring

Status: upgrade completed on 2026-09-07. All four nodes run Kubernetes
`1.34.11` on unchanged Talos `1.11.3`; core health, DNS, and PVC metrics passed.
Direct Grafana alert-state verification remains pending.

The [dated maintenance runbook](../../kubernetes-1.34.11-maintenance-2026-09-07.md)
and [control-plane target patch](../../../.talos/patches/kubernetes-1.34.11.yaml)
record the exact `1.34.1` to `1.34.11` change. The control-plane patch declares
all five images; the [worker patch](../../../.talos/patches/worker-kubernetes-1.34.11.yaml)
changes only kubelet, matching the CLI's worker config update. Patches are for
bootstrap and offline renders; only the gated Talos upgrade command owns live sequencing.
The dated runbook records completed prerequisites and the execution outcome.

## Volume Metrics Recovery

Pre-upgrade inspection on 2026-09-07 found all four nodes running Kubernetes
`v1.34.1` on Talos `v1.11.3`. Each kubelet omitted
`kubelet_volume_stats_*` from `/metrics`, despite mounted-volume statistics in
`/stats/summary`. This matches the upstream
[collector registration regression](https://github.com/kubernetes/kubernetes/issues/133847).
The [fix](https://github.com/kubernetes/kubernetes/pull/133890) is present from
`v1.34.2`; choose a maintained patch rather than that first fixed release.

The selected release is `1.34.11`, listed by the
[Kubernetes release page](https://kubernetes.io/releases/#release-history)
and published as a non-prerelease
[GitHub release](https://github.com/kubernetes/kubernetes/releases/tag/v1.34.11).
The [Talos 1.11 support matrix](https://docs.siderolabs.com/talos/v1.11/getting-started/support-matrix)
includes Kubernetes 1.34. The local Talos 1.11.3 planner also accepted that
combination for each node. Compatibility is not evidence that the old Talos
minor has current community support; Talos lifecycle maintenance remains
separate. No Kubernetes minor or Talos version change is included here.

The ordered upgrade completed at 05:35:37 UTC without node reboots. Direct
kubelet checks confirmed statistics for all 28 expected mounted node/PVC pairs
across 30 Pod bindings. Prometheus subsequently covered the same 28 pairs with fresh samples
and all 34 scrape targets up. The PVC alert query returned `31.8029%`, below
the `85%` threshold. Grafana's admin API returned HTTP 401, so its current rule
state and notification delivery remain unverified; query data alone does not
prove the rule is Normal. See the dated runbook for recovery and acceptance
scope, including transient controller restarts.

## Talos 1.11.3 Dry-Run Side Effects

Do not classify `talosctl upgrade-k8s --dry-run` as read-only on this version.
Inspection of the
[pinned implementation](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/cluster/kubernetes/talos_managed.go)
found two independent problems:

- Image pre-pulling checks `PrePullImages`, but not `DryRun`, and makes image
  pull requests. `--pre-pull-images=false` avoids this step only.
- The kube-proxy dry-run callback returns success instead of the skip sentinel.
  The [configuration patch helper](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/cluster/kubernetes/patch.go)
  consequently submits the serialized, nominally unchanged machine config.

The September 7 pre-upgrade plan encountered both paths before these source-level
findings were available. It completed successfully. Checks immediately afterward
confirmed all four Kubernetes versions remained `v1.34.1`, the intended live CoreDNS Corefile
remained intact, and the existing backup schedules had no new failures. Image
downloads consume node disk space even when component upgrades are skipped.
Do not repeat this command as a health check or claim its output proves no
mutating API calls occurred.

For future inspection use authenticated resource reads, pinned source review,
and local render comparisons. Any replacement planner must prove that it skips
both image-pull and machine-configuration writes, including kube-proxy.

## CoreDNS Ownership Conflict

The plan proposed replacing the GitOps-owned `kube-system/coredns` ConfigMap
with Talos's generated default. It would remove the internal Octelium API
rewrite, replace explicit `1.1.1.1` / `1.0.0.1` upstreams with
`/etc/resolv.conf`, and remove ownership metadata. These are operationally
significant settings: the prior node-local resolver failed external lookups.

The source is
[`clusters/homelab/platform/dns/coredns-configmap.yaml`](../../../clusters/homelab/platform/dns/coredns-configmap.yaml).
Before maintenance, Argo CD owned this ConfigMap while Talos still generated
its bootstrap version. The
[[operations/coredns-gitops-ownership|gated CoreDNS ownership handoff]] completed
on September 7: Argo adopted all six resources, the controlled image-pin rollout
and DNS checks passed, then the validated Talos disable patch applied without
a reboot. The post-handoff gate confirmed the two Talos DNS manifest IDs were
absent while the Kubernetes resources and intended DNS behavior remained.
Initial bootstrap still retains Talos DNS until adoption is ready; merging the
declaration alone does not complete that handoff.

## Before Any Upgrade

Use the [canonical maintenance workflow](../../talos-control-plane-maintenance.md#talos-and-kubernetes-upgrade-checklist)
for future upgrades, rechecking the completed DNS handoff. Commit the selected
component versions and bootstrap configuration before executing the ordered upgrade.
Require healthy nodes, Talos services, etcd, storage and workloads, a current
verified off-node etcd snapshot, current application backups, and a maintenance
window for the single control-plane cluster. Require any active workload backup
or migration to finish before restarting kubelets or control-plane components.

The September 7 verified off-node etcd snapshots are retained recovery points,
not a restore drill, PVC backup, or control-plane redundancy. Take a fresh
snapshot immediately before each future maintenance window. A failed upgrade
requires a reviewed recovery decision; an automatic component downgrade or etcd
restore is not the rollback for this note.

After upgrading, require every node and control-plane component to report the
selected version, all required services to recover, the canonical issuer and
DNS policy to remain intact, and volume-capacity/available-byte samples to
return in both kubelet metrics and Prometheus. Check coverage against currently
mounted supported volumes rather than assuming every Bound PVC has a sample.

Related: [[architecture/cluster-topology]], [[architecture/storage-and-state]].
