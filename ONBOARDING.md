# Homelab Onboarding

This document captures the completed Talos control-plane and worker onboarding
process for the homelab Kubernetes cluster.

## Completed Talos Control Plane

| Node | Static IP | Role | Kubernetes Status | Notes |
| --- | --- | --- | --- | --- |
| `acer` | `10.1.0.199` | control-plane | Ready | Canonical Talos and Kubernetes API endpoint |

`acer` is the active seed control-plane node. Keep `10.1.0.199` as the canonical
cluster endpoint unless intentionally migrating the control plane again.

## Completed Talos Workers

| Node | Static IP | Temporary USB IP | Active NIC | System Disk | Status |
| --- | --- | --- | --- | --- | --- |
| `zimaboard-0` | `10.1.0.200` | `10.1.0.184` | `enp2s0` | `mmcblk0` | Ready |
| `zimaboard-1` | `10.1.0.201` | `10.1.0.139` | `enp2s0` | `mmcblk0` | Ready |
| `zimaboard-2` | `10.1.0.202` | `10.1.0.150` | `enp2s0` | `mmcblk0` | Ready |

Use hyphenated hostnames such as `zimaboard-1`. Do not use underscore names such
as `zimaboard_1`; underscores are not valid Kubernetes node hostnames.

## Cluster Assumptions

- Talos control plane endpoint: `10.1.0.199`
- Kubernetes API endpoint: `https://10.1.0.199:6443`
- Talos config: `.talos/talosconfig`
- Control-plane config: `.talos/controlplane.yaml`
- Base worker config: `.talos/worker.yaml`
- Worker install disk: `/dev/mmcblk0`
- Persistent storage NAS: QNAP at `10.1.0.2`
- Persistent storage NFS share: `homelab`
- USB install media appears as `/dev/sda` and must not remain the system disk.
- Worker NICs are expected to look like:
  - `enp2s0`: linked and active
  - `enp3s0`: down

Use `--insecure` only while a node is booted into Talos maintenance mode from
fresh USB install media. Once a node has accepted machine config, use
authenticated Talos API calls through `.talos/talosconfig`.

The old `10.1.0.216` control-plane address is stale. Do not use it as the
canonical Kubernetes API endpoint or Talos endpoint for new work.

## Repository Source of Truth

Permanent homelab changes are made through code in this repository. External
infrastructure must be modeled as OpenTofu modules orchestrated by
Terragrunt, with a documented path that can rebuild the project from scratch
with one `terragrunt apply` command after required credentials and deliberately
external secret material are available.

Kubernetes runtime changes must be delivered through Argo CD, Helm, Kustomize,
or repository-owned manifests. The Talos commands in this guide apply
repo-authored machine configuration; they are not a substitute for capturing
lasting configuration in git.

Desired-state inputs must be committed as non-secret code or repository data.
Do not use environment variables as normal operator inputs for Terragrunt,
OpenTofu, Helm, Kustomize, Talos config, or application configuration.
Environment variables are reserved for CI/CD credential plumbing and secret
injection. If a secret is required, inject it in the CI/CD pipeline and keep
only safe references, encrypted values, templates, or contracts in git.

## Persistent Storage

Shared persistent storage for Kubernetes workloads is provided by a QNAP NAS on
the homelab LAN.

| System | Address | Protocol | Share | Intended use |
| --- | --- | --- | --- | --- |
| QNAP NAS | `10.1.0.2` | NFS | `homelab` | Backing storage for Kubernetes persistent volumes |

The NAS share is the cluster-level durable storage target. It is separate from
Talos node persistence: each node should still boot from and keep Talos state on
its internal system disk, while workload data that must survive pod rescheduling
or node replacement should use the QNAP-backed storage class once that class is
defined in Kubernetes.

NAS-side expectations:

