<!-- markdownlint-disable MD013 -->

# Existing-Node Control-Plane Feasibility

Status: read-only assessment; no role, disk, endpoint, or workload change.
`acer`, `zimaboard-0`, and `zimaboard-1` could form a three-member control
plane without new hardware. This could tolerate one control-plane failure
after a failover API endpoint is established. It would add no workload
capacity, and current resource and disk evidence does not justify promotion yet.

## Capacity Observed On September 12

At `2026-09-12T03:15:22Z`, the four nodes ran Talos `1.11.3` and Kubernetes
`1.34.11`. Read-only node, active-Pod, and metrics API metadata gave:

| Node | Physical memory GiB | Allocatable GiB | Effective memory requests GiB | Request headroom GiB |
| --- | --- | --- | --- | --- |
| `acer` | 15.501 | 14.903 | 10.382 | 4.521 |
| `zimaboard-0` | 7.584 | 7.111 | 4.184 | 2.927 |
| `zimaboard-1` | 7.584 | 7.111 | 5.830 | 1.281 |
| `zimaboard-2` | 1.750 | 1.278 | 1.090 | 0.188 |

Effective requests include init-container scheduling demand, restartable init
sidecars, and Pod overhead; terminal Pods are excluded. Headroom is a request
budget, not unused physical RAM. The two larger workers have four cores each;
the smallest worker falls below the [Talos control-plane minimum][requirements]
of 2 GiB. The larger workers meet minimum CPU/RAM/disk requirements, but their
roughly 32 GB eMMC is below the recommended 100 GiB disk size.

The existing API server, controller manager, and scheduler together request
`832Mi` and `260m`. Reusing those requests on each new member, plus the
[Talos role default][reserved] increase from `384Mi` to `512Mi` system-reserved
memory, costs **at least `960Mi` and `260m` per promoted worker** in this
accounting model: **1.875 GiB and 520m total**. These are current/default
reservations, not sizing guarantees or measured etcd consumption.

| Candidate | Projected memory request headroom GiB | Projected CPU request headroom |
| --- | --- | --- |
| `zimaboard-0` | 1.990 | 295m |
| `zimaboard-1` | 0.343 | 1550m |

The existing three control-plane Pods actually used **1.341 GiB** in the same
metrics snapshot, excluding Talos-hosted etcd. New members can differ, and this
is not a peak bound. In particular, `zimaboard-1` would have only about **352Mi**
unrequested memory after the minimum accounting change. Measure etcd and
control-plane peaks plus workload startup/rollout demand before choosing real
reservations; retain mixed control-plane/workload scheduling deliberately.
Moving all ordinary workloads off these three nodes would leave only the
1.278 GiB-allocatable worker.

## Quorum Does Not Supply Workload N+1

Total effective memory requests were **21.485 GiB** against **30.402 GiB**
allocatable. The same conservative largest-node-loss arithmetic used by
memory-overcommit alerts, `requests - (total allocatable - largest node)`, gives
a **5.986 GiB** deficit; using ordinary container requests gives **5.858 GiB**,
consistent with [[operations/monitoring-resource-requests]]. Adding the two
members raises the effective-request result to **7.861 GiB**.

That arithmetic is not an exact rescheduling simulation: it retains the failed
node's static-Pod and DaemonSet requests. Even subtracting just `acer`'s `832Mi`
static control-plane demand leaves about **7.049 GiB** before other adjustments.
Affinity, local volumes, Pod slots, and actual memory demand further constrain
recovery. Failure of full workload N+1 does **not** prevent an etcd quorum;
three healthy voting members need two. API/etcd availability and full
application failover must be accepted separately.

## Conversion And Disk Constraints

Talos `1.11.3` [code persists a changed configuration and reboots][apply] when
the change cannot be applied immediately; changing the machine role requires
that reboot. This supports a conversion mechanism without mandatory reinstall,
but an explicit tested v1.11 worker-promotion runbook was not found. Rehearse
the exact transition before production maintenance.

A role-only patch is insufficient: [control-plane validation][validation]
requires signing material forbidden on workers. A repository-owned generation
path must produce complete control-plane configuration from the existing
cluster's secret material, preserving node identity, network, install, and
storage settings. Secret availability was not inspected in this assessment.
Join the existing etcd cluster; do not bootstrap another cluster. Talos
[joins as a learner and promotes after catch-up][join]. The intermediate
two-voter cluster requires both members; complete and verify each join
serially. Reverting the role after joining is not a complete rollback:
[plain reboot does not remove etcd membership][sequences].

There is no missing etcd partition to create: the [v1.11.3 volume controller][volumes]
defines `/var/lib/etcd` as a directory under EPHEMERAL. Default conversion
needs no partition shrink or wipe. The observed worker ephemeral capacity
was 26.906 GiB each; capacity is not current free space or a durability test.
[etcd 3.6 guidance][etcd-hardware] emphasizes low, stable write latency and
warns that co-located applications can cause contention. eMMC is not an
automatic incompatibility, but these devices remain unqualified for etcd:
`zimaboard-1` previously suffered severe memory pressure and queued eMMC reads
until kubelet stopped. See [[architecture/cluster-topology]] and the unresolved
`acer` corruption finding in [[operations/continuous-improvement]]. Quorum
does not prove storage integrity or replace verified independent backups.

The current Kubernetes endpoint is `acer`'s physical IP. Adding members alone
leaves that client endpoint dependent on `acer`. A declared [VIP][vip] or
load-balancer path must accompany any availability claim; VIP requires a
reserved unused address on the shared L2 network and healthy etcd. Keep direct
per-member Talos recovery access.

## Next Capacity Decision

Before implementation, choose how to reduce or relocate demand on the two
candidates enough to fund measured control-plane/etcd peaks and recovery
headroom. Recheck all-node and node-loss placement with actual workload
constraints. If that cannot be achieved on existing hardware, additional
reliable memory/compute is needed for the desired workload availability target.
NAS storage alone supplies neither RAM nor API quorum.

Also require current eMMC free space and health evidence, stable disk latency
under representative load, the existing-cluster configuration generation
contract, an endpoint/discovery design, fresh verified etcd and application
backups, isolated restore proof, and a serial maintenance/member-aware rollback
runbook. No disk benchmark, private machine-config read, promotion, drain,
reboot, or application change was performed for this assessment.

[requirements]: https://docs.siderolabs.com/talos/v1.11/getting-started/system-requirements
[reserved]: https://github.com/siderolabs/talos/blob/v1.11.3/pkg/machinery/constants/constants.go#L442-L455
[apply]: https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/internal/server/v1alpha1/v1alpha1_server.go#L169-L316
[validation]: https://github.com/siderolabs/talos/blob/v1.11.3/pkg/machinery/config/types/v1alpha1/v1alpha1_validation.go
[join]: https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/system/services/etcd.go#L267-L305
[sequences]: https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/runtime/v1alpha1/v1alpha1_sequencer.go#L235-L335
[volumes]: https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/block/volume_config.go#L449-L583
[etcd-hardware]: https://etcd.io/docs/v3.6/op-guide/hardware/
[vip]: https://docs.siderolabs.com/talos/v1.11/networking/vip
