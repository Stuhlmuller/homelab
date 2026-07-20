# Cluster Topology

Tags: #architecture #talos #kubernetes

## Current Shape

The homelab is a Talos Linux Kubernetes cluster with one active seed
control-plane node and three Zimaboard workers.

| Node | Address | Role | Notes |
| --- | --- | --- | --- |
| `acer` | `10.1.0.199` | control-plane | Canonical Talos and Kubernetes API endpoint |
| `zimaboard-0` | `10.1.0.200` | worker | Hyphenated Kubernetes node name |
| `zimaboard-1` | `10.1.0.201` | worker | Hyphenated Kubernetes node name |
| `zimaboard-2` | `10.1.0.202` | worker | Hyphenated Kubernetes node name |

## Monitoring Contract

Grafana alerting treats this four-node set as the expected hardware inventory
through `clusters/homelab/apps/grafana/values.yaml`. The node rules watch
`acer`, `zimaboard-0`, `zimaboard-1`, and `zimaboard-2` with kube-state-metrics
and kubelet/cAdvisor metrics for inventory count, Kubernetes readiness,
pressure conditions, and workload CPU/memory use against reported machine
capacity.

Kube-state-metrics availability has a dedicated critical alert. The expected
hardware inventory rule only evaluates while that scrape is healthy, so a
telemetry outage cannot be misreported as four missing machines. The dedicated
alert also makes it explicit that the kube-state-metrics-backed readiness and
pressure rules have no current data.

Update the Grafana alert regex and expected count in the same change that adds,
removes, or renames a node.

## Canonical Endpoints

- Talos endpoint: `10.1.0.199`
- Kubernetes API endpoint: `https://10.1.0.199:6443`
- Talos config reference: `.talos/talosconfig`
- Control-plane config reference: `.talos/controlplane.yaml`
- Worker config reference: `.talos/worker.yaml`

The previous control-plane address `10.1.0.216` is stale. If it appears in
Talos config, kubeconfig, service-account issuer discovery, OIDC setup, or
troubleshooting notes, fix the repository-owned desired state to use
`https://10.1.0.199:6443`.

## Source Files

- `ONBOARDING.md`
- `docs/talos-control-plane-maintenance.md`
- `.talos/patches/controlplane-service-account-issuer.yaml`

## Maintenance Notes

- Use `--insecure` with `talosctl` only for nodes in Talos maintenance mode
  before machine config has been applied.
- After machine config is applied, use authenticated Talos access through
  `.talos/talosconfig`.
- Talos machine config changes should stay patch-oriented when only one node
  differs from the shared baseline.