- NFS service is enabled on the QNAP.
- A shared folder or export named `homelab` exists.
- The export allows read/write access from the Talos node addresses
  `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and `10.1.0.202`, or from the
  narrower trusted node subnet if the node list changes.
- Access controls, UID/GID ownership, and squash behavior are documented beside
  any workload that depends on a specific filesystem identity.

Kubernetes storage integration should be declared in git rather than configured
by hand in the cluster. When a CSI driver, external provisioner, or static
`PersistentVolume` is added, use these source values:

```yaml
server: 10.1.0.2
share: homelab
```

Record the exact QNAP NFS export path in the storage manifest when it is wired
into Kubernetes. Many examples use paths like `10.1.0.2:/homelab`, but QNAP can
show a device-specific export path in its UI. Prefer the path reported by the
NAS over an assumed path.

Operator workstation checks:

```sh
showmount -e 10.1.0.2
```

Expected evidence:

```text
Export list for 10.1.0.2:
<qnap-export-path-for-homelab>  <allowed-clients>
```

Before making the QNAP-backed storage class the default, verify that a test PVC
can be created, written, deleted, and recreated with the expected reclaim
policy. Document backup and restore expectations before placing important
stateful workloads on this storage.

## Required Control-Plane Config

The control-plane config must preserve the same cluster secrets as the worker
configs and should set the Acer node as the canonical endpoint:

```yaml
machine:
  type: controlplane
  network:
    hostname: acer
    interfaces:
      - interface: ACTIVE_NIC
        addresses:
          - 10.1.0.199/24
        routes:
          - network: 0.0.0.0/0
            gateway: 10.1.0.1
    nameservers:
      - 1.1.1.3
      - 1.0.0.3
  install:
    disk: CONTROL_PLANE_INTERNAL_DISK
    image: ghcr.io/siderolabs/installer:v1.11.3
    wipe: true
cluster:
  controlPlane:
    endpoint: https://10.1.0.199:6443
  apiServer:
    certSANs:
      - 10.1.0.199
```

Before applying, replace `ACTIVE_NIC` and `CONTROL_PLANE_INTERNAL_DISK` with the
values proven by maintenance-mode inspection. Do not assume the control-plane
disk name matches the Zimaboard workers.

If the control-plane IP changes, update all of these together:

- `cluster.controlPlane.endpoint`
- `cluster.apiServer.certSANs`
- `.talos/talosconfig` endpoints and nodes
- local kubeconfig server URL
- worker configs that point at the control-plane endpoint

## Control-Plane Onboarding

Boot Acer from Talos USB media and find its temporary DHCP address. Inspect the
node before applying config:

```sh
talosctl -n TEMP_IP get disks --insecure
talosctl -n TEMP_IP get links --insecure
talosctl -n TEMP_IP get addresses --insecure
```

Confirm the selected install disk is the intended internal disk and not the USB
installer. Then apply the control-plane config:

```sh
talosctl apply-config --insecure \
  -n TEMP_IP \
  --file .talos/controlplane.yaml
```

Once the node answers securely at `10.1.0.199`, bootstrap etcd only for the first
control-plane node:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.199 \
  bootstrap
```

Do not re-run `bootstrap` after the cluster is initialized.

Fetch or refresh kubeconfig from Acer:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.199 \
  kubeconfig ~/.kube/config --force

kubectl config set-cluster homelab --server=https://10.1.0.199:6443
```

Verify the control-plane node:

```sh
kubectl get node acer -o wide
```

Required result:

```text
acer   Ready   control-plane   ...   10.1.0.199
```

Verify Talos persistence with authenticated access:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.199 \
  get systemdisk

talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.199 \
  get volumestatuses
```

The control-plane is not considered USB-independent until `systemdisk`, `META`,
`STATE`, and `EPHEMERAL` all point at the intended internal disk.

## Required Base Worker Config

The base worker config should set the shared worker defaults:

