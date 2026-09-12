# Talos Restore Runtime Validation

Related: [[restore-egress-boundary]], [[validation-gates]],
[[../runbooks/runtime-isolation]].

## Read-only baseline: 2026-09-06 UTC

Authenticated `talosctl` reached all four nodes. Each reported Talos `1.11.3`
(`a0243ef7`), `linux/amd64`; Kubernetes reported `1.34.1`, containerd `2.1.4`
and kernel `6.12.52-talos`. All nodes were Ready without pressure conditions or
taints; worker CRI services were Running/OK. No RuntimeClass objects existed.

The running `octelium-postgres-0` on `zimaboard-1` used `RuntimeDefault` and
UID/GID `65534`. Its actual PID 1 status reported `NoNewPrivs: 1`, `Seccomp: 2`,
`Seccomp_filters: 1`, and zero effective, permitted and inheritable capabilities.
The `octelium-storage` namespace enforced baseline Pod Security with restricted
audit/warnings; it had no ResourceQuota, LimitRange or ambient/injection labels.

These are runtime baseline observations. **Stacked-filter installation and the
synthetic restore under the final Job profile remain unverified.** No synthetic
Job, image publication, backup read or cluster mutation occurred in this audit.

## Capacity snapshot

Request headroom is allocatable minus scheduler-reported requests. Nodefs
availability comes from kubelet statistics. Refresh both before choosing Job
placement; these values reserve no resources.

| Worker      | CPU request headroom | Memory request headroom | Available nodefs |
| ---         | ---                  | ---                     | ---              |
| zimaboard-0 | 555m                 | 2.93 GiB                | 6.39 GiB         |
| zimaboard-1 | 1910m                | 3.13 GiB                | 5.13 GiB         |
| zimaboard-2 | 1250m                | 0.26 GiB                | 17.03 GiB        |

The proposed restore budget uses a `2Gi` disk-backed `emptyDir` and `3Gi`
ephemeral-storage limit. Allow for image/log growth and concurrent usage;
`zimaboard-2` had little unreserved memory. The existing NFS backup claim was
Bound; the synthetic compatibility Job must not mount it or production data.

## Safe status projections

Use the existing authenticated operator context. Replace `NODE_INTERNAL_IP`
with an address from the node status output. Keep credentials outside git.

```sh
(
set -euo pipefail
kubectl get nodes -o json | jq '[.items[] | {
  node: .metadata.name,
  internalIPs: [.status.addresses[] | select(.type == "InternalIP") | .address],
  arch: .status.nodeInfo.architecture, os: .status.nodeInfo.osImage,
  kernel: .status.nodeInfo.kernelVersion,
  kubelet: .status.nodeInfo.kubeletVersion,
  runtime: .status.nodeInfo.containerRuntimeVersion,
  allocatable: (.status.allocatable | {cpu, memory, "ephemeral-storage"}),
  conditions: [.status.conditions[] | select(.type == "Ready" or
    .type == "MemoryPressure" or .type == "DiskPressure" or .type == "PIDPressure") |
    {type, status}], taints: .spec.taints}]'
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP version --short |
  awk '/^(Talos v|[[:space:]]*(NODE:|Tag:|OS\/Arch:|Enabled:))/ {print}'
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP service cri |
  awk '/^(NODE|ID|STATE|HEALTH)[[:space:]]/ {print}'
)
```

Read only the existing PostgreSQL process's security status; do not load a
filter or execute a test program inside that production container:

```sh
kubectl -n octelium-storage exec octelium-postgres-0 -c postgres -- \
  awk '/^(Uid:|Gid:|CapInh:|CapPrm:|CapEff:|NoNewPrivs:|Seccomp:|Seccomp_filters:)/ {print}' \
  /proc/1/status
```

Refresh reservation and local scratch capacity without printing Pod inventories
or node events:

```sh
(
set -euo pipefail
kubectl describe nodes | awk '
  /^Name:/ {print}
  /^Allocated resources:/ {keep=1}
  /^Events:/ {keep=0}
  keep {print}'
for restore_node in zimaboard-0 zimaboard-1 zimaboard-2; do
  kubectl get --raw "/api/v1/nodes/$restore_node/proxy/stats/summary" |
    jq --arg node "$restore_node" '{node: $node,
      availableBytes: .node.fs.availableBytes, capacityBytes: .node.fs.capacityBytes}'
done
)
```

## Required runtime proof

Before any production backup is read, a reviewed repository-owned synthetic Job
must use the published, tested immutable amd64 image and explicitly invoke the
launcher before its script. An image ENTRYPOINT alone is insufficient when
Kubernetes `command` overrides it. No unpublished digest is selected here.

Match the intended `RuntimeDefault`, UID/GID `65534`, dropped capabilities,
no-privilege-escalation, read-only root, bounded scratch/resources, stdio and
deadline settings. Exclude backup/production PVCs, credentials, service-account
tokens, host/runtime/proxy sockets, unfiltered sidecars and shared host namespaces.

Require successful filter installation, the launcher's deterministic forbidden
syscall `EPERM` checks and working Unix communication, followed by the synthetic
PostgreSQL init/dump/drop/restore and subprocess-inheritance fixtures. Injected
startup failures must stop before the command sentinel. Verify the admitted Pod
and process profile on its observed node; retain exact source/image/runtime
identity and aggregate results. Complete that proof before the later reviewed
GitOps activation. Failure keeps the real drill inactive; never remove the
launcher or relax the runtime profile to obtain a passing result.
