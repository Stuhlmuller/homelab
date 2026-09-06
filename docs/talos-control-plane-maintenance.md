# Talos Control-Plane Maintenance

This runbook owns repository-backed control-plane maintenance for Talos and
Kubernetes. It covers the current service-account issuer drift and the upgrade
checklist for Talos and Kubernetes patch releases.

Do not use this runbook to make ad hoc live changes. First express desired
state in this repository, validate the rendered Talos machine config, then
apply that reviewed config through the documented Talos path.

## Current Audit Findings

The parent audit reported:

- Live Kubernetes OIDC discovery issuer:
  `https://10.1.0.216:6443`.
- Canonical Kubernetes API endpoint:
  `https://10.1.0.199:6443`.
- Live node versions: Kubernetes `v1.34.1` and Talos `v1.11.3`.

Treat `10.1.0.216` as stale. It may still appear in live service-account issuer
discovery until the control-plane machine config is corrected and applied.

Security refresh on 2026-05-25:

- Kubernetes `v1.34.1` is still on a supported upstream minor, but upstream
  `1.34` has newer patch releases. Plan a Kubernetes patch upgrade after
  reading the current `1.34` changelog.
- Talos `v1.11.3` is behind the current Talos security baseline. Sidero's
  CVE-2026-31431 guidance recommends upgrading clusters to Talos `1.12.7` or
  newer, or `1.13.0` or newer. Treat a Talos minor upgrade as a separate
  maintenance change with validated machine config and a node-by-node rollout.

## Desired Service-Account Issuer State

The desired service-account issuer is the canonical Kubernetes API endpoint:

```text
https://10.1.0.199:6443
```

The repository-owned patch fragment lives at
`.talos/patches/controlplane-service-account-issuer.yaml` and sets:

```yaml
cluster:
  controlPlane:
    endpoint: https://10.1.0.199:6443
  apiServer:
    extraArgs:
      service-account-issuer: https://10.1.0.199:6443
```

This keeps the control-plane endpoint and Kubernetes service-account issuer
aligned. The kube-apiserver `service-account-issuer` value becomes the `iss`
claim in issued service-account tokens and drives service-account issuer
discovery. The rendered control-plane config must also keep `10.1.0.199` in
`cluster.apiServer.certSANs` so clients can verify the canonical endpoint.

The separate `.talos/patches/controlplane-octelium-talos-api.yaml` patch adds
`talos-api.homelab.local.stinkyboi.com` to `machine.certSANs`. That name is the
private Octelium TCP Service endpoint for the Talos API.
`.talos/patches/controlplane-kubernetes-api-san.yaml` replaces the Kubernetes
API SAN list with the canonical `10.1.0.199` address. Both SAN patches use
RFC 6902 list replacement so rerendering an already patched live config stays
idempotent and removes the stale `10.1.0.216` SAN.

Live validation on 2026-09-02 recovered the current control-plane configuration
without resetting Talos, generated a new local `os:admin` client from the
original CA, and saved a fresh etcd snapshot off-node. The SAN-only patch then
validated strictly, applied without a reboot, and appeared on Acer's live Talos
server certificate. Kubernetes readiness and Talos services remained healthy.
The private Octelium Service still requires its catalog rollout and an off-LAN
authenticated check before the Tailscale subnet route can be removed.

## Render And Validate The Control-Plane Changes

This checkout does not currently contain `.talos/controlplane.yaml` or
`.talos/talosconfig`. Add or restore those files only through the established
secret-safe Talos config workflow. Do not commit Talos secrets, raw certificate
material, private keys, or kubeconfigs.

When `.talos/controlplane.yaml` is available locally, render a candidate config:

```sh
talosctl machineconfig patch .talos/controlplane.yaml \
  --patch @.talos/patches/controlplane-service-account-issuer.yaml \
  --patch @.talos/patches/controlplane-kubernetes-api-san.yaml \
  --patch @.talos/patches/controlplane-octelium-talos-api.yaml \
  --output /private/tmp/controlplane-access.yaml

yq -e '
  .cluster.controlPlane.endpoint == "https://10.1.0.199:6443" and
  (.cluster.apiServer.certSANs | length == 1) and
  .cluster.apiServer.certSANs[0] == "10.1.0.199" and
  .cluster.apiServer.extraArgs."service-account-issuer" ==
    "https://10.1.0.199:6443" and
  (.machine.certSANs | length == 1) and
  .machine.certSANs[0] == "talos-api.homelab.local.stinkyboi.com"
' /private/tmp/controlplane-access.yaml
```

Validate before any live apply:

```sh
talosctl validate \
  --config /private/tmp/controlplane-access.yaml \
  --mode metal \
  --strict
```

Review the rendered config and confirm the only intended control-plane changes
are:

- `cluster.controlPlane.endpoint: https://10.1.0.199:6443`
- `cluster.apiServer.certSANs` includes `10.1.0.199`
- `cluster.apiServer.extraArgs.service-account-issuer:
  https://10.1.0.199:6443`
- `machine.certSANs` includes `talos-api.homelab.local.stinkyboi.com`

## Apply Sequence For Issuer Drift

Do not run these commands until the rendered config has passed validation and
the operator has explicitly approved the live Talos apply sequence.
Use the direct `10.1.0.199` Talos endpoint for this first apply because the
Octelium hostname is not valid until the new machine certificate is active.
Use the homelab LAN or the temporarily retained Tailscale subnet route, and do
not withdraw that fallback until the Octelium path passes the off-LAN check.

1. Confirm every node, non-terminal Pod, the API, and etcd are healthy with
   read-only commands:

   ```sh
   set -euo pipefail
   kubectl get nodes -o wide
   kubectl wait --for=condition=Ready node --all --timeout=1m
   kubectl wait --for=condition=Ready pod --all --all-namespaces \
     --field-selector "status.phase!=Succeeded,status.phase!=Failed" \
     --timeout=1m
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services -o json | jq -se '
       map(select(.metadata.id != "dashboard")) as $services
       | ($services | length) > 0 and
         all($services[];
           .spec.running == true and .spec.healthy == true and
           .spec.unknown == false)
     '
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     etcd status
   ```

