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

## Render And Validate The Issuer Fix

This checkout does not currently contain `.talos/controlplane.yaml` or
`.talos/talosconfig`. Add or restore those files only through the established
secret-safe Talos config workflow. Do not commit Talos secrets, raw certificate
material, private keys, or kubeconfigs.

When `.talos/controlplane.yaml` is available locally, render a candidate config:

```sh
talosctl machineconfig patch .talos/controlplane.yaml \
  --patch @.talos/patches/controlplane-service-account-issuer.yaml \
  --output /private/tmp/controlplane-service-account-issuer.yaml
```

Validate before any live apply:

```sh
talosctl validate \
  --config /private/tmp/controlplane-service-account-issuer.yaml \
  --mode metal \
  --strict
```

Review the rendered config and confirm the only intended control-plane changes
are:

- `cluster.controlPlane.endpoint: https://10.1.0.199:6443`
- `cluster.apiServer.certSANs` includes `10.1.0.199`
- `cluster.apiServer.extraArgs.service-account-issuer:
  https://10.1.0.199:6443`

## Apply Sequence For Issuer Drift

Do not run these commands until the rendered config has passed validation and
the operator has explicitly approved the live Talos apply sequence.

1. Confirm API and Talos access are healthy with read-only commands:

   ```sh
   kubectl get nodes -o wide
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services
   ```

2. Apply the validated rendered config to the Acer control-plane node:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     apply-config \
     --file /private/tmp/controlplane-service-account-issuer.yaml
   ```

3. Watch the control plane recover:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services

   kubectl get nodes -o wide
   ```

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
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     kubeconfig ~/.kube/config --force

   kubectl config set-cluster homelab --server=https://10.1.0.199:6443
   ```

## Issuer Apply Risks

- A malformed control-plane config can interrupt the only control-plane node.
- If the rendered config accidentally changes cluster secrets, the node can
  lose trust with the existing cluster. Never regenerate secrets for this fix.
- If `certSANs` omits `10.1.0.199`, clients may fail TLS verification after the
  endpoint correction.
- Existing projected service-account tokens minted with the stale issuer may
  continue to exist until they rotate. Verify new discovery state first, then
  restart only workloads that prove they are still using stale projected tokens
  through their normal GitOps path.
- Do not use `talosctl patch machineconfig` or `talosctl edit machineconfig` as
  the durable fix. Those are acceptable only for emergency recovery when the
  final desired state is immediately backfilled into this repository.

## Remote Worker Reboot

When physical access is unavailable and a ZimaBoard needs a restart, use its
authenticated Talos API instead of waiting for a manual power cycle. Reboot
only one exact node at a time:

| Node | Talos address |
| --- | --- |
| `zimaboard-0` | `10.1.0.200` |
| `zimaboard-1` | `10.1.0.201` |
| `zimaboard-2` | `10.1.0.202` |

Confirm Talos still answers, then reboot and require the node plus every
assigned non-terminal pod, including node-pinned workloads, to become ready:

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

talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes "$node_ip" \
  reboot --wait

kubectl wait --for=condition=Ready "node/$node_name" --timeout=10m
kubectl wait --for=condition=Ready pod --all --all-namespaces \
  --field-selector "spec.nodeName=$node_name,status.phase!=Succeeded,status.phase!=Failed" \
  --timeout=10m
```

If either readiness check times out, do not reboot another worker. Inspect the
affected pods with `kubectl get pods -A -o wide --field-selector
"spec.nodeName=$node_name"`, then use the workload's repository-backed recovery
path; do not delete, restart, or patch live pods by hand.

If a normal reboot completes but the node remains stuck and the Talos API still
answers, retry the reboot with `--mode=powercycle`. Never add `--insecure` for
an already configured node. If authenticated Talos access is unavailable,
stop; physical intervention is required.

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
