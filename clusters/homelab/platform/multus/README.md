# Multus CNI

`platform-multus` installs the Multus thick DaemonSet in `kube-system` so the
homelab can run Octelium data-plane workloads. Talos requires the Multus netns
mount at `/var/run/netns`, and the init container uses `install_multus -t thick`
so reboot races do not leave the CNI binary missing.

This app intentionally owns only Multus. Octelium node labels are managed by the
`IaC/live/kubernetes-node-labels` Terragrunt unit, and the Octelium Cluster is
initialized through `scripts/octelium-cluster-bootstrap.sh`.

The Multus v4.3.1 daemon limits itself to four concurrent CNI requests. It keeps
a 128Mi memory request and 512Mi limit, with no CPU limit, so Octelium service
pod attachment churn cannot exhaust the daemon or throttle pod networking on
`zimaboard-0`. The DaemonSet uses `system-node-critical`, matching
[Talos's bundled Flannel](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/k8s/internal/k8stemplates/testdata/flannel-daemonset.yaml#L82),
so ordinary workloads cannot permanently starve node CNI after a worker
recovers. This addresses the version-independent scheduler failure described in
[Multus issue #1531](https://github.com/k8snetworkplumbingwg/multus-cni/issues/1531).

## v4.3.1 upgrade and rollback

The pinned [v4.3.1 release](https://github.com/k8snetworkplumbingwg/multus-cni/releases/tag/v4.3.1)
fixes delegated conflist cleanup, certificate rotation races, and thick-daemon
termination. Retain the Talos mounts, `connectionLimit: 4`, resource envelope,
and `system-node-critical`; the upgrade does not address worker overcommit.
The upstream Kubernetes client dependency moves to 1.36.2; the homelab API
version is unchanged, so live CNI attachment acceptance remains required.

Before merge, run `nix develop --command bash scripts/ci/static-checks.sh` and
`nix develop --command bash scripts/ci/conftest-policies.sh`. These validate the
repository and rendered manifests; they cannot prove live CNI behavior. After
sync, complete the native attachment and direct Pod-IP checks below before
running `scripts/octelium-e2e-check.sh` for externally routed paths. Emergency
proxies can satisfy that script without using Multus.

If v4.3.1 causes attachment or daemon failures, revert this image update through
a PR to restore the previous v4.3.0 digest
`sha256:2b9671447f3ea4e7e56730843dbf59445b9307246f393b61386b896d56ae51c9`.
Keep `connectionLimit: 4` and the Talos mounts. GitOps restarts the thick daemon,
so verify CNI config presence and the same acceptance checks after rollback.
Do not manually delete daemon Pods or change node CNI files.

## Validation

After Argo CD syncs this app:

```sh
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system get pods -l app=multus
kubectl -n kube-system get daemonset kube-multus-ds -o jsonpath='{.spec.template.spec.priorityClassName}{"\n"}'
kubectl -n kube-system top pod -l app=multus --containers
```

### Native attachment acceptance

Exclude the primary-network emergency Pods and inspect every native Pod that
requests a Multus network:

```sh
kubectl -n octelium get pods -l '!homelab.rst.io/emergency-dataplane' -o json |
  jq '.items[] |
    select(.metadata.annotations["k8s.v1.cni.cncf.io/networks"] != null) |
    {pod: .metadata.name, node: .spec.nodeName,
     created: .metadata.creationTimestamp, primaryIP: .status.podIP,
     ready: [.status.conditions[]? | select(.type == "Ready") | .status],
     requested: .metadata.annotations["k8s.v1.cni.cncf.io/networks"],
     attached: ((.metadata.annotations["k8s.v1.cni.cncf.io/network-status"] // "[]") | fromjson)}'
```

Empty output is a failed acceptance gate. Require each expected native workload
to be present and Ready, and each requested NetworkAttachmentDefinition to
appear in `attached` with its secondary interface and expected nonempty IPs.
Inside each selected native Pod, confirm those interfaces and addresses exist
and the expected secondary-network routes are installed:

```sh
kubectl -n octelium exec '<native-pod>' -c '<container-with-ip>' -- ip -br address
kubectl -n octelium exec '<native-pod>' -c '<container-with-ip>' -- ip route
```

Require a successful attachment created after the upgraded Multus daemon became
Ready on each node hosting native dataplane Pods. Existing pre-upgrade Pods do
not exercise the new CNI ADD path. If none exists, record acceptance as pending
until a reviewed repository-owned workload rollout creates one; do not manually
restart or delete Pods to manufacture evidence.

From an existing authorized client with Pod-network reachability, probe every
recovered native service directly. For an HTTPS service, preserve its hostname
and TLS verification while selecting the native Pod address:

```sh
curl --silent --show-error --max-time 10 --noproxy '*' \
  --resolve '<service-host>:<native-port>:<native-pod-ip>' \
  --output /dev/null --write-out '%{http_code}\n' \
  'https://<service-host>:<native-port>/<read-only-path>'
```

Use the service's actual protocol, listener port, CA trust, and normal authorized
probe; require its expected status/content, not merely any HTTP response. Repeat
against each native Pod and its reported secondary address where that listener
is bound. Do not use a Kubernetes Service, public DNS route, or emergency Pod as
the destination. Missing native replicas, attachment/interface mismatches,
unavailable inspection tools, unreachable native addresses, or unexpected probe
results leave acceptance pending. Only after these checks pass, run
`scripts/octelium-e2e-check.sh` for the external paths. Record Pod names, nodes,
creation times, attachment addresses, and probe outcomes; no live acceptance has
been established by this documentation change.

Do not roll back to v4.2.4 for the August 2026 worker outage. The
[v4.3.0 release](https://github.com/k8snetworkplumbingwg/multus-cni/releases/tag/v4.3.0)
adds `connectionLimit` as an opt-in Unix-listener cap, and its
[implementation](https://github.com/k8snetworkplumbingwg/multus-cni/pull/1510)
does not enter Kubernetes v1.34.1's
[PLEG pod-listing path](https://github.com/kubernetes/kubernetes/blob/v1.34.1/pkg/kubelet/pleg/generic.go#L232-L258).
Keep `connectionLimit: 4` across the v4.3.1 upgrade unless a controlled
reproduction proves a Multus regression. A rollback also restarts the thick daemon; upstream
[issue #1527](https://github.com/k8snetworkplumbingwg/multus-cni/issues/1527)
records that termination removes its generated CNI config. The priority change
cannot revive an unreachable kubelet, so the NotReady workers still require
operator reboot or physical recovery before the DaemonSet can roll out there.

Removing the `platform-multus` Argo CD Application removes the service; it is
safe only after all workloads that require Multus have been removed.