```yaml
machine:
  network:
    hostname: zimaboard-0
    interfaces:
      - interface: enp2s0
        addresses:
          - 10.1.0.200/24
        routes:
          - network: 0.0.0.0/0
            gateway: 10.1.0.1
    nameservers:
      - 1.1.1.3
      - 1.0.0.3
  install:
    disk: /dev/mmcblk0
    image: ghcr.io/siderolabs/installer:v1.11.3
    wipe: true
cluster:
  controlPlane:
    endpoint: https://10.1.0.199:6443
```

`zimaboard-0` can use the base file directly. Additional nodes should use small
JSON6902 patch files rather than copying the full worker config.

Example per-node patch:

```yaml
- op: replace
  path: /machine/network/hostname
  value: zimaboard-2
- op: replace
  path: /machine/network/interfaces/0/addresses/0
  value: 10.1.0.202/24
```

Render a per-node config:

```sh
talosctl machineconfig patch .talos/worker.yaml \
  --patch @.talos/worker-zimaboard-2.patch.yaml \
  --output /private/tmp/worker-zimaboard-2.yaml
```

## Safety Gates

Before changing live node state, run the repository checks that are available in
this checkout:

```sh
nix flake check
```

This flake currently provides the operator development shell and flake
evaluation check; it does not define a `validate` app. Pair the repository check
with the nearest validation for the files being changed:

- Talos machine config: `talosctl validate --mode metal --strict`.
- Kubernetes or Argo CD desired state: `kubectl kustomize`, `kubectl diff`, or a
  server-side dry run before apply.
- Terragrunt/OpenTofu: `terragrunt hcl fmt --check`, OpenTofu validation, and a
  reviewed `terragrunt plan` from the documented stack root before apply.

## Argo CD Bootstrap

Argo CD is bootstrapped through one Terragrunt stack:

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

Use `docs/argocd-bootstrap.md` for the full runbook, validation sequence,
handoff rules, rollback path, and recovery notes. The initial bootstrap installs
Argo CD in the `argocd` namespace, keeps the service internal, and creates the
`argocd-self-management` Application with repository-defined automated prune
and self-heal.

Quick recovery summary:

- Missing CRDs: fix the Helm release before retrying Application registration.
- Bad repo path or target revision: correct repository desired state and
  reapply the same Terragrunt stack.
- Missing credentials: inject them through CI/CD or an external secret path; do
  not commit tokens or kubeconfigs.
- Partial install: capture read-only state, fix or revert repository code, and
  reapply the reviewed state.
- Break-glass live changes are incomplete until the final state is backfilled
  into this repository.

## Argo CD Application Onboarding

Application delivery is modeled through Terragrunt-registered Argo CD
Applications under `IaC/live/argocd-apps/`. Start with these runbooks before
syncing or rolling back application desired state:

- `docs/argocd-app-onboarding.md`: app inventory, owning paths, dependency
  readiness, and sync/health exception format.
- `docs/storage-nfs.md`: default NFS StorageClass prerequisite, backup gate,
  restore expectations, and current rollout blocker.
- `docs/networking-tailnet-ingress.md`: Istio reverse proxy, Tailscale tailnet
  reachability, no first-rollout Funnel paths, and DNS assumptions.
- `docs/secrets-aws-ssm.md`: AWS SSM Parameter Store references and External
  Secrets rules.
- `docs/validation-runbook.md`: pre-mutation checks, Argo CD readiness checks,
  and failure handling.
- `docs/rollback-argocd-apps.md`: dependency-aware rollback order.

Stateful apps auto-sync by default, but they must not be considered ready until
the NFS provisioner exists and NFS backup coverage is documented in
`docs/storage-nfs.md`.

Then validate the Talos config that will be applied:

```sh
talosctl validate --config .talos/worker.yaml --mode metal --strict
talosctl validate --config /private/tmp/worker-zimaboard-2.yaml --mode metal --strict
```

If this checkout is incomplete or a legacy validation helper is unavailable,
record that fact before proceeding. During early onboarding, a stripped checkout
was missing the project flake and live survey helper, so Talos validation and
read-only node inspection were used as the live safeguards.

## Maintenance-Mode Inspection