2. Apply the validated rendered config to the Acer control-plane node:

   ```sh
   set -euo pipefail
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     apply-config --dry-run \
     --file /private/tmp/controlplane-access.yaml

   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     apply-config --mode=reboot \
     --file /private/tmp/controlplane-access.yaml
   ```

3. Watch the control plane recover:

   ```sh
   set -euo pipefail
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services -o json | jq -se '
       map(select(.metadata.id != "dashboard")) as $services
       | ($services | length) > 0 and
         all($services[];
           .spec.running == true and .spec.healthy == true and
           .spec.unknown == false)
     '

   kubectl wait --for=condition=Ready node/acer --timeout=10m
   kubectl wait --for=condition=Ready node --all --timeout=1m
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     etcd status
   ```

   Do not require cluster-wide Pod readiness between the Acer reboot and the
   first worker reboot. Talos 1.11 switches the only accepted issuer at once,
   so worker CNI credentials minted by the old issuer can reject API requests
   until that worker reboots. Continue only when every Node is Ready, Acer's
   services and etcd are healthy, and every unready workload is positively
   traced to old-issuer CNI authorization on an unrebooted worker. Stop on any
   unrelated or unexplained failure.

4. Verify issuer discovery no longer reports `10.1.0.216`:

   ```sh
   kubectl get --raw /.well-known/openid-configuration
   ```

   Expected issuer:

   ```json
   {"issuer":"https://10.1.0.199:6443"}
   ```

5. Refresh local kubeconfig only after the API is healthy:

   ```sh
   set -euo pipefail
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     kubeconfig ~/.kube/config --force

   kubectl config set-cluster homelab --server=https://10.1.0.199:6443
   ```

