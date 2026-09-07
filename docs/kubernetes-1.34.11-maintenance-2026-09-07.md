# Kubernetes 1.34.11 Maintenance, 2026-09-07

Status: Kubernetes `1.34.1` to `1.34.11` upgrade completed on all four nodes.
Core health, DNS, and PVC metrics passed verification; direct Grafana alert-state
verification remains pending. Talos remains `1.11.3`.

## Execution Record

The [CoreDNS handoff](knowledge-base/operations/coredns-gitops-ownership.md)
completed before the upgrade: the no-reboot Talos patch applied at 05:21:39 UTC,
and the post-handoff DNS gates passed at 05:23 UTC. All six resources remained
Argo-owned, both updated DNS replicas were Ready, the Corefile and Service
addresses were preserved, and both Talos DNS manifest IDs were absent.

Preflight confirmed the latest scheduled media PostgreSQL, Octelium PostgreSQL,
Deluge, Radarr, and Sonarr backups completed with their committed validators.
Their published artifacts remained present on the retained NFS claims, with no
active backup or migration Jobs. This combined publisher-time validation with
current file metadata; it was not a fresh artifact rehash or restore drill.
OpenClaw recovery and its fresh backup completed separately. A new verified
off-node etcd snapshot was taken after the DNS handoff before execution.

