# Cilium migration trial

`values-migration.yaml` renders the initial overlay for chart 1.20.5.
This directory has no Argo CD registration. The values keep kube-proxy,
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

## Rollout checkpoints

1. Exercise a trial with Flannel, thick Multus, and Istio ambient. Verify
   cross-overlay Pod and Service connectivity, DNS, and the Octelium secondary
   attachment as nodes switch over. Confirm Multus delegates primary network
   setup to the correct plugin, and rehearse restoring its Flannel delegation.
2. Publish and admit the exact chart images through the Harbor image pipeline.
   Register the initial overlay through GitOps, then implement the protected
   node-by-node cutover and rollback. Include eviction feasibility and retain
   a working route to the Talos and Kubernetes APIs throughout the cutover.
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