6. Reboot workers one at a time in this order: `zimaboard-2`, `zimaboard-1`,
   `zimaboard-0`. Before each reboot, require every Node, Acer's services and
   etcd, and the target worker's Talos services to be healthy. Start with an
   empty allowlist, then add only Pods whose Events or logs positively trace
   their failure to old-issuer credentials on workers that have not rebooted:

   ```sh
   set -euo pipefail
   node_name=zimaboard-2
   case "$node_name" in
     zimaboard-0) node_ip=10.1.0.200 ;;
     zimaboard-1) node_ip=10.1.0.201 ;;
     zimaboard-2) node_ip=10.1.0.202 ;;
     *) echo "unsupported worker: $node_name" >&2; exit 1 ;;
   esac
   approved_unready_pods='[]'

   services_healthy() {
     talosctl --talosconfig .talos/talosconfig \
       --endpoints 10.1.0.199 \
       --nodes "$1" \
       get services -o json | jq -se '
         map(select(.metadata.id != "dashboard")) as $services
         | ($services | length) > 0 and
           all($services[];
             .spec.running == true and .spec.healthy == true and
             .spec.unknown == false)
       '
   }

   kubectl wait --for=condition=Ready node --all --timeout=1m
   services_healthy 10.1.0.199
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     etcd status
   services_healthy "$node_ip"

   kubectl get pods --all-namespaces -o json | jq -e \
     --argjson approved "$approved_unready_pods" '
       ($approved | arrays) as $expected
       | [.items[]
        | select(.status.phase != "Succeeded" and .status.phase != "Failed")
        | select((.status.conditions // [] |
            any(.type == "Ready" and .status == "True")) | not)
        | "\(.metadata.namespace)/\(.metadata.name)" +
          "@\(.metadata.uid)@" +
          "\(.spec.nodeName // "<unbound>")"] as $actual
       | ($expected | all(.[]; type == "string")) and
         (($expected | unique | length) == ($expected | length)) and
         (($actual | sort) == ($expected | sort))
     '

   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes "$node_ip" \
     reboot --wait --timeout=10m

   kubectl wait --for=condition=Ready "node/$node_name" --timeout=10m
   kubectl wait --for=condition=Ready pod --all --all-namespaces \
     --field-selector \
       "spec.nodeName=$node_name,status.phase!=Succeeded,status.phase!=Failed" \
     --timeout=10m
   ```

   Set `node_name` in the order above; the `case` statement derives its address
   from the [worker address table](#remote-worker-reboot). This is the issuer
   cutover's narrow degraded-state exception to the normal worker reboot
   preflight.
   Rebuild `approved_unready_pods` before every worker; never carry names
   forward without fresh evidence. Each entry uses
   `namespace/name@pod-UID@node`; use `<unbound>` only when `spec.nodeName` is
   empty. Accept direct CNI `Unauthorized` errors or dependents whose failure
   traces to such a CNI error on an unrebooted worker. Missing or different
   evidence is an unrelated failure and stops the sequence. Also stop if the
   reboot or target-local readiness gate fails.
   The sequence recreates worker-bound projected tokens, and keeps
   `zimaboard-0`, which runs Istiod and the Octelium dataplane, until last.

7. After `zimaboard-0`, restore the normal global gates:

   ```sh
   set -euo pipefail
   kubectl wait --for=condition=Ready node --all --timeout=1m
   kubectl wait --for=condition=Ready pod --all --all-namespaces \
     --field-selector "status.phase!=Succeeded,status.phase!=Failed" \
     --timeout=10m
   ```

## Issuer Apply Risks

- A malformed control-plane config can interrupt the only control-plane node.
- If the rendered config accidentally changes cluster secrets, the node can
  lose trust with the existing cluster. Never regenerate secrets for this fix.
- If `certSANs` omits `10.1.0.199`, clients may fail TLS verification after the
  endpoint correction.
- Talos v1.11 cannot configure both the old and new service-account issuers for
  a non-disruptive transition. Existing projected tokens minted with the stale
  issuer fail authentication until kubelet rotates them. The sequence therefore
  reboots Acer with the apply and then each worker to recreate every projected
  token. Stop if any readiness gate fails; do not rely on eventual rotation.
- Do not use `talosctl patch machineconfig` or `talosctl edit machineconfig`.
  Emergency recovery also requires a repository-owned patch, rendered config,
  and validation before applying through the documented path.

## Remote Talos Through Octelium

The private `talos-api.homelab` Octelium TCP Service forwards raw port `50000`
to `10.1.0.199`. Its policy permits only the `homelab-owner` human client;
Talos mutual TLS still authenticates every request.

After the control-plane patch and Octelium catalog workflow both complete,
validate from an off-LAN workstation before withdrawing the Tailscale subnet
route:

```sh
octelium connect --domain stinkyboi.com --ip-mode=v4 -d
talosctl --talosconfig .talos/talosconfig \
  --endpoints talos-api.homelab.local.stinkyboi.com:50000 \
  --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 \
  version
```

The node addresses select Talos API targets; the client connection itself uses
the Octelium Service endpoint. Keep direct IP access as the LAN recovery path.

## Remote Worker Reboot

When physical access is unavailable and a ZimaBoard needs a restart, use its
authenticated Talos API instead of waiting for a manual power cycle. Reboot
only one exact node at a time:

| Node | Talos address |
| --- | --- |
| `zimaboard-0` | `10.1.0.200` |
| `zimaboard-1` | `10.1.0.201` |
| `zimaboard-2` | `10.1.0.202` |

Select one worker, confirm its Talos API answers, and require every node and
non-terminal pod to be ready before reboot:

```sh
node_name=zimaboard-0
case "$node_name" in
  zimaboard-0) node_ip=10.1.0.200 ;;
  zimaboard-1) node_ip=10.1.0.201 ;;
  zimaboard-2) node_ip=10.1.0.202 ;;
  *) echo "unsupported worker: $node_name" >&2; exit 1 ;;
esac

talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes "$node_ip" \
  get services

kubectl wait --for=condition=Ready node --all --timeout=1m &&
  kubectl wait --for=condition=Ready pod --all --all-namespaces \
    --field-selector "status.phase!=Succeeded,status.phase!=Failed" \
    --timeout=1m
```

If either preflight wait fails, do not reboot. This routine runbook does not
cover degraded-state maintenance; recover the unavailable node or workload
through its reviewed repository-owned path, or add that path first, then repeat
the preflight.

Only after preflight succeeds, reboot and require fresh node and cluster-wide
workload readiness, including unbound `Pending` replacements:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes "$node_ip" \
  reboot --wait

kubectl wait --for=condition=Ready "node/$node_name" --timeout=10m
kubectl wait --for=condition=Ready pod --all --all-namespaces \
  --field-selector "status.phase!=Succeeded,status.phase!=Failed" \
  --timeout=10m
```

If either readiness check times out, do not reboot another worker. Inspect the
affected pods with `kubectl get pods -A -o wide`, then use the workload's
repository-backed recovery path; do not delete, restart, or patch live pods by
hand.

If a normal reboot completes but the node remains stuck and the Talos API still
answers, retry the reboot with `--mode=powercycle`. Never add `--insecure` for
an already configured node. If authenticated Talos access is unavailable,
stop; physical intervention is required.

### Degraded Recovery: Issuer-Cutover Resource Stall

This dated exception covers the 2026-09-02 issuer cutover only. CNI
authentication failures caused restart and termination churn; memory, eMMC,
and NFS I/O then wedged the `zimaboard-1` kubelet. `zimaboard-2` showed severe
pressure and a simultaneous kubelet stall, but its exact cause is unverified.
Acer and `zimaboard-0` remained healthy. API-deleted NFS Pods may still be
executing on an unreachable worker, so its reboot is also writer fencing. Do
not restore it in place, force-delete Pods, or touch PVCs.

Recover `zimaboard-1` first. Run the Talos recovery blocks for `zimaboard-2`
only after every `zimaboard-1` postflight passes. The self-contained preflight
validates the healthy cluster first, then preserves but stops Cordium Workspace
`v64` through
[Cordium's native lifecycle command](https://octelium.com/docs/cordium/latest/use/cli).
Its Kubernetes resource name is `ws-v64`. The gate rejects an ephemeral
Workspace, preserves the exact bound PVC, waits for the controller-owned
ConfigMap, Service, and Deployment to disappear, and allows only zero-replica
remnants or deleting Pods. It never scales or deletes Kubernetes resources
directly.

No worker reboot was submitted before this incident path was added; stop if an
earlier reboot request might still be outstanding. Set the private snapshot
path, select one target, then run this preflight and one-shot reboot exactly
once:

```bash
set -euo pipefail
snapshot_file=/path/to/recent-off-node-etcd-snapshot.db
node_name=zimaboard-1
workspace_name=v64
workspace_resource=ws-v64

case "$node_name" in
  zimaboard-1)
    node_ip=10.1.0.201
    healthy_nodes=(acer zimaboard-0)
    healthy_ips=(10.1.0.199 10.1.0.200)
    ;;
  zimaboard-2)
    node_ip=10.1.0.202
    healthy_nodes=(acer zimaboard-0 zimaboard-1)
    healthy_ips=(10.1.0.199 10.1.0.200 10.1.0.201)
    ;;
  *) echo "unsupported recovery target: $node_name" >&2; exit 1 ;;
esac
attempt_dir="/private/tmp/$node_name.recovery-attempt"

services_healthy() {
  talosctl --talosconfig .talos/talosconfig \
    --endpoints "$1" --nodes "$1" get services -o json | jq -se '
      map(select(.metadata.id != "dashboard")) as $services
      | ($services | length) > 0 and
        all($services[];
          .spec.running == true and .spec.healthy == true and
          .spec.unknown == false)
    '
}