Boot the target machine from fresh Talos USB media and find its temporary DHCP
address. Before applying config, confirm the disk and NIC layout:

```sh
talosctl -n TEMP_IP get disks --insecure
talosctl -n TEMP_IP get links --insecure
talosctl -n TEMP_IP get addresses --insecure
```

Required disk evidence:

```text
mmcblk0   31 GB   false   mmc
sda       31 GB   false   usb   SanDisk 3.2Gen1
```

Required NIC evidence:

```text
enp2s0   up     true
enp3s0   down   false
```

Do not apply config if `mmcblk0` is missing or read-only, or if the active
interface is not the interface used in the worker config.

## Apply Worker Config

For the base node:

```sh
talosctl apply-config --insecure \
  -n 10.1.0.184 \
  --file .talos/worker.yaml
```

For patched nodes:

```sh
talosctl apply-config --insecure \
  -n TEMP_IP \
  --file /private/tmp/worker-zimaboard-N.yaml
```

The command may report:

```text
Applied configuration without a reboot
```

That is acceptable. The node should leave the temporary DHCP address and begin
answering on its static IP.

## Transition Checks

After apply, the old temporary address should stop answering:

```sh
talosctl -n TEMP_IP get addresses --insecure
```

The new static address should reject insecure requests with:

```text
tls: certificate required
```

That message means the node accepted config and is no longer in maintenance
mode. Switch to authenticated Talos calls.

## Persistence Verification

Use authenticated Talos access against the static IP:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes STATIC_IP \
  get systemdisk
```

Required result:

```text
SystemDisk   system-disk   mmcblk0
```

Confirm networking:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes STATIC_IP \
  get addresses
```

Required result:

```text
enp2s0/STATIC_IP/24
```

Confirm persistent volumes are on internal storage:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes STATIC_IP \
  get volumestatuses
```

Required result:

```text
META        /dev/mmcblk0p2
STATE       /dev/mmcblk0p3
EPHEMERAL   /dev/mmcblk0p4
```

Do not remove the USB until `systemdisk`, `META`, `STATE`, and `EPHEMERAL` all
point at `mmcblk0`.

## Kubernetes Verification

Wait for the node to register and become ready:

```sh
kubectl get node zimaboard-N -o wide
kubectl get nodes -o wide
```

Required result:

```text
zimaboard-N   Ready   <none>   ...   v1.34.1   STATIC_IP
```

`NotReady` for a short period immediately after first registration is normal
while kubelet and CNI settle.

## Physical Boot Test

After persistence is verified:

1. Remove the USB installer.
2. Reboot the node.
3. Confirm the node returns at its static IP.
4. Re-run the `systemdisk`, `volumestatuses`, and `kubectl get node` checks.

The machine is not considered fully independent of USB until it reboots with:

```text
SystemDisk   system-disk   mmcblk0
```

## Kubeconfig Refresh

If `kubectl` points at the old API address, refresh the kubeconfig from Acer:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.199 \
  kubeconfig ~/.kube/config --force

kubectl config set-cluster homelab --server=https://10.1.0.199:6443
kubectl get nodes
```

The active Kubernetes server should be:

```text
https://10.1.0.199:6443
```

## Failure Modes

`tls: certificate required` with `--insecure` means the node is already
configured. Use authenticated Talos access instead.

`systemdisk = sda` means Talos is still running from USB. Do not pull the USB in
that state. Boot fresh install media, verify maintenance mode, and apply the
worker config to the temporary DHCP address.

`kubectl` timeouts to `10.1.0.216:6443` mean the local kubeconfig is stale. Reset
the `homelab` cluster server to `https://10.1.0.199:6443`.

If a broad physical NIC selector assigns the static IP to both NICs, pin the
worker config to `interface: enp2s0`.

If Kubernetes reports `nodes "zimaboard-N" not found` immediately after Talos
comes up, wait and check kubelet health:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes STATIC_IP \
  get services
```

`kubelet`, `containerd`, and `cri` should be running and healthy.
