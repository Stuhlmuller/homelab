<!-- markdownlint-disable MD013 -->

# Cluster Topology

Tags: #architecture #talos #kubernetes

## Current Shape

The homelab is a Talos Linux Kubernetes cluster with one active seed
control-plane node and three Zimaboard workers.

| Node | Address | Role | Notes |
| --- | --- | --- | --- |
| `acer` | `10.1.0.199` | control-plane | Canonical Talos and Kubernetes API endpoint |
| `zimaboard-0` | `10.1.0.200` | worker | Hyphenated Kubernetes node name |
| `zimaboard-1` | `10.1.0.201` | worker | Octelium control-plane and Cordium Workspace node |
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

## Workload Scheduling

Terragrunt manages `octelium.com/node-mode-cordium=` on `zimaboard-1` because
Cordium-generated Workspace Pods require that selector. Of the worker nodes,
`zimaboard-1` has enough memory for the default Workspace limit and lower
reserved load than `zimaboard-0`; `zimaboard-2` is too small.
Talos on `zimaboard-1` does not expose AppArmor enforcement, so repo-owned
support Pods use RuntimeDefault seccomp and explicitly request an unconfined
AppArmor profile to clear stale server-side-applied defaults.

### Octelium dataplane capacity

Terragrunt currently assigns the Octelium dataplane label to `zimaboard-0` and
`zimaboard-2`. The August 2026 outage showed that this is not resilient enough:
a failover can start 51 dataplane-selected Deployments plus the node-local
gateway agent at once. Seven-day measurements put the full fleet near 3.1 GiB
memory at p95, while its declared memory requests total only about 315 MiB.

Do not use the existing control-plane node or `zimaboard-1` as the replacement
dataplane target. The control-plane node has etcd and rollout pod-slot risk;
`zimaboard-1` already hosts the Octelium control plane and stateful workloads.
After the 16 stale `*.homelab` service proxies are removed, the retained
dataplane still uses about 2.7 GiB memory at p95 and creates 35 Deployment Pods
plus the gateway agent.

The durable recovery requirement is a dedicated third dataplane-capable worker
with enough real memory and pod capacity for that retained fleet plus startup
and rolling-update headroom. No hardware choice or sizing is declared yet.
Before assigning its label, remove the stale services, set representative proxy
requests, and validate the chosen node against measured use. The declarative
label path is `IaC/.catalog/units/live/kubernetes-node-labels/terragrunt.hcl`.

### Temporary August 2026 recovery

While both labeled dataplane nodes are NotReady,
`clusters/homelab/apps/octelium-enterprise/emergency-dataplane.yaml` runs 26
uniquely named temporary Deployments on `acer`: the Octelium ingress, shared
Octovigil authorization service, Portal, login, Auth API, admin API, OctoBot,
CI Kubernetes API, and 18 additional public WEB Service proxies. Including the
existing OctoBot fallback, 19 public WEB proxies run during recovery. The
additional public set is AFFiNE, Argo CD, Compass, Cordium, the Enterprise
console, Deluge, Dispatcharr, Grafana, Kiali, LiteLLM, Multica, n8n, NOFX,
OpenClaw, Policy Bot, Prowlarr, Radarr, and Sonarr. Existing Service selector
labels restore these paths without a new Service, ingress, port, node label, or
controller-owned Deployment patch. Cordium and the Enterprise console retain
their required digest-pinned managed sidecars; Cordium gets a bounded writable
`/tmp` for its bbolt cache. Temporary containers are capped at 256 MiB except
the measured Auth API and admin API managed containers, which request 384 MiB
and are capped at 512 MiB.

The 24 temporary service-proxy Pods intentionally use only the primary
Kubernetes network. The ingress Envoy resolves their existing Kubernetes
Services, and Vigil listens on all Pod interfaces. Attaching Octelium's
secondary Multus network would require the privileged gateway agent that is
deliberately absent from the control-plane node. Each fallback embeds its
generated `octelium.com/svc-uid`; refresh that value if Octelium recreates the
corresponding Service.

Do not remove the file merely because one dataplane node reports Ready;
`zimaboard-2` alone does not have enough capacity. First validate the replacement
node against measured use plus startup and rolling-update headroom. Keep the
full native fleet on it for 24 hours with a stable Ready condition and restart
counts. The package-managed `octelium-ingress-dataplane`,
`octelium-octovigil`, all six original control and CI Service Deployments, and
all 18 additional public WEB Service Deployments must each have a Ready replica. Before
pruning, probe the native Pod IPs directly—not the selector-balanced
Services—for every recovered path, then run `scripts/octelium-e2e-check.sh`.
Remove the file from the Enterprise Kustomization only after both checks pass;
the `octelium-enterprise` Application then prunes the 26 uniquely named
temporary Deployments. Reverify native-only endpoints and the public paths
afterward.

Keep Multus `connectionLimit` at `4`; lowering it to `1` or `2` is not a safe
capacity fix. The [upstream option](https://github.com/k8snetworkplumbingwg/multus-cni/pull/1510)
limits simultaneous Unix-socket connections to the thick daemon so its
delegated CNI child processes stay within the daemon container's memory budget.
It does not limit scheduler placement or the final number of proxy Pods. During
the August 2026 failure, the limit was already
`4`: 51 dataplane-selected Pods were created in eight seconds, an unrelated
client Pod joined the same window, container starts continued for about 27
seconds, and `zimaboard-2` became NotReady 44 seconds later. Multus peaked near
`24Mi` memory and `162m` CPU, far below its `512Mi` memory limit, with no
observed container OOM event before telemetry stopped. The node exposes only
about `1.28Gi` allocatable memory, so even the retained fleet's `2.7Gi` p95
cannot reach steady state there. A lower connection limit would only queue CNI
work and can add head-of-line delay to every node-local CNI operation; it would
not remove the overcommit. Revisit the value only with a controlled startup
test on a correctly sized dedicated dataplane worker.

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