recovery_preflight() {
  test -s "$snapshot_file"
  test ! -e "$attempt_dir"
  for healthy_node in "${healthy_nodes[@]}"; do
    kubectl wait --for=condition=Ready \
      "node/$healthy_node" --timeout=1m
  done
  kubectl get lease -n kube-node-lease "${healthy_nodes[@]}" -o json |
    jq -e --argjson expected "${#healthy_nodes[@]}" \
      --argjson now "$(date -u +%s)" '
        (.items | length) == $expected and
        all(.items[];
          ($now - (.spec.renewTime |
            sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)) as $age
          | $age >= 0 and $age < 60)
      '
  for healthy_ip in "${healthy_ips[@]}"; do
    services_healthy "$healthy_ip"
  done
  talosctl --talosconfig .talos/talosconfig \
    --endpoints 10.1.0.199 --nodes 10.1.0.199 etcd status
  if [[ "$node_name" == zimaboard-2 ]]; then
    prerequisite_file=/private/tmp/zimaboard-1.recovery-attempt/complete.boot-id
    test -s "$prerequisite_file"
    prerequisite_boot_id="$(talosctl \
      --talosconfig .talos/talosconfig \
      --endpoints 10.1.0.201 --nodes 10.1.0.201 \
      read /proc/sys/kernel/random/boot_id | tr -d '\n')"
    test -n "$prerequisite_boot_id"
    test "$prerequisite_boot_id" = \
      "$(tr -d '\n' <"$prerequisite_file")"
  fi
  kubectl get node "$node_name" -o json | jq -e '
    any(.status.conditions[];
      .type == "Ready" and .status == "Unknown")
  '
  talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" get services -o json |
    jq -se '
      map({key: .metadata.id, value: .spec}) | from_entries as $services
      | ["apid", "machined", "containerd", "cri"] as $required
      | all($required[];
          . as $name
          | $services[$name].running == true and
            $services[$name].healthy == true and
            $services[$name].unknown == false)
    '
}

workspace_json="$(cordium get ws "$workspace_name" \
  --domain stinkyboi.com -o json)"
jq -e --arg name "$workspace_name" '
  .metadata.name == $name and (.spec.isEphemeral // false) == false
' <<<"$workspace_json"
workspace_uid="$(jq -er '.metadata.uid | select(length > 0)' \
  <<<"$workspace_json")"
workspace_pvc="ws-$workspace_uid"
pvc_json="$(kubectl get pvc "$workspace_pvc" -n cordium -o json)"
pvc_uid="$(jq -er '
  select(.status.phase == "Bound") | .metadata.uid | select(length > 0)
' <<<"$pvc_json")"
pvc_volume="$(jq -er '.spec.volumeName | select(length > 0)' \
  <<<"$pvc_json")"

cordium_workspace_stopped() {
  cordium get ws "$workspace_name" --domain stinkyboi.com -o json |
    jq -e --arg uid "$workspace_uid" '
      .metadata.uid == $uid and .status.state == "STOPPED"
    ' &&
    kubectl get configmap,deploy,rs,pod,pvc,service -n cordium -o json |
      jq -e --arg resource "$workspace_resource" \
        --arg uid "$workspace_uid" --arg pvc "$workspace_pvc" \
        --arg pvc_uid "$pvc_uid" --arg volume "$pvc_volume" '
          ([.items[]
            | select(.kind == "ConfigMap" and
                .metadata.name == $resource)] | length == 0) and
          ([.items[]
            | select(.kind == "Deployment" and
                .metadata.name == $resource)] | length == 0) and
          ([.items[]
            | select(.kind == "Service" and
                .metadata.name == $resource)] | length == 0) and
          ([.items[]
            | select(.kind == "ReplicaSet" and
                .metadata.labels["octelium.com/workspace-uid"] == $uid)
            | select((.spec.replicas // 0) != 0 or
                (.status.replicas // 0) != 0 or
                (.status.readyReplicas // 0) != 0)] | length == 0) and
          ([.items[]
            | select(.kind == "Pod" and
                .metadata.labels["octelium.com/workspace-uid"] == $uid)
            | select(.metadata.deletionTimestamp == null)
            | select(.status.phase != "Succeeded" and
                .status.phase != "Failed")] | length == 0) and
          ([.items[]
            | select(.kind == "PersistentVolumeClaim" and
                .metadata.name == $pvc and .metadata.uid == $pvc_uid and
                .spec.volumeName == $volume and
                .status.phase == "Bound")] | length == 1)
        '
}

recovery_preflight
if [[ "$node_name" == zimaboard-1 ]]; then
  workspace_state="$(cordium get ws "$workspace_name" \
    --domain stinkyboi.com -o json |
    jq -er --arg uid "$workspace_uid" '
      select(.metadata.uid == $uid) | .status.state
    ')"
  case "$workspace_state" in
    STOPPING_REQUEST | STOPPING | STOPPED) ;;
    *) cordium stop "$workspace_name" --domain stinkyboi.com ;;
  esac
fi
for attempt in {1..30}; do
  if cordium_workspace_stopped; then
    break
  fi
  ((attempt < 30)) || {
    echo "Cordium workspace did not stop safely" >&2
    exit 1
  }
  sleep 10
done
recovery_preflight
cordium_workspace_stopped

umask 077
mkdir "$attempt_dir"
boot_id_file="$attempt_dir/boot-id.before"
start_file="$attempt_dir/start-epoch"
talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" \
  read /proc/sys/kernel/random/boot_id >"$boot_id_file"
date -u +%s >"$start_file"
test -s "$boot_id_file"
test -s "$start_file"

talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" \
  reboot --mode=default --wait --timeout=10m
```

If the reboot times out, do not submit another reboot or immediately power
cycle. First select the same `node_name` and run this five-minute identity
gate. It fails closed if the node becomes unreachable or its boot ID changes:

```bash
set -euo pipefail
node_name=zimaboard-1
case "$node_name" in
  zimaboard-1)
    node_ip=10.1.0.201
    healthy_nodes=(acer zimaboard-0)
    healthy_ips=(10.1.0.199 10.1.0.200)
    ;;
  zimaboard-2)
    node_ip=10.1.0.202
    healthy_nodes=(acer zimaboard-0 zimaboard-1)
    healthy_ips=(10.1.0.199 10.1.0.200 10.1.0.201)
    ;;
  *) echo "unsupported recovery target: $node_name" >&2; exit 1 ;;
esac

services_healthy() {
  talosctl --talosconfig .talos/talosconfig \
    --endpoints "$1" --nodes "$1" get services -o json | jq -se '
      map(select(.metadata.id != "dashboard")) as $services
      | ($services | length) > 0 and
        all($services[];
          .spec.running == true and .spec.healthy == true and
          .spec.unknown == false)
    '
}

boot_id_file="/private/tmp/$node_name.recovery-attempt/boot-id.before"
test -s "$boot_id_file"
old_boot_id="$(tr -d '\n' <"$boot_id_file")"
for attempt in {1..30}; do
  current_boot_id="$(talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" \
    read /proc/sys/kernel/random/boot_id | tr -d '\n')"
  test -n "$current_boot_id"
  test "$current_boot_id" = "$old_boot_id"
  ((attempt == 30)) || sleep 10
done
kubectl get node "$node_name" -o json | jq -e '
  any(.status.conditions[];
    .type == "Ready" and .status == "Unknown")
'
for healthy_node in "${healthy_nodes[@]}"; do
  kubectl wait --for=condition=Ready \
    "node/$healthy_node" --timeout=1m
done
kubectl get lease -n kube-node-lease "${healthy_nodes[@]}" -o json |
  jq -e --argjson expected "${#healthy_nodes[@]}" \
    --argjson now "$(date -u +%s)" '
      (.items | length) == $expected and
      all(.items[];
        ($now - (.spec.renewTime |
          sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)) as $age
        | $age >= 0 and $age < 60)
    '
for healthy_ip in "${healthy_ips[@]}"; do
  services_healthy "$healthy_ip"
done
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 --nodes 10.1.0.199 etcd status
if [[ "$node_name" == zimaboard-2 ]]; then
  prerequisite_file=/private/tmp/zimaboard-1.recovery-attempt/complete.boot-id
  test -s "$prerequisite_file"
  prerequisite_boot_id="$(talosctl \
    --talosconfig .talos/talosconfig \
    --endpoints 10.1.0.201 --nodes 10.1.0.201 \
    read /proc/sys/kernel/random/boot_id | tr -d '\n')"
  test -n "$prerequisite_boot_id"
  test "$prerequisite_boot_id" = \
    "$(tr -d '\n' <"$prerequisite_file")"
fi
kubectl get node "$node_name" -o json | jq -e '
  any(.status.conditions[];
    .type == "Ready" and .status == "Unknown")
'
final_boot_id="$(talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" \
  read /proc/sys/kernel/random/boot_id | tr -d '\n')"
