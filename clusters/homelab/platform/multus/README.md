# Multus CNI

`platform-multus` installs the Multus thick DaemonSet in `kube-system` so the
homelab can run Octelium data-plane workloads. Talos requires the Multus netns
mount at `/var/run/netns`, and the init container uses `install_multus -t thick`
so reboot races do not leave the CNI binary missing.

This app intentionally owns only Multus. Octelium node labels are managed by the
`IaC/live/kubernetes-node-labels` Terragrunt unit, and the Octelium Cluster is
initialized through `scripts/octelium-cluster-bootstrap.sh`.

The Multus 4.3 daemon limits itself to four concurrent CNI requests. It keeps a
128Mi memory request and 512Mi limit, with no CPU limit, so Octelium service pod
attachment churn cannot exhaust the daemon or throttle pod networking on
`zimaboard-0`.

## Validation

After Argo CD syncs this app:

```sh
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system get pods -l app=multus
kubectl -n kube-system top pod -l app=multus --containers
```

To roll back the version, restore both image references to
`v4.2.4-thick@sha256:3c20900b5381fac7f9cbbdfac8370ea10a2f6ed7fbecc678384a9db57047abb1`
and remove `connectionLimit` from `multus-daemon-config` in the same change.

Removing the `platform-multus` Argo CD Application removes the service; it is
safe only after all workloads that require Multus have been removed.
