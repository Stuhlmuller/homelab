# Multus CNI

`platform-multus` installs the Multus thick DaemonSet in `kube-system` so the
homelab can run Octelium data-plane workloads. Talos requires the Multus netns
mount at `/var/run/netns`, and the init container uses `install_multus -t thick`
so reboot races do not leave the CNI binary missing.

This app intentionally owns only Multus. Octelium node labels are managed by the
`IaC/live/kubernetes-node-labels` Terragrunt unit, and the Octelium Cluster is
initialized through `scripts/octelium-cluster-bootstrap.sh`.

## Validation

After Argo CD syncs this app:

```sh
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system get pods -l app=multus
```

Rollback is to remove the `platform-multus` Argo CD Application only after all
workloads that require Multus have been removed.