test -n "$final_boot_id"
test "$final_boot_id" = "$old_boot_id"
```

Only a fully passing identity gate permits a physical power-cycle of the exact
selected worker; the power event fences its stale NFS writers. If the boot ID
changed, run postflight. If any read failed, wait and inspect the physical node
instead of assuming the reboot stalled. After the reboot or physical recovery,
select the same `node_name` and run the postflight:

```bash
set -euo pipefail
node_name=zimaboard-1

case "$node_name" in
  zimaboard-1)
    node_ip=10.1.0.201
    allowed_unrecovered_node=zimaboard-2
    ;;
  zimaboard-2)
    node_ip=10.1.0.202
    allowed_unrecovered_node=
    ;;
  *) echo "unsupported recovery target: $node_name" >&2; exit 1 ;;
esac

attempt_dir="/private/tmp/$node_name.recovery-attempt"
boot_id_file="$attempt_dir/boot-id.before"
start_file="$attempt_dir/start-epoch"
complete_file="$attempt_dir/complete.boot-id"
test -s "$boot_id_file"
test -s "$start_file"
old_boot_id="$(tr -d '\n' <"$boot_id_file")"
new_boot_id="$(talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" \
  read /proc/sys/kernel/random/boot_id | tr -d '\n')"
test -n "$new_boot_id"
test "$new_boot_id" != "$old_boot_id"

talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" get services -o json |
  jq -se '
    map(select(.metadata.id != "dashboard")) as $services
    | ($services | length) > 0 and
      all($services[];
        .spec.running == true and .spec.healthy == true and
        .spec.unknown == false)
  '
kubectl wait --for=condition=Ready "node/$node_name" --timeout=10m
kubectl get lease -n kube-node-lease "$node_name" -o json |
  jq -e --argjson now "$(date -u +%s)" '
    ($now - (.spec.renewTime |
      sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)) as $age
    | $age >= 0 and $age < 60
  '
kubectl wait --for=condition=Ready pod --all --all-namespaces \
  --field-selector \
    "spec.nodeName=$node_name,status.phase!=Succeeded,status.phase!=Failed" \
  --timeout=10m

