# Multus CNI

`platform-multus` installs the Multus thick DaemonSet in `kube-system` so the
homelab can run Octelium data-plane workloads. Talos requires the Multus netns
mount at `/var/run/netns`, and the init container uses `install_multus -t thick`
so reboot races do not leave the CNI binary missing.

This app intentionally owns only Multus. Octelium node labels are managed by the
`IaC/live/kubernetes-node-labels` Terragrunt unit, and the Octelium Cluster is
initialized through `scripts/octelium-cluster-bootstrap.sh`.

The Multus v4.3.0 daemon limits itself to four concurrent CNI requests. It keeps
a 128Mi memory request and 512Mi limit, with no CPU limit, so Octelium service
pod attachment churn cannot exhaust the daemon or throttle pod networking on
`zimaboard-0`. The DaemonSet uses `system-node-critical`, matching
[Talos's bundled Flannel](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/k8s/internal/k8stemplates/testdata/flannel-daemonset.yaml#L82),
so ordinary workloads cannot permanently starve node CNI after a worker
recovers. This addresses the version-independent scheduler failure described in
[Multus issue #1531](https://github.com/k8snetworkplumbingwg/multus-cni/issues/1531).

## Validation

After Argo CD syncs this app:

```sh
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system get pods -l app=multus
kubectl -n kube-system get daemonset kube-multus-ds -o jsonpath='{.spec.template.spec.priorityClassName}{"\n"}'
kubectl -n kube-system top pod -l app=multus --containers
```

Do not roll back to v4.2.4 for the August 2026 worker outage. The
[v4.3.0 release](https://github.com/k8snetworkplumbingwg/multus-cni/releases/tag/v4.3.0)
adds `connectionLimit` as an opt-in Unix-listener cap, and its
[implementation](https://github.com/k8snetworkplumbingwg/multus-cni/pull/1510)
does not enter Kubernetes v1.34.1's
[PLEG pod-listing path](https://github.com/kubernetes/kubernetes/blob/v1.34.1/pkg/kubelet/pleg/generic.go#L232-L258).
Keep v4.3.0 and `connectionLimit: 4` unless a controlled reproduction proves a
Multus regression. A rollback also restarts the thick daemon; upstream
[issue #1527](https://github.com/k8snetworkplumbingwg/multus-cni/issues/1527)
records that termination removes its generated CNI config. The priority change
cannot revive an unreachable kubelet, so the NotReady workers still require
operator reboot or physical recovery before the DaemonSet can roll out there.

Removing the `platform-multus` Argo CD Application removes the service; it is
safe only after all workloads that require Multus have been removed.