The initial API update waited several minutes and produced temporary kubelet
status-read errors. The original upgrade continued without intervention.
The [CLI wait](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/cluster/kubernetes/talos_managed.go#L486-L574)
checks the Kubernetes mirror Pod's `talos.dev/config-version` annotation and
readiness; Talos's separate status collector can lag that replacement. The
initial replacement delay's cause was not isolated.

The ordered command ran from 05:25:54 to 05:35:37 UTC and exited successfully.
Postflight at 05:36 UTC verified all four nodes Ready on `v1.34.11`, all seven
control-plane/proxy Pods Ready on target images, and each actual machine config
matching its strictly validated target. Talos services and etcd were healthy,
the canonical issuer was unchanged, all active Pods were Ready, all 42 Argo
Applications were Healthy/Synced, and all 50 PVCs were Bound. All four boot IDs
matched preflight at 05:42 UTC, confirming no node reboots.

Postflight found maintenance-time exits in seven current containers. Six latest
previous logs identify API discovery, authentication-config lookup, or
leader-election failures.
Kube-state-metrics has a liveness-restart event matching its last exit; its
endpoint failure's underlying cause was not established. None of these last
termination states was `OOMKilled`. All seven recovered, and the 05:36 to 05:38
comparison found no new restarts or Pod identity changes and all active Pods
Ready. This does not classify every older restart.

At 05:36:50 UTC, the DNS acceptance gate confirmed the same two DNS Pods, zero
container restarts, unchanged Corefile/Service/RBAC, all six tracked resources,
correct public/internal lookups, and absent Talos DNS manifests. Readiness
conditions were reasserted during kubelet restarts; this is recovered readiness,
not evidence of uninterrupted readiness throughout maintenance.

Direct kubelet inspection confirmed restored volume statistics for all 28
expected mounted node/PVC pairs, covering 30 Pod bindings. At 05:39:41 UTC, Prometheus
had fresh samples for those same 28 pairs, all 34 scrape targets up, and no
inventory drift. The unchanged PVC alert expression returned `31.8029%`, below
its `85%` threshold. These checks cover mounted supported volumes, not every
Bound or unmounted claim. Temporary local verification tunnels were closed.

The existing Grafana admin API returned HTTP 401, so direct current rule-state
verification remains pending. Prometheus query results and stale NoData log
entries do not prove the Grafana rule is Normal. Alert delivery was not tested.

A post-upgrade off-node etcd snapshot passed offline verification at 05:45:19 UTC;
the pre-maintenance copies were retained.
The procedure below records the reviewed maintenance gates and command.

## Desired Versions And Offline Validation

[kubernetes-1.34.11.yaml](../.talos/patches/kubernetes-1.34.11.yaml) records the
control-plane target's five images: Sidero's kubelet plus Kubernetes API server, controller
manager, scheduler, and kube-proxy at `v1.34.11`. Registry inspection confirmed
`linux/amd64` manifests and image configurations for all five on 2026-09-07.
The [selected release and collector fix](knowledge-base/operations/kubernetes-patch-maintenance-2026-09.md)
are compatible with the Talos 1.11 Kubernetes 1.34 support matrix.

Use that patch only for the control-plane bootstrap config or offline target
render. Workers use [worker-kubernetes-1.34.11.yaml](../.talos/patches/worker-kubernetes-1.34.11.yaml),
which changes only `machine.kubelet.image`. The actual CLI changes
`cluster.proxy.image` only on the control plane; kube-proxy Pods on workers
receive the new image through the cluster DaemonSet. Do not add unused API,
controller, scheduler, or proxy image fields to worker configs.

Preserve original cluster recovery material and all unrelated desired state.
Replace the private paths below and render each node locally with the matching
client:

```sh
umask 077
/opt/homebrew/bin/talosctl machineconfig patch \
  /path/to/private/current/acer.yaml \
  --patch @.talos/patches/kubernetes-1.34.11.yaml \
  --output /path/to/private/rendered/acer.yaml
for node in zimaboard-0 zimaboard-1 zimaboard-2; do
  /opt/homebrew/bin/talosctl machineconfig patch \
    "/path/to/private/current/$node.yaml" \
    --patch @.talos/patches/worker-kubernetes-1.34.11.yaml \
    --output "/path/to/private/rendered/$node.yaml"
done
for node in acer zimaboard-0 zimaboard-1 zimaboard-2; do
  /opt/homebrew/bin/talosctl validate --mode metal --strict \
    --config "/path/to/private/rendered/$node.yaml"
done
```

Require all four complete renders to pass strict validation. Review exactly
five image changes on `acer` and only the kubelet image on each worker;
preserve credentials, issuer, SANs, DNS ownership, disks,
networking, and workload-specific patches. Keep configs and comparison output
private. Do not apply these rendered version configs to live nodes: changing
all images together bypasses component ordering. Fresh bootstrap still follows
the [DNS bootstrap contract](knowledge-base/operations/coredns-gitops-ownership.md#bootstrap-and-rollback),
which retains Talos DNS until GitOps adoption is ready.

Private validation on 2026-09-07 used the actual Talos `v1.11.3` client and
current configs from all four nodes. Every role-specific target passed strict
metal validation. The control-plane comparison contained only the five image
changes after locally modeling the required DNS-disabled state; each worker
changed only kubelet, with Talos also omitting the existing empty
`machine.registries` map during serialization. Current images were unsuffixed
`v1.34.1`. These were private local renders; the DNS handoff and Kubernetes
upgrade were not executed by this validation.

## Required Maintenance Gates

1. Merge and sync the reviewed six-resource CoreDNS overlay. Complete its
   tracking-ID, rollout, Service-address, Corefile, and DNS lookup gates. Then
   apply only its separately validated `cluster.coreDNS.disabled: true`
   candidate in the documented no-reboot mode. Verify this value is active,
   Talos no longer exposes `11-core-dns` or `11-core-dns-svc`, and all six
   Kubernetes resources remain Argo-owned with two Ready DNS replicas. Follow
   the [ordered handoff](knowledge-base/operations/coredns-gitops-ownership.md#ordered-takeover);
   a merged declaration alone is insufficient.
2. Finish OpenClaw recovery and verify current application backups through each
   workload's declared backup path. Inspect CronJob last-success times and
   latest Job completion against their schedules, verify retained recovery
   artifacts, and investigate any failed or overdue backup. Do not restart
   kubelets while a backup or state migration is active. An etcd snapshot does
   not contain PVC data.
3. Run the healthy-cluster checks below immediately before maintenance. Require
   all four nodes Ready on the exact source version, every non-terminal Pod
   Ready, no unexplained restarts or node pressure, and every Argo Application
   Healthy/Synced at its reviewed revision. Require healthy Talos services on
   each node and one healthy etcd member with its leader present and no errors.
4. Create a new [verified private off-node etcd backup](talos-etcd-backup.md)
   after the DNS handoff, immediately before the upgrade; recheck it offline.
   Keep the manifest and private recovery material accessible without Kubernetes.
5. Obtain explicit approval for this exact maintenance sequence and window,
   with all gates recorded. Expect interruption of the sole Kubernetes API and
   serial kubelet restarts. The CLI does not drain nodes; no Talos OS upgrade,
   node reboot, or automatic workload evacuation is part of this change.

Read-only checks, using the existing authenticated Kubernetes context:

```sh
set -euo pipefail
kubectl get --raw /readyz
kubectl get nodes -o wide
kubectl get nodes -o json | jq -e '
  .items | length == 4 and all(.[];
    .status.nodeInfo.kubeletVersion == "v1.34.1" and
    all(.status.conditions[] | select(.type | IN(
      "MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"));
      .status == "False"))'
kubectl wait --for=condition=Ready node --all --timeout=1m
kubectl wait --for=condition=Ready pod --all --all-namespaces \
  --field-selector 'status.phase!=Succeeded,status.phase!=Failed' --timeout=1m
kubectl -n argocd get applications -o json | jq -e '
  .items | length > 0 and all(.[];
    .status.health.status == "Healthy" and .status.sync.status == "Synced")'
for node in 10.1.0.199 10.1.0.200 10.1.0.201 10.1.0.202; do
  /opt/homebrew/bin/talosctl --talosconfig /path/to/current-private-talosconfig \
    --endpoints 10.1.0.199 --nodes "$node" get services -o json |
    jq -se 'map(select(.metadata.id != "dashboard")) |
      length > 0 and all(.[];
        .spec.running == true and .spec.healthy == true and .spec.unknown == false)'
done
/opt/homebrew/bin/talosctl --talosconfig /path/to/current-private-talosconfig \
  --endpoints 10.1.0.199 --nodes 10.1.0.199 etcd status
/opt/homebrew/bin/talosctl --talosconfig /path/to/current-private-talosconfig \
  --endpoints 10.1.0.199 --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 version
kubectl get cronjobs -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,SCHEDULE:.spec.schedule,SUSPENDED:.spec.suspend,LAST_SUCCESS:.status.lastSuccessfulTime,ACTIVE:.status.active[*].name'
kubectl get jobs -A --sort-by=.metadata.creationTimestamp
```

An earlier inspection had 42/42 Applications Healthy/Synced and all four nodes on
Kubernetes `1.34.1` / Talos `1.11.3`; this dated observation does not satisfy the
fresh maintenance gates. Verify the exact current inventory and versions again.

## Approved Ordered Upgrade

Only after every gate passes, run once from the reviewed checkout with the
matching `/opt/homebrew/bin/talosctl` `v1.11.3` client. Keep the existing direct
Talos/LAN recovery path available throughout the API interruption.

```sh
/opt/homebrew/bin/talosctl --talosconfig /path/to/current-private-talosconfig \
  --endpoints 10.1.0.199 --nodes 10.1.0.199 \
  upgrade-k8s --from 1.34.1 --to 1.34.11 \
  --apiserver-image registry.k8s.io/kube-apiserver \
  --controller-manager-image registry.k8s.io/kube-controller-manager \
  --scheduler-image registry.k8s.io/kube-scheduler \
  --proxy-image registry.k8s.io/kube-proxy \
  --kubelet-image ghcr.io/siderolabs/kubelet \
  --upgrade-kubelet=true --pre-pull-images=true
```

The [Talos 1.11.3 implementation](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/cluster/kubernetes/talos_managed.go)
checks compatibility and upgrade preconditions, pulls images, updates API
server, controller manager, and scheduler in order, then updates kube-proxy
configuration. It restarts kubelets serially, control plane first followed by
the discovered worker order, waiting for each kubelet to become healthy and its
Node to report the target version and Ready. Finally it synchronizes remaining
bootstrap manifests. Allow temporary mixed component versions during this
sequence. Preserve private logs and the last completed step.

Do not run `upgrade-k8s --dry-run`: on this client it can pull images and submit
machine configuration. Do not apply either version patch directly, substitute the
Nix `1.13.2` client, disable kubelet upgrades, or run a concurrent maintenance
command. The CLI preserves an existing kubelet `-fat`/`-slim` suffix; stop
before execution if any current kubelet uses such a suffix or any component
uses a different image repository. Review the matching artifacts first.

## Acceptance

After the command returns, repeat the preflight's `/readyz`, Node/Pod Ready
waits, Argo health/sync, Talos services, etcd, and application-backup checks.
Use the target-aware version/pressure check below instead of the preflight's
`v1.34.1` assertion. Verify the API version, all four kubelet versions, and every
running control plane/proxy image against the committed patches:

```sh
kubectl version -o json | jq -e '.serverVersion.gitVersion == "v1.34.11"'
kubectl get nodes -o json | jq -e '
  .items | length == 4 and all(.[];
    .status.nodeInfo.kubeletVersion == "v1.34.11" and
    all(.status.conditions[] | select(.type | IN(
      "MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"));
      .status == "False"))'
/opt/homebrew/bin/talosctl --talosconfig /path/to/current-private-talosconfig \
  --endpoints 10.1.0.199 --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 version
kubectl -n kube-system get pods \
  -l 'k8s-app in (kube-apiserver,kube-controller-manager,kube-scheduler,kube-proxy)' \
  -o custom-columns='NAME:.metadata.name,NODE:.spec.nodeName,IMAGES:.spec.containers[*].image,READY:.status.containerStatuses[*].ready'
kubectl get --raw /.well-known/openid-configuration |
  jq -e '.issuer == "https://10.1.0.199:6443"'
```

Require API server, controller manager, scheduler, and proxy images all at
`v1.34.11`, all replicas Ready, and Talos unchanged. Recheck the GitOps Corefile,
two Ready DNS replicas, preserved Service IPs and tracking IDs, absent Talos DNS
manifest IDs, and the runbook's public/internal DNS lookups. Verify current
application readiness, backup health, and Argo convergence without live repairs.

For each node with a currently mounted supported PVC, check the restored
collector:

```sh
kubectl --request-timeout=30s get --raw /api/v1/nodes/acer/proxy/metrics |
  rg '^kubelet_volume_stats_(capacity|available)_bytes\{'
```

Repeat this for each applicable worker. Prometheus's Kubernetes Service proxy
returned connection resets after its worker placement; an authenticated,
localhost-only port-forward worked. Use that temporary access path without
changing AuthorizationPolicy. In a separate terminal:

```sh
kubectl -n monitoring port-forward --address 127.0.0.1 \
  service/prometheus-kube-prometheus-prometheus 19090:9090
```

Wait for the `Forwarding from 127.0.0.1:19090` message, allow a scrape interval,
then query both metric families from the operator host:

```sh
for metric in kubelet_volume_stats_capacity_bytes kubelet_volume_stats_available_bytes; do
  curl --fail --silent --show-error --max-time 30 --get \
    --data-urlencode "query=$metric" http://127.0.0.1:19090/api/v1/query |
    jq -e 'if .status == "success" and (.data.result | length) > 0
      then .data.result else error("PVC metric family has no samples") end'
done
```

Stop the temporary port-forward with Ctrl-C when verification finishes.
Compare returned namespace
and PVC labels with currently mounted supported claims; global nonempty queries
alone do not prove complete coverage. Retained unmounted claims are not missing
collector samples, and NFS subdirectory statistics measure their shared
filesystem. Confirm the existing PVC alert now evaluates real samples; alert
delivery validation remains separate.

## Stop And Recovery

Stop before starting if any gate fails. If the CLI fails or stalls, do not
launch a second upgrade, apply a full version config, reboot nodes, or mutate
Pods to force progress. Use authenticated reads to record actual component
versions, API/Talos/etcd health, DNS state, and the last completed step. A failed
command can leave partial progress; preserving that state is necessary for a
reviewed continuation decision.

Keep the verified snapshots and application backups. Escalate API/etcd/DNS or
workload failure for a new recovery decision. There is no automatic component
downgrade, Talos rollback, etcd restore, or PVC restore in this runbook. Mark
maintenance incomplete until all acceptance gates pass, even if the CLI exits
successfully.