observation_start_epoch="$(date -u +%s)"
pods_json="$(kubectl get pods --all-namespaces -o json)"
restart_baseline="$(jq -c --arg node "$node_name" '
  [.items[]
   | select(.spec.nodeName == $node)
   | select(.status.phase != "Succeeded" and
       .status.phase != "Failed")
   | . as $pod
   | (((.status.initContainerStatuses // []) |
       map({kind: "init", status: .})) +
      ((.status.containerStatuses // []) |
       map({kind: "app", status: .})))[]
   | {key: "\($pod.metadata.uid)/\(.kind)/\(.status.name)",
      restarts: .status.restartCount}]
' <<<"$pods_json")"
for sample in {1..31}; do
  pods_json="$(kubectl get pods --all-namespaces -o json)"
  jq -e '
    [.items[]
     | select((.spec.nodeName // "") == "" or
         .spec.nodeName == "zimaboard-1")
     | select(.metadata.labels["octelium.com/component"] ==
         "workspace")
     | select(.metadata.deletionTimestamp == null)
     | select(.status.phase != "Succeeded" and
         .status.phase != "Failed")]
    | length == 0
  ' <<<"$pods_json"
  current_restarts="$(jq -c --arg node "$node_name" \
    --argjson cutoff "$observation_start_epoch" '
      [.items[]
       | select(.spec.nodeName == $node)
       | select(.status.phase != "Succeeded" and
           .status.phase != "Failed")
       | . as $pod
       | (((.status.initContainerStatuses // []) |
           map({kind: "init", status: .})) +
          ((.status.containerStatuses // []) |
           map({kind: "app", status: .})))[]
       | {key: "\($pod.metadata.uid)/\(.kind)/\(.status.name)",
          restarts: .status.restartCount,
          new_oom:
            (.status.lastState.terminated.reason == "OOMKilled" and
             ((.status.lastState.terminated.finishedAt |
               sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) >= $cutoff))}]
    ' <<<"$pods_json")"
  jq -en --argjson baseline "$restart_baseline" \
    --argjson current "$current_restarts" '
      (($baseline | map({key, restarts}) | sort_by(.key)) ==
       ($current | map({key, restarts}) | sort_by(.key))) and
      all($current[]; .new_oom == false)
    '

  meminfo="$(talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" read /proc/meminfo)"
  mem_total_kib="$(awk '$1 == "MemTotal:" {print $2}' <<<"$meminfo")"
  mem_available_kib="$(awk \
    '$1 == "MemAvailable:" {print $2}' <<<"$meminfo")"
  blocked="$(talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" read /proc/stat |
    awk '$1 == "procs_blocked" {print $2}')"
  memory_full_avg60="$(talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" read /proc/pressure/memory |
    awk '$1 == "full" {sub("avg60=", "", $3); print $3}')"
  io_full_avg60="$(talosctl --talosconfig .talos/talosconfig \
    --endpoints "$node_ip" --nodes "$node_ip" read /proc/pressure/io |
    awk '$1 == "full" {sub("avg60=", "", $3); print $3}')"

  [[ "$mem_total_kib" =~ ^[0-9]+$ ]]
  [[ "$mem_available_kib" =~ ^[0-9]+$ ]]
  [[ "$blocked" =~ ^[0-9]+$ ]]
  [[ "$memory_full_avg60" =~ ^[0-9]+([.][0-9]+)?$ ]]
  [[ "$io_full_avg60" =~ ^[0-9]+([.][0-9]+)?$ ]]
  ((mem_available_kib * 5 > mem_total_kib))
  ((blocked == 0))
  awk -v memory="$memory_full_avg60" -v io="$io_full_avg60" \
    'BEGIN { exit !(memory < 1 && io < 1) }'
  ((sample == 31)) || sleep 60
done

kubectl get pods --all-namespaces -o json |
  jq -e --arg allowed "$allowed_unrecovered_node" '
    [.items[]
     | select(.status.phase != "Succeeded" and
         .status.phase != "Failed")
     | select((.status.conditions // [] |
         any(.type == "Ready" and .status == "True")) | not)
     | select($allowed == "" or .spec.nodeName != $allowed)]
    | length == 0
  '
kubectl get events --all-namespaces -o json |
  jq -e --argjson cutoff "$observation_start_epoch" '
    [.items[]
     | (.series.lastObservedTime // .lastTimestamp // .eventTime //
        .metadata.creationTimestamp) as $timestamp
     | select(($timestamp |
         sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) >= $cutoff)
     | select((.message // "") |
         test("unauthorized|credentials are required|token.*issuer"; "i"))]
    | length == 0
  '
verified_boot_id="$(talosctl --talosconfig .talos/talosconfig \
  --endpoints "$node_ip" --nodes "$node_ip" \
  read /proc/sys/kernel/random/boot_id | tr -d '\n')"
test -n "$verified_boot_id"
test "$verified_boot_id" = "$new_boot_id"
(
  set -o noclobber
  printf '%s\n' "$verified_boot_id" >"$complete_file"
)
```

Any postflight failure stops the sequence. After `zimaboard-1` passes, repeat
both blocks once for `zimaboard-2` only if it remains `Unknown`; never reboot a
worker that recovered naturally. Then restore the global Node and Pod gates
from the issuer sequence. Do not reboot `zimaboard-0` merely for symmetry; skip
it when its services stay healthy and no fresh issuer error appears. A clean
pressure sample means more than 20% `MemAvailable`, zero blocked processes, and
less than 1% full memory and I/O stall time over the kernel's 60-second PSI
window. The 31 one-minute samples cover the incident's observed 18–30 minute
failure lag and also reject Pod replacement, container-set changes, new
restarts, OOM kills, or an active Cordium workspace on `zimaboard-1`.

### Degraded Recovery: `zimaboard-2`

This exception covers only the unreachable `zimaboard-2` (`10.1.0.202`) from
the August 2026 outage. It does not relax the healthy-cluster gate for routine
reboots. Its 1.28 GiB allocatable memory cannot hold the measured Octelium
dataplane fleet; rebooting while its dataplane label remains would permit the
same overload again.

Before recovery, require the other three nodes Ready and verify the native
Octelium Deployments have available replicas on `zimaboard-0`. Keep the
emergency Deployments in place. Inspect every Pod bound to `zimaboard-2`,
including terminating Pods; if any mounts a PVC, stop and establish a separate
writer-fencing and data-recovery plan before proceeding.

Apply the reviewed `IaC/live/kubernetes-node-labels` unit through the
[documented saved-plan recovery path](ci-cd.md#octelium-ci-access-setup).
Its `zimaboard-2 = {}` input removes the Terragrunt-owned dataplane label while
retaining the label-management resource and Node. The expected plan updates
only `kubernetes_labels.nodes["zimaboard-2"]`; reject unrelated changes.
The Octelium gateway-agent DaemonSet should then mark its old Pod for deletion.
Label removal does not evict already bound Deployment Pods, so verify they are
already terminating rather than assuming the label change fenced them.

Run these read-only gates immediately before either authenticated or physical
recovery; every command must succeed:

```sh
set -euo pipefail
kubectl wait --for=condition=Ready node/acer node/zimaboard-0 node/zimaboard-1 --timeout=1m
kubectl get node zimaboard-2 -o json |
  jq -e '.metadata.labels | has("octelium.com/node-mode-dataplane") | not'
kubectl get pods -A --field-selector spec.nodeName=zimaboard-2 -o json |
  jq -e '
    all(.items[]; all(.spec.volumes[]?; has("persistentVolumeClaim") | not)) and
    all(.items[] | select(.metadata.namespace == "octelium");
      .metadata.deletionTimestamp != null)
  '
```

Use a current Talos client configuration trusted by this cluster; an expired
certificate or one signed by an old CA is not usable. Verify authenticated
access to this exact worker before a remote reboot:

```sh
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.202 --nodes 10.1.0.202 get services
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.202 --nodes 10.1.0.202 reboot --wait
```

On Talos v1.11, `--mode=powercycle` skips kexec but does not skip graceful
teardown. If this reboot stalls in `stopAllPods` while stopping an unhealthy
kubelet, let the bounded command time out and do not submit another reboot.
The 2026-09-02 recovery attempt reached this state without restarting the node;
the subsequent physical power-cycle restored it.

If authentication is unavailable, do not run the reboot command or use
`--insecure`. An operator with physical access must identify `zimaboard-2`
before power-cycling only that worker. Do not force-delete Pods, clear locks,
patch labels, or change other live resources manually.

After recovery, require a fresh Ready heartbeat and ready node-local Pods:

```sh
kubectl wait --for=condition=Ready node/zimaboard-2 --timeout=10m
kubectl wait --for=condition=Ready pod -A \
  --field-selector \
    'spec.nodeName=zimaboard-2,status.phase!=Succeeded,status.phase!=Failed' \
  --timeout=10m
kubectl get nodes -o wide
kubectl top nodes
kubectl get pods -A --field-selector spec.nodeName=zimaboard-2 -o wide
```

Verify old terminating Pods disappear through kubelet reconciliation, Multus
and Istio node agents recover, the dataplane label remains absent, and restart
counts stop rising. Stop if readiness times out; do not reboot another node.
Do not restore the dataplane label as a rollback on this undersized worker.
Restore redundancy only after a dedicated replacement passes the capacity and
24-hour stability gates in the knowledge-base topology note.

## Talos And Kubernetes Upgrade Checklist

Use this checklist before changing Talos or Kubernetes versions. The observed
baseline from the parent audit is Talos `v1.11.3` and Kubernetes `v1.34.1`.

1. Refresh official release information:

   ```sh
   talosctl version
   kubectl version
   kubectl get nodes -o wide
   ```

   Then check the Talos support matrix, Talos release notes, Talos security
   guidance, and Kubernetes release notes for the selected target versions.

2. Choose targets:

   - For a Kubernetes patch upgrade within `1.34`, choose the latest supported
     `1.34.z` patch that is compatible with the installed Talos release.
   - For a Talos patch upgrade within `1.11`, choose the latest supported
     `1.11.z` installer image.
   - For a Talos minor upgrade, confirm Kubernetes compatibility and read every
     machine-config migration note before changing anything.

3. Validate repository state:

   ```sh
   nix flake check
   talosctl validate --config <rendered-control-plane-config> --mode metal --strict
   talosctl validate --config <rendered-worker-config> --mode metal --strict
   ```

4. Preflight live state with read-only commands:

   ```sh
   kubectl get nodes -o wide
   kubectl get pods -A
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 \
     get services
   ```

5. For a Kubernetes upgrade, run the Talos-managed Kubernetes upgrade from the
   control-plane node after reading the target release notes:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     upgrade-k8s --to <target-kubernetes-version>
   ```

   Verify every node reports the target Kubernetes version before considering
   the Kubernetes upgrade complete.

6. For a Talos upgrade, upgrade one node at a time, starting with workers:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes <node-ip> \
     upgrade --image ghcr.io/siderolabs/installer:<target-talos-version>
   ```

   Wait for the node to return `Ready` and for Talos services to become healthy
   before continuing to the next node. Upgrade the single control-plane node
   last.

7. Post-upgrade verification:

   ```sh
   kubectl get nodes -o wide
   kubectl get pods -A
   kubectl get --raw /.well-known/openid-configuration
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 \
     get systemdisk
   ```

   Required results:

   - All nodes are `Ready`.
   - Kubernetes versions match the target.
   - The OIDC discovery issuer is `https://10.1.0.199:6443`.
   - Talos still reports the intended internal system disks.

## Upgrade Risks

- Talos OS upgrades do not automatically upgrade Kubernetes; plan and validate
  them as separate operations.
- A single control-plane cluster has no API-server redundancy. Schedule a
  maintenance window before upgrading or applying control-plane config.
- Skipping supported version paths can strand the node on an unsupported Talos
  or Kubernetes combination.
- Storage workloads depend on QNAP-backed NFS. Verify stateful applications and
  storage health after every node reboot.
- If a version change requires machine-config schema migration, commit the
  desired config update first, render it locally, and validate it before the
  live upgrade.

## Corrupt Kubernetes Object Recovery

Use `scripts/recover-kubernetes-storage-20260825.sh` only for the exact
2026-08-25 incident recorded in the knowledge base. It verifies the known
decode failures and the healthy deployed Argo CD Helm revision before changing
state. With `--execute`, it runs a transient etcd client on `acer`, saves an
etcd snapshot at
`/var/mnt/etcd-before-corruption-repair-20260825.db`, removes only the
corrupt keys, waits for API and CRD recovery, then reschedules OpenClaw off
`acer`.

### Restore the incident snapshot

Use this rollback only if the exact-key deletion removes unexpected state or
reconciliation does not recover. It rebuilds the single-member etcd cluster
from the pre-repair snapshot, so schedule a maintenance window and confirm
authenticated Talos access and physical console access first.

The Talos reset wipes `acer`'s `EPHEMERAL` partition, including the active
`media-postgres` data. First commit and merge a temporary client-writer fence:
set `controllers.<app>.replicas: 0` in the Sonarr, Radarr, and Prowlarr
`values.yaml` files. Wait for Argo CD to sync and require this command to find
no pods:

```sh
kubectl -n media get pod \
  -l 'app.kubernetes.io/name in (sonarr,radarr,prowlarr)'
```

Prepare and review a second PR that sets `media-postgres-local` replicas to `0`
in `clusters/homelab/apps/media-postgres/statefulset.yaml` and sets
`suspend: true` in
`clusters/homelab/apps/media-postgres/backup-cronjob.yaml`, but do not merge it
yet. With all database clients fenced, create a fresh verified recovery set on
QNAP through the dated repository-owned path:

```sh
scripts/recover-kubernetes-storage-20260825.sh --prepare-restore
```

The command creates the Job with an unschedulable toleration so it can run while
`acer` is quarantined. It checks all six custom-format dumps and their SHA-256
checksums, cordons `acer`, and stops PostgreSQL before printing `completed
backup <BACKUP_ID>:` with the matching
`/backup/logical-backups/<BACKUP_ID>` path. Record `BACKUP_ID` for the restore.

Merge the prepared PostgreSQL fence PR immediately. Wait for Argo CD to sync,
then require the first command to print no Ready database pod and the second to
print no active backup Job:

```sh
kubectl -n media get pod \
  -l app.kubernetes.io/name=media-postgres,app.kubernetes.io/instance=local \
  -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'
kubectl -n media get job -l app.kubernetes.io/name=media-postgres-backup \
  -o jsonpath='{range .items[?(@.status.active)]}{.metadata.name}{"\n"}{end}'
```

Copy the snapshot off `acer` before wiping its ephemeral partition:

```sh
talosctl --talosconfig .talos/talosconfig --nodes 10.1.0.199 \
  cp /var/mnt/etcd-before-corruption-repair-20260825.db \
  ./etcd-before-corruption-repair-20260825.db
```

Reset only the ephemeral partition, wait until `talosctl service etcd` reports
`Preparing`, then recover the snapshot:

```sh
talosctl --talosconfig .talos/talosconfig --nodes 10.1.0.199 \
  reset --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
talosctl --talosconfig .talos/talosconfig --nodes 10.1.0.199 service etcd
talosctl --talosconfig .talos/talosconfig --nodes 10.1.0.199 \
  bootstrap --recover-from=./etcd-before-corruption-repair-20260825.db
```

The bootstrap result must print the snapshot hash, revision, total keys, and
size. The restored Node object predates the quarantine. As soon as the API
answers, re-cordon `acer` before any other Kubernetes operation and require the
verification to print `true`:

```sh
kubectl cordon acer
kubectl get node acer -o jsonpath='{.spec.unschedulable}{"\n"}'
```

Then verify etcd is healthy and the API is live:

```sh
talosctl --talosconfig .talos/talosconfig --nodes 10.1.0.199 etcd status
kubectl get --raw=/livez
kubectl -n argocd get secret sh.helm.release.v1.argocd.v14 \
  -o jsonpath='{.metadata.labels.status}{"\n"}'
```

Expected results are a healthy single etcd member, `ok`, and `deployed`. The
snapshot intentionally restores the three corrupt records too; their recorded
decode failures should return. Stop and revise the exact-key repair if any
other state differs.

Do not invoke the PostgreSQL recovery overlay yet. If the rollback was caused
by an unrelated failure and the three-key scope is still valid, rerun the
dated repair; otherwise commit and review a revised exact-key recovery before
changing live state:

```sh
scripts/recover-kubernetes-storage-20260825.sh --execute
```

Require the repair to complete, then verify API, External Secrets, and Argo CD
reconciliation:

```sh
kubectl get --raw=/readyz
kubectl get crd clustersecretstores.external-secrets.io -o name
kubectl -n media get secret media-postgres-arr-env -o name
kubectl -n external-secrets rollout status deployment/external-secrets \
  --timeout=5m
kubectl -n argocd rollout status statefulset/argocd-application-controller \
  --timeout=5m
kubectl -n argocd get application media-postgres \
  -o jsonpath='{.status.sync.status}{"\t"}{.status.health.status}{"\n"}'
```

Expected results are `ok`, both object names, successful controller rollouts,
and `Synced` plus `Healthy`. The dated repair also validates all expected keys
in `media-postgres-arr-env`; do not continue if it exits before its success
message.

Before unfencing PostgreSQL or starting the media apps, use the recorded
`BACKUP_ID` and the two-revision recovery-overlay procedure in
[`clusters/homelab/apps/media-postgres/README.md`](../clusters/homelab/apps/media-postgres/README.md#backup-and-restore).
The overlay follow-up revision must return the Application to the base path,
set `media-postgres-local` back to one replica in `statefulset.yaml`, and set
`suspend: false` in `backup-cronjob.yaml`. Uncordon `acer` only after the
restore Job succeeds and memory and system-storage diagnostics clear the
suspected hardware. Then require
PostgreSQL readiness, all six databases, successful queries, and a new verified
backup. Finally, merge a reviewed client-unfence revision that removes the
temporary `controllers.<app>.replicas: 0` overrides from the Sonarr, Radarr,
and Prowlarr values. Wait for all three Deployments to become available, then
test an indexer search in Prowlarr, Sonarr, and Radarr. This follows the
[Talos disaster-recovery procedure](https://docs.siderolabs.com/talos/v1.11/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery).

The script is intentionally not parameterized. A future corrupt object needs a
new evidence-backed recovery revision, not broader access to etcd deletion.
