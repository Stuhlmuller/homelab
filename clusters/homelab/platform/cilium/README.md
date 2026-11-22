# Cilium migration trial

`values-migration.yaml` renders the initial overlay for chart 1.20.5.
The `platform-cilium` Application syncs the coexistence overlay automatically. The trial values keep kube-proxy,
disable Cilium policy enforcement during coexistence, and let Flannel and
Multus own the active CNI configuration. Talos supplies cgroup v2 and agents
run without the kernel-module loading capability.

```sh
helm template cilium cilium --repo https://helm.cilium.io --version 1.20.5 \
  --namespace kube-system --kube-version 1.34.11 \
  -f clusters/homelab/platform/cilium/values-migration.yaml
```

The trial uses `10.245.0.0/16` as a second Pod CIDR and UDP 8473 for its VXLAN
overlay. Verify that the CIDR is unused by cluster, LAN and tailnet routes and
that the port is available across nodes before registering the chart.
The Homelab values keep operator replicas off the smallest worker,
`zimaboard-2`. The hosted lab measured 170 MiB for its worker agent and
12 MiB for Envoy. Measure host headroom and Cilium working sets under live
load before advancing node cutover.


## Rollout checkpoints

1. Exercise a trial with Flannel, thick Multus, and Istio ambient. Verify
   cross-overlay Pod and Service connectivity, DNS, and the Octelium secondary
   attachment as nodes switch over. Confirm Multus delegates primary network
   setup to the correct plugin, and rehearse restoring its Flannel delegation.
2. Publish and admit the exact chart images through the Harbor image pipeline.
   Deploy the coexistence Application through GitOps, then implement the protected
   node-by-node cutover and rollback. Include eviction feasibility and retain
   a working route to the Talos and Kubernetes APIs throughout the cutover.
   The Application tracks `node-migration.yaml`, which selects only
   `zimaboard-2` by hostname. When the agent starts on the selected worker,
   it writes the primary CNI configuration and retains the Multus and Flannel
   files. Before syncing this stage, verify the coexistence overlay, host-route
   preflight, completed eviction and registry recovery. Recreate the worker
   workloads through the guarded cutover so their sandboxes use Cilium.

3. Inventory effective egress and install explicit workload grants for DNS,
   API access, internal peers and approved external destinations. Verify
   host-network and Multus traffic on their actual interfaces. Account for
   node and host-network services before enabling any Cilium host firewall.
4. Enable Cilium policy after all workload endpoints have migrated. Start
   default-deny qualification on an isolated scope and verify allowed and
   denied traffic, including direct IP and alternate ports, before widening
   enforcement. Use Cilium endpoint coverage, policy status and live traffic
   results to verify the cluster-wide rollout.

See the [Cilium migration guide](https://docs.cilium.io/en/stable/installation/k8s-install-migration/)
and the [Talos Cilium guide](https://docs.siderolabs.com/kubernetes-guides/cni/deploying-cilium).

## Retire Talos-managed Flannel

The [cutover patch](../../../../.talos/patches/cilium-cni.yaml) disables the
Talos-managed CNI configuration. Apply it through the protected Talos
delivery path only after Cilium has taken over primary CNI setup on all nodes
and every non-host-network Pod has been recreated on the Cilium overlay.
Verify node and API access, DNS, storage, mesh traffic and Multus attachments
before retiring the Flannel resources. Confirm that new Pod sandboxes still
use Cilium after each node configuration change.

Use contemporaneous, private all-namespace Pod and CiliumEndpoint JSON
snapshots with `scripts/cilium-cutover-check.py --pods <pods.json> --endpoints
<endpoints.json> --cidr 10.245.0.0/16`. The check rejects stale endpoint
ownership, unready endpoints and legacy primary IP addresses. Repeat it
around the cutover and verify host-network and Multus traffic separately.
Before uncordoning `zimaboard-2`, run the same check against private Pod and
CiliumEndpoint snapshots containing the Cilium probe. Supply
`--worker zimaboard-2 --nodes <nodes.json> --previous-boot-id <boot-id>`
to require a changed boot ID, a Ready node and a current Cilium endpoint
while the worker remains cordoned. Verify the probe's DNS, Service and
Multus attachment paths before restoring scheduling.



The [rollback patch](../../../../.talos/patches/cilium-cni-rollback.yaml)
restores the Flannel selection. Use it as part of a coordinated rollback
that restores Flannel routing and Multus delegation before recreating
affected workloads. Preserve kube-proxy throughout both changes.
