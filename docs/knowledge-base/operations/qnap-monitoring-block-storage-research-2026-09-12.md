# QNAP Block Storage Candidate For Monitoring

Status: researched candidate; no NAS, Talos, CSI, or workload change applied.
The existing QNAP could provide ext4 filesystems over iSCSI without another
disk or machine, **if its healthy pool has allocatable capacity**. This is a
compatibility finding, not a proven storage or restore path.

## Evidence And Compatibility

`docs/storage-nfs.md` records a TS-451+, QTS `5.2.9.3451` at setup, and
`Storage Pool 1`: RAID 5 across four 2 TB disks with a 10% snapshot reserve.
Current firmware, disk health, pool allocation, and free capacity have not been
verified through authenticated NAS management. September 12 read-only probes
found TCP `10.1.0.2:3260` refused and HTTP `:8080` returning an unidentified
landing page. These results do not establish the QTS management endpoint or
explain whether iSCSI is disabled or bound elsewhere.

The official [QNAP CSI v1.6.2 documentation][qnap] lists Kubernetes
`1.24–1.35`, Talos `1.8+`, and QTS `5.1+`, covering the cluster's Kubernetes
`1.34.11` and Talos `1.11.3` on paper. Pin upstream commit
`8e88467ecf612fb84bbcd4caf300b624fca41de2` (release `v1.6.2`), including
the operator, backend sidecar, and driver. Its [Helm chart][chart] is version
`2.0.0`. No exact-stack deployment has been tested here.

[Prometheus excludes NFS from supported local storage][prometheus]. An ext4
filesystem on an iSCSI LUN removes that filesystem mismatch; it does not make
the NAS, RAID, network, or power supply independent or prove their durability.
[QTS describes block-based LUNs as allocations from storage-pool space][qts].
Free bytes reported inside `/homelab` are not proof of unallocated pool space.

## Smallest Proposed Repository Path

1. Declare the NAS prerequisite first: verified management endpoint, existing
   pool identity/health/capacity, and intended iSCSI portal. The repo currently
   has no QNAP service-management owner. Add a bounded, idempotent repository
   operation for enabling the intended service/portal before executing it;
   preserve existing shares, volumes, LUNs, and snapshot reserve.
2. Add `siderolabs/iscsi-tools` to a committed Talos `1.11.3` image schematic
   while preserving existing boot requirements. Authenticated September 12
   `get extensions` returned no extension rows on all four nodes. Talos
   [installs extensions through boot/installer assets][extensions]; a machine
   patch alone does not install them. The declared installer update requires
   fresh verified backups, serial node maintenance/reboots, and verification
   of `ext-iscsid` and node readiness. Do not use package-manager commands from
   generic Linux examples. [Talos 1.11.3 identifies this extension][talos-storage]
   as its iSCSI support path.
3. Register a dedicated `qnap-csi` Application through
   `IaC/terragrunt.stack.hcl` and the existing Application module. Review and pin
   upstream Helm resources, namespace privileges, CRDs and node-plugin mounts.
   Let a `TridentBackendConfig` and controller-managed credential Secret own
   provisioning. Use `qnap-nas`, `csi.trident.qnap.io`, single-path iSCSI,
   `fsType: ext4`, `ReadWriteOnce`, and a new non-default `Retain` StorageClass.
   Keep `nfs-default` and all existing claims unchanged. Multipath and snapshot
   controllers are not needed for the initial single-path candidate. See [driver prerequisites][qnap].
4. Prove the target using disposable, repository-owned test claims before
   adapting [draft PR #973][migration]. Preserve distinct new claim-template
   names, `50Gi`/`10Gi` capacities, `15d`/`120h` retention, original claims,
   all-writer fencing, and isolated application restore proof before startup.
   Budget checkpoint and restore copies separately. Acer's unresolved
   corruption finding remains open; its system disk is not the fallback target.

Kubernetes 1.34 also supports a [static pre-existing iSCSI volume][k8s], so CSI
is not intrinsically mandatory. Static PVs still require a declared NAS target,
LUN, IQN/portal, CHAP references and lifecycle owner. The vendor CSI route is
the proposed fit for repeatable provisioning through the existing GitOps model.

## Missing Provisioning Contract

- Verified QTS management URL/port and controller-accessible credentials for
  pool discovery and target/LUN provisioning, supplied through the existing
  external-secret workflow. The pinned guide does not establish a minimum
  delegated account role; validate the actual required permissions. Do not
  place login values in git or ordinary environment inputs.
- One unambiguous eligible pool, allocation policy and actual free capacity
  beyond existing commitments, snapshot reserve, `60Gi` production capacity,
  and measured verification copies. Backend virtual-pool labels are not proof
  of a particular physical pool; verify the selected NAS pool before allocation.
- Confirmed portal/interface, intended node initiators, management and iSCSI
  reachability, and CHAP secret references if enabled. `:8080` and a NAS NFS
  export alone satisfy none of these requirements.
- Repo-owned bootstrap/service operation and CSI resources, a reviewed serial
  Talos installer rollout, and measured workload placement/replay capacity.
  NAS storage does not fix the cluster's memory or sole-control-plane limits.

## Acceptance And Limits

Pin the current driver: [v1.6.1 added filesystem-detection safeguards][fix]
following a [reported destructive reformat on reattachment][issue]. Maintainers
could not reproduce that incident reliably; the reporter subsequently observed
no issue after upgrading. Treat the release as a candidate to validate, not
proof that attachment is lossless.

Require known content and filesystem identity to survive write/fsync, clean
detach, reattach on every eligible node, and controlled serial restart tests.
Then prove Prometheus historical queries/WAL replay and Alertmanager
silence/notification-log restoration with external effects disabled. Measure
latency and replay/compaction headroom. `ReadWriteOnce` is not a substitute for
node-side fencing of an unreachable former writer. Retain independent backup,
restore, rollback RPO/RTO, and interruption gates from PR #973. A snapshot or
archive on the same QNAP remains in the same failure domain.

Validation for this note: pinned source inspection, existing manifests and
draft migration review, plus read-only endpoint/extension evidence. No login,
credential discovery, NAS changes, device creation, mounts, or test claims.

[qnap]: https://github.com/qnap-dev/QNAP-CSI-PlugIn/blob/8e88467ecf612fb84bbcd4caf300b624fca41de2/readme.md
[chart]: https://github.com/qnap-dev/QNAP-CSI-PlugIn/blob/8e88467ecf612fb84bbcd4caf300b624fca41de2/Helm/trident/Chart.yaml
[prometheus]: https://prometheus.io/docs/prometheus/latest/storage/
[qts]: https://docs.qnap.com/operating-system/qts/5.2.x/en-us/getting-started-with-iscsi-CD1CE5D2.html
[extensions]: https://github.com/siderolabs/talos/blob/v1.11.3/website/content/v1.11/talos-guides/configuration/system-extensions.md
[talos-storage]: https://github.com/siderolabs/talos/blob/v1.11.3/website/content/v1.11/kubernetes-guides/configuration/storage.md
[k8s]: https://v1-34.docs.kubernetes.io/docs/concepts/storage/volumes/#iscsi
[migration]: https://github.com/Stuhlmuller/homelab/pull/973
[fix]: https://github.com/qnap-dev/QNAP-CSI-PlugIn/releases/tag/v1.6.1
[issue]: https://github.com/qnap-dev/QNAP-CSI-PlugIn/issues/50
