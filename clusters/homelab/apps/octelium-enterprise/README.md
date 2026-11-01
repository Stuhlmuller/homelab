# Octelium Enterprise GitOps State

This app lets Argo CD own the Kubernetes steady state for the
`octeliumee` Enterprise package after the package has been installed with
`octops install-package`.

The upstream Enterprise package still creates Octelium-native resources and
runtime Secrets. This directory intentionally commits only non-secret
Kubernetes resources that are safe for this public repository:

- `octeliumee-*` Enterprise Deployments and Services.
- Enterprise service-proxy Deployments, Services, and ConfigMaps for
  `console.octelium`, `enterprise.octelium-api`, `public.octelium`, and
  `dirsync.octelium`.
- ServiceAccounts required by Enterprise package components.
- PVC declarations for `octelium-rscstore`, `octelium-logstore`, and
  `octelium-metricstore`, each protected from Argo CD deletion with
  `argocd.argoproj.io/sync-options: Delete=false`.
- A bounded emergency dataplane on `acer` for the control paths, CI API, and
  current public WEB Services while both normal dataplane nodes are NotReady.

`generated-networkpolicies.json` records the ten NetworkPolicy specs created
by the pinned [Enterprise Genesis v0.22.0 constructors](https://github.com/octelium/octelium-ee/tree/0e9368283420e17847879a58dc7f354b656ef3c3/cluster/genesis/genesis/components).
It is a sanitized `--render` input for `scripts/network-policy-inventory.py`,
not a Kustomize resource. A read-only October 20 comparison found all ten
complete specs equal to live policies. These ingress-only policies do not
isolate egress; traffic and enforcement still require a canary review.

Do not commit generated Secrets such as `sys-init-kek`, Octelium database
credentials, license material, or kubeconfigs here. Those remain runtime state
created by Octelium or stored through the existing secret contracts.

The Deployment manifests keep the upstream package security context and probe
shape. Checkov exceptions are scoped per Deployment for that adoption boundary;
change them only after validating the new runtime constraints against the
Enterprise package.

The `octeliumee-logstore`, `octeliumee-metricstore`, and
`octeliumee-rscstore` Deployments intentionally use `Recreate` instead of a
rolling update. Each process opens a DuckDB-backed `store.db` on its PVC, so a
second pod against the same volume can fail on the single-writer lock while the
old pod is still terminating. Keep `rollingUpdate` absent when refreshing
package captures; the deployed stores already use `Recreate`.

The resource-store PVC retains private recovery artifacts. Startup runs only
the store process; historical WAL quarantine files are never replayed or
removed automatically. Preserve them until a reviewed recovery-retention
change establishes they are no longer needed.

## Dormant resource-store capture stage

The active app includes only `capture-stage/inspector.yaml`; the
`capture-stage` fence component remains excluded and the resource-store
Deployment stays at one replica. Verify the pinned Harbor mirror image pulls,
the Pod schedules and reaches Ready, and both read-only mount fields are live.
The liveness probe checks the mounted directory; readiness checks that
`store.db` exists and is readable. The proposed UID/GID 0 matches the upstream
store's root behavior, but source PVC ownership and modes must be checked before
activation. Retain root only if complete file access requires it; otherwise
revise the inspector and capture guard to a proven nonroot UID. A successful
readiness probe covers `store.db`; the full tar capture must still read every
PVC entry. Only a later reviewed fence stage adds `capture-stage` as a
Kustomize component; its patch sets only `octeliumee-rscstore` to zero replicas. The inspector mounts
the exact `octelium-rscstore` claim read-only at the volume and container mount,
has no API token, credentials, or writable image root, and is not selected by
the resource-store Service. This image digest is declared in
`clusters/homelab/platform/image-policy/images.json` and used by existing
Harbor-backed workloads; the inspector's own live pull is still an activation
gate. `imagePullPolicy: Always` requires a Harbor registry check even if the
image layers are cached. Merging this inspector stage alone must not stop or
restart the store. The capture helper requires the exact fence revision Synced
in Argo CD and a
complete namespaced PodList showing zero other PVC mount users. Removal and
restart require a later reviewed change; this stage does
not quarantine the WAL, replay it, or resume the Deployment.

The fenced Kustomization must retain both the inspector Pod and its exact-label
`capture-stage/inspector-networkpolicy.yaml` resource. The capture helper
requires the live Application's single `spec.sources` entry and matching
`status.sync.revisions` entry for this repository, path, and exact `main` SHA;
it rejects a missing policy or ambiguous source/revision list.

Before this stage syncs, privately record the writer Deployment and Pod output
below. Repeat after sync; require the same writer Pod UID and restart count,
one ready replica, and the same Deployment generation. Keep a read-only
Deployment watch open through sync; its ready count must not drop. Stop if any
check differs.

```sh
kubectl -n octelium get deployment octeliumee-rscstore -o json |
  jq -r '[.metadata.uid, .metadata.generation, .spec.replicas, (.status.readyReplicas // 0)] | @tsv'
kubectl -n octelium get pod -l octelium.com/component=rscstore -o json |
  jq -r '.items[] | [.metadata.uid, .spec.nodeName, .status.phase, ([.status.containerStatuses[]?.restartCount] | add // 0)] | @tsv'
kubectl -n octelium get deployment octeliumee-rscstore -w
```

After sync, require the Application to be Synced and Healthy at the exact
merged `main` SHA, one inspector Pod Ready on the writer's node, a nonempty
image ID for the pinned Harbor reference, and `Pulling`/`Pulled` events for
that reference. Both Pod mount fields must be `true`, the claim must be
`octelium-rscstore`, and `/proc/mounts` must report `ro` for `/source`.
Readiness proves access to `store.db`, not readability of every PVC entry.

```sh
kubectl -n argocd get application octelium-enterprise -o json |
  jq -r '[.status.sync.revision, .status.sync.status, .status.health.status] | @tsv'
kubectl -n octelium get pod octelium-rscstore-capture-inspector -o json |
  jq -r '[.metadata.uid, .spec.nodeName, .status.phase, (.status.containerStatuses[0].ready // false), .spec.containers[0].image, (.status.containerStatuses[0].imageID // ""), .spec.containers[0].volumeMounts[0].readOnly, .spec.volumes[0].persistentVolumeClaim.readOnly, .spec.volumes[0].persistentVolumeClaim.claimName] | @tsv'
kubectl -n octelium describe pod octelium-rscstore-capture-inspector
kubectl -n octelium exec pod/octelium-rscstore-capture-inspector -c inspection -- \
  sh -c 'grep " /source " /proc/mounts'
```

If pull, scheduling, mount, readiness, or writer continuity fails, revert the
inspector-stage commit through a reviewed PR. The Application's automated
prune removes the inspector after the rollback SHA syncs; verify it is absent
and the retained PVC is still Bound. Do not add the fence component or run
capture while this gate fails. The capture helper itself rejects this
inspector-only Kustomization because its fence component is absent.

After activation, privately record the live PVC UID, bound PV name and UID,
the exact merged `main` SHA, and the intended kubectl context. The capture
helper requires those identities, a settled zero-replica Deployment, no other
Pod mounting the claim, and the pinned, ready inspector. It also requires an
explicit private Talos config and authenticated `talosctl` v1.11.3. At every
checkpoint it verifies all four expected nodes are Ready with leases renewed
within 30 seconds, reads each kubelet's desired and CRI Pod lists, and reads
each node's Talos Kubernetes container inventory. Any stale PVC mount,
orphaned Octelium Pod, resource-store container or sandbox, unreachable node,
or changed node boot ID fails closed. The inspector must run on the single node
with the declared control-plane selector label, currently `zimaboard-1`; the
receipt records all node boot IDs. Its exact UID must appear in both kubelet
views; the kubelet container ID must match the API, and Talos must show exactly
one current inspector sandbox and running container whose 12-hex ID matches
the API container ID prefix. Old or duplicate
same-name runtime rows block capture.
This catches a former writer that disappeared from the API while its node
kept running. It streams a tar of
the entire PVC root three times: before, archive, after. All three byte counts
and SHA-256 values must match. The archive includes the active WAL, dated
quarantines, and recovery markers present on the claim; its private receipt
records their names and hashes. Missing `store.db`, unsupported file types,
changed identities, main advancing during capture, or changed bytes fail
closed. The helper rechecks current `main`, Argo sync, and the stopped writer
immediately before issuing its receipt. Private partials remain for
inspection and cannot enter the publisher as a completed timestamp directory.

Use a pre-existing, owned mode-0700 directory on durable **local off-NAS**
storage with five times the archive size plus 64 MiB free. Do not use a Git
checkout, temporary directory, NFS, or SMB mount. The two archive parts are
each at most 5 GiB for S3 `PutObject`; the complete tar is bounded at 10 GiB.
The 5000 Mi PVC request is not a file-system quota, so an oversized archive
stops for a separately reviewed multipart path.

```sh
python3 -I scripts/octelium-rscstore-capture.py capture \
  --context '<reviewed-homelab-context>' \
  --talosconfig /private/operator/talosconfig \
  --expected-sha '<exact-merged-main-sha>' \
  --expected-pvc-uid '<live-pvc-uid>' --expected-pv-uid '<live-pv-uid>' \
  --workspace /private/durable-off-nas/rscstore
python3 -I scripts/application-backup.py prepare \
  --app octelium-rscstore --workspace /private/durable-off-nas/rscstore \
  --source /private/durable-off-nas/rscstore/<capture-timestamp>
python3 -I scripts/application-backup.py publish \
  --app octelium-rscstore --workspace /private/durable-off-nas/rscstore \
  --id '<prepared-id>' --aws-cli '<absolute-aws-cli-path>' \
  --profile application-backup
python3 -I scripts/octelium-rscstore-capture.py prove-retrieval \
  --workspace /private/durable-off-nas/rscstore --id '<prepared-id>' \
  --aws-cli '<absolute-aws-cli-path>' --profile application-backup-reader \
  --proof /private/durable-off-nas/rscstore/<new-proof-directory>
```

The existing application-backup publisher conditionally creates each object
in the committed versioned S3 bucket, reads each exact version back, and writes
a versioned `complete.json` marker last. Its rscstore allowlist requires both
archive parts and `capture.json`; it verifies the complete-PVC receipt and
three matching hashes. The proof command itself retrieves a fresh set from S3
through the publisher, then records the marker and object version IDs and
rehashes files restored into a separate directory. A locally fabricated
`complete.json` or `retrieval.json` cannot start a proof.
The publisher and reader policy examples include only the new rscstore prefix;
their attachment and the operator profile's actual rights remain a separate
activation check. A failed S3 upload or retrieval leaves the writer fenced.
Immediately before publication and any recovery decision, recheck current
`main` against the capture receipt's fence SHA, Argo Synced at that revision,
and zero live resource-store writers; drift requires a new capture and review.
Only that published, retrieved, extracted set qualifies as the off-NAS archive
gate. It does **not** prove DuckDB can reopen the checkpoint/WAL or that Octelium
can serve traffic. Keep the writer fenced and all source files untouched until
a separately reviewed recovery plan establishes those facts.

The resource-store Deployment declares `initContainers: []` and
`Replace=true,ServerSideApply=false` so Argo CD reconciles the complete Pod
template without inheriting the Application's server-side apply mode. Server-side
apply alone retains init containers owned by an earlier field manager, even
when they are absent from the current manifest. Replacement preserves the
Deployment's `Recreate` strategy and existing PVC.

The `svc-console-octelium`, `svc-dirsync-octelium`,
`svc-enterprise-octelium-api`, and `svc-public-octelium` Deployments are
generated service proxies. The committed package capture keeps their images
pinned as `tag@sha256:digest`, but the Octelium controller normalizes those
live Deployments back to tag-only image references. The Argo CD Application
therefore ignores only the `vigil` and `managed` container image fields on
those four Deployments and uses `RespectIgnoreDifferences=true` so self-heal
does not fight the controller-owned values.

`emergency-dataplane.yaml` reuses each existing Octelium Service selector and
runs a uniquely named, digest-pinned fallback Deployment on the primary
Kubernetes network. The recovery manifest includes 18 public WEB proxies.
`default.cordium` and `console.octelium` include their required managed
sidecars; Cordium also gets a bounded writable `/tmp` for its bbolt cache. Do
not add the Multus annotation or a dataplane node label to these temporary
Pods. If Octelium recreates a Service, refresh its generated
`octelium.com/svc-uid` here before relying on the fallback.

Keep this recovery file until a correctly sized native dataplane worker has
run the full package-managed fleet for 24 hours. Follow the direct native Pod
probe and public end-to-end removal gate in
`openwiki/architecture/cluster-topology.md`; Service-level probes
alone can be satisfied by these emergency replicas.

## Updating

Use `scripts/octelium-enterprise-package.sh --upgrade` first when changing the
Enterprise package version. After the package settles, refresh
`resources.yaml` from the healthy live resources, scrub generated metadata, pin
images as `tag@sha256:digest`, preserve `Recreate` on the three store Deployments,
omit `rollingUpdate`, keep `initContainers: []` and
`Replace=true,ServerSideApply=false` on the resource store, preserve
the Argo image ignore rule for the four generated service proxy Deployments,
and re-run validation.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-enterprise
kubectl -n octelium get deploy,pod,svc,pvc -l octelium.com/app=octeliumee
scripts/octelium-e2e-check.sh
```
