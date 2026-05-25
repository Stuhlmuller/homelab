# Homelab Onboarding

Tags: #runbooks #onboarding #talos #kubernetes

Source: `ONBOARDING.md`

## Current Cluster

| Node | Address | Role | Status |
| --- | --- | --- | --- |
| `acer` | `10.1.0.199` | control-plane | Ready |
| `zimaboard-0` | `10.1.0.200` | worker | Ready |
| `zimaboard-1` | `10.1.0.201` | worker | Ready |
| `zimaboard-2` | `10.1.0.202` | worker | Ready |

Canonical endpoints:

- Talos control-plane endpoint: `10.1.0.199`
- Kubernetes API endpoint: `https://10.1.0.199:6443`
- Talos config reference: `.talos/talosconfig`
- Control-plane config reference: `.talos/controlplane.yaml`
- Worker config reference: `.talos/worker.yaml`
- Worker install disk: `/dev/mmcblk0`

The old `10.1.0.216` address is stale. Fix repo-owned desired state if it
appears in Talos config, kubeconfig, service-account issuer discovery, or OIDC
troubleshooting.

## Source-Of-Truth Rule

Permanent changes must be represented in this repo first. Use Terragrunt and
OpenTofu for infrastructure, Argo CD/Helm/Kustomize/manifests for runtime
Kubernetes state, and repo-authored Talos config for node state. Environment
variables are not normal desired-state inputs; they are for CI/CD credentials
and secret injection only.

## Control-Plane Flow

1. Boot Acer from Talos USB media.
2. Inspect disks, links, and addresses with `talosctl -n TEMP_IP ... --insecure`.
3. Confirm the internal install disk is not USB.
4. Apply `.talos/controlplane.yaml` in maintenance mode.
5. Bootstrap etcd once through authenticated Talos access.
6. Refresh kubeconfig from `10.1.0.199`.
7. Verify `kubectl get node acer -o wide`.
8. Verify `systemdisk`, `META`, `STATE`, and `EPHEMERAL` are on the intended
   internal disk.

## Worker Flow

1. Keep `.talos/worker.yaml` as the base worker config.
2. Use patch files for node-specific hostname and address changes.
3. Validate rendered configs with `talosctl validate --mode metal --strict`.
4. Inspect maintenance-mode disk and NIC layout before apply.
5. Apply config with `--insecure` only while the node is in maintenance mode.
6. Switch to authenticated access after insecure calls return
   `tls: certificate required`.
7. Verify `systemdisk`, addresses, volume statuses, Kubernetes readiness, and a
   physical boot without USB before calling the node complete.

## Storage Gate

The QNAP NAS at `10.1.0.2` exports `/homelab` for `nfs-default`. Workload data
that must survive pod rescheduling or node replacement should use that
StorageClass. See [[storage-nfs]] and [[../architecture/storage-and-state]].

## Related Notes

- [[../architecture/cluster-topology]]
- [[argocd-bootstrap]]
- [[argocd-app-onboarding]]
- [[storage-nfs]]
- [[talos-control-plane-maintenance]]
