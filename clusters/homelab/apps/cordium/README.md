<!-- markdownlint-disable MD013 -->

# Cordium

Cordium is bootstrapped into the self-hosted Octelium Cluster with the upstream
`cordium-genesis` component. The `cordium` Argo CD Application first converges
the network, secret, and host prerequisites, then creates the
`cordium-bootstrap` child Application at Sync wave 1. The child runs the
version-pinned genesis hook from the same reviewed desired-state path.

The deployed runtime is split intentionally:

- Human access uses the Octelium `homelab-cordium-user` HUMAN identity and the
  package-managed `default.cordium` WEB Service at
  `https://cordium.stinkyboi.com`, scoped by the dedicated User-attached
  `homelab-cordium-user-access` policy.
- Agent access uses the Octelium `homelab-cordium-agent` WORKLOAD identity and
  a credential policy restricted to Cordium's package-managed
  `default-cordium.octelium-api` `ManagementService`.
- The repo-owned Cordium `ClusterConfig` sends every Workspace PVC to the
  non-default `cordium-local` StorageClass on `zimaboard-1`. A second PostSync
  hook applies that config through Cordium's native API after genesis succeeds.

The hook image is pinned to Cordium `0.12.7`. Upstream genesis creates the
long-running Cordium `nocturne` and `rscserver` Deployments and registers the
`apiserver` and `portal` managed services with Octelium. The image declares the
non-root user by name, so the hook pins `runAsUser: 100` and
`runAsGroup: 65533` to satisfy kubelet's `runAsNonRoot` verification. The
bootstrap service account also needs Kubernetes' `bind` and `escalate` RBAC
verbs because upstream genesis creates privileged ClusterRoles such as
`cordium-nocturne` with permissions the service account does not otherwise hold
directly. The parent does not create `cordium-bootstrap` until its normal Sync
wave is healthy, so a stalled prerequisite cannot create bootstrap privilege.
Creation starts a separate Argo CD operation with a fresh 15-minute timeout.
The child's immediate-health normal resources include only the generated
ClusterConfig and the narrowly scoped cleanup identity. It then creates the
privileged ServiceAccount, ClusterRole, and ClusterRoleBinding as PostSync wave
-1 hooks immediately before genesis at wave 0. Genesis has a 12-minute Job
deadline, leaving three minutes for cleanup within that child operation. The
same cleanup Job runs at PostSync wave 1 after success and as a SyncFail hook
after failure, deleting only those three `cordium-genesis` resources. Its
persistent cleanup Role and ClusterRole can only `delete` resources named
`cordium-genesis`; they cannot create, bind, or escalate RBAC. An ordinary
failed child sync runs the cleanup and removes the identity. In-operation
retries are disabled because Argo CD keeps their original timeout start; the
next new full `cordium-bootstrap` sync gets a fresh 15-minute budget and
recreates the identity at PostSync wave -1.
Do not use selective sync because Argo CD does not run hooks during selective
sync. Generated Octelium/Cordium runtime resources remain owned by Octelium
controllers.

Cordium-generated Workspace Pods run as privileged root containers with an
unconfined AppArmor profile. The repo-owned `cordium` Namespace therefore
enforces the `privileged` Pod Security profile while continuing to audit and
warn against `restricted`. Keep this exception limited to Cordium Workspaces;
ordinary homelab workloads must not use this Namespace.

Workspace Pods select `octelium.com/node-mode-cordium=`. Terragrunt manages
that label on `zimaboard-1`, the lower-reserved-capacity 8 GB worker; the
smaller `zimaboard-2` cannot satisfy the default Workspace memory limit.
Workspace storage is also pinned there under `/var/lib/cordium-workspaces`.
It is disposable node-local data with no replication or backup. Existing
Workspace PVCs keep their original StorageClass; recreate a failed Workspace
after applying the ClusterConfig.

Cordium runs rootless Podman inside each privileged Workspace Pod. Apply the
repo-owned `.talos/patches/worker-cordium-user-namespaces.yaml` patch only to
`zimaboard-1`; Talos otherwise reports `user.max_user_namespaces=0`, and new
Workspaces fail during startup with `cannot clone: No space left on device`.
The repo-owned `cordium-user-namespace-sysctl` DaemonSet applies the same value
through a short-lived root init container whose only host access is the single
sysctl file and reports the current value through an unprivileged readiness
check. The init container reapplies the value whenever GitOps or a node reboot
recreates the Pod, while the Talos patch remains the machine-config source of
truth.
These direct-IP Talos operations require a homelab LAN route or the retained
Tailscale fallback. A Cordium Workspace's Octelium session does not expose the
Talos API or arbitrary LAN addresses. Render the complete worker config,
validate it, and apply that reviewed config:

```sh
talosctl machineconfig patch .talos/worker.yaml \
  --patch @.talos/patches/worker-zimaboard-1.yaml \
  --patch @.talos/patches/worker-cordium-user-namespaces.yaml \
  --output /private/tmp/worker-zimaboard-1-cordium.yaml
talosctl validate \
  --config /private/tmp/worker-zimaboard-1-cordium.yaml \
  --mode metal \
  --strict
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.201 \
  apply-config \
  --file /private/tmp/worker-zimaboard-1-cordium.yaml
```

Before applying, confirm the rendered config still names `zimaboard-1` and uses
`10.1.0.201/24`; applying the base `zimaboard-0` identity would create a node
name and address collision.

Cordium genesis owns the system Service `default.cordium`, whose primary
hostname is `cordium`. The homelab catalog must not also declare a `cordium`
Service in Octelium's default Namespace: both names derive the same public
hostname, causing the Octelium ingress to reject the entire updated routing
snapshot. The catalog keeps authorization narrow by attaching
`homelab-cordium-user-access` to the repo-owned `homelab-cordium-user`; the
policy also matches that exact User, and it does not modify the system-owned
Service or Namespace.

## Activation

Apply the Octelium service catalog after the PR merges:

```sh
octeliumctl apply --domain stinkyboi.com docs/examples/octelium/homelab-services.yaml
```

When upgrading a Cluster that previously applied the repo-defined `cordium`
Service, remove only that obsolete non-system duplicate after the updated
Policy and User have applied:

```sh
if octeliumctl get service cordium.default --domain stinkyboi.com >/dev/null 2>&1; then
  octeliumctl delete service cordium.default --domain stinkyboi.com
fi
```

Do not use `octeliumctl apply --prune` with this catalog. Pruning would also
remove unrelated non-system Octelium resources that are not declared in this
single file.

Argo CD then syncs `cordium`; after its prerequisites are healthy, the tracked
child Application starts a separate `cordium-bootstrap` sync and runs genesis.
If the hook needs to be rerun after a Cordium upgrade or bootstrap RBAC change,
bump `homelab.rst.io/cordium-genesis-revision` on both the Job template and the
tracked `cordium-genesis-cleanup` ServiceAccount. The tracked annotation starts
a full child sync; that sync recreates the temporary bootstrap identity
immediately before genesis and retires it after success or failure.

When the ClusterConfig payload changes, bump
`homelab.rst.io/cordium-cluster-config-revision` in
`../cordium-bootstrap/kustomization.yaml`. That changes the tracked ConfigMap
metadata and starts a full child sync. Argo CD reruns genesis before applying
ClusterConfig because selective sync does not execute hooks.

Create the policy-bound agent credential and store it in
`/homelab/cordium/agent-auth-token` before applying the stack:

```sh
octeliumctl create cred \
  --user homelab-cordium-agent \
  --policy homelab-cordium-agent-api-access \
  homelab-cordium-agent
```

The production apply adopts that pre-populated parameter into OpenTofu state
instead of replacing it with the declared placeholder.
The ExternalSecret polls the current SSM token every five minutes, so replacing
the initial placeholder does not require a manifest annotation bump. Argo CD
runs genesis at PostSync wave 0, then applies `cluster-config.yaml` and retires
the genesis identity at wave 1; no manual `cordium man apply` step is needed.
Do not reuse a human browser session token for agent automation.
Developer shell access should enter through `https://cordium.stinkyboi.com`
and workspace subdomains under `*.cordium.stinkyboi.com`; do not bypass the
Octelium-backed Cordium route with a direct Service, port-forward, or
Tailscale-only URL.

## Private Kubernetes Access

Start a named developer Workspace from the clean reviewed commit. Evidence runs
must omit `--rm` so results can be exported before Workspace deletion:

```sh
reviewed_commit="$(git rev-parse HEAD)"
boundary_workspace="octelium-boundary-$(date -u +%Y%m%d%H%M%S)"
cordium run "$boundary_workspace" --domain stinkyboi.com \
  --repository https://github.com/Stuhlmuller/homelab.git \
  --checkout "$reviewed_commit"
```

Cordium starts a dedicated Octelium client session for the Workspace owner.
Inside the Workspace, generate a read-only client kubeconfig for the private
Service:

```sh
octelium config kubernetes-api.homelab --domain stinkyboi.com
```

Run the `KUBECONFIG` export printed by that command, set the generated file to
mode `0600`, then request only an explicit namespace. The upstream kubeconfig
remains in the Octelium gateway Secret; the Workspace receives no long-lived
Kubernetes credential and does not need a Tailscale route. The policy permits
namespace-scoped `get`, `list`, and `watch` for core Events, Pods, and Services;
apps/v1 DaemonSets, Deployments, ReplicaSets, and StatefulSets; and batch/v1
CronJobs and Jobs. It permits only the matching five discovery endpoints.

```sh
chmod 0600 "$KUBECONFIG"
cordium_evidence="${TMPDIR:-/tmp}/octelium-cordium-boundary-evidence"
scripts/octelium-kubernetes-boundary-e2e.sh \
  --role cordium \
  --kubeconfig "$KUBECONFIG" \
  --evidence-dir "$cordium_evidence"
```

First require `scripts/octelium-e2e-check.sh` at this exact commit to report
that the live private Kubernetes Policy matches the repository catalog. The
live boundary script then requires the exact `homelab-cordium-user`
HUMAN/CLIENT identity, the exact v0.35 private Service server, placeholder user,
and context. It
rejects a dirty checkout, alternate credentials, kubeconfig proxies, and TLS
bypass before Kubernetes requests. Every Octelium/kubectl proof child removes
inherited upper- and lower-case HTTP, HTTPS, and ALL proxies. Its bounded status
preflight uses child-only container mode so a missing or expired session cannot
launch browser login; an existing database session may refresh its token. The
policy permits allowlisted reads in any one explicit namespace and denies
all-namespaces reads. The script accepts only kubectl's exact v0.35 rendering
`Error from server (Forbidden): Octelium: Unauthorized request`; denied response
bodies are discarded. Private metadata records exact script and catalog
SHA-256 digests.

Exit without deleting the Workspace. Use Cordium 0.12.7's native copy path to
export and verify the evidence before deletion:

```sh
workspace_tmp="$(cordium exec "$boundary_workspace" --domain stinkyboi.com -- \
  sh -c 'printf %s "${TMPDIR:-/tmp}"')"
encrypted_evidence="/ABSOLUTE/PATH/ON/ENCRYPTED-STORAGE/$boundary_workspace"
mkdir -m 0700 "$encrypted_evidence"
cordium cp -r --domain stinkyboi.com \
  "$boundary_workspace:$workspace_tmp/octelium-cordium-boundary-evidence/" \
  "$encrypted_evidence/"
test -s "$encrypted_evidence/metadata.tsv" &&
  test -s "$encrypted_evidence/summary.tsv" &&
  test -s "$encrypted_evidence/identity.json" &&
  test -s "$encrypted_evidence/kubeconfig.json" &&
  grep -Eq '^script_sha256\t[0-9a-f]{64}$' "$encrypted_evidence/metadata.tsv" &&
  grep -Eq '^catalog_sha256\t[0-9a-f]{64}$' "$encrypted_evidence/metadata.tsv" &&
  ! grep -q $'\tFAIL\t' "$encrypted_evidence/summary.tsv" &&
  cordium delete workspace "$boundary_workspace" --domain stinkyboi.com
```

Run the separate `owner` role from the operator workstation at the same catalog
revision. Keep both evidence directories outside the checkout on private
encrypted storage; never upload them to GitHub or Actions. The full operator
procedure and rollback are in `docs/octelium.md`. Catalog equality and the
jq/CEL fixture are prerequisites and drift checks, not enforcement proof.

## Validation

```sh
kubectl -n argocd get application cordium cordium-bootstrap
kubectl -n argocd get application cordium-bootstrap \
  -o jsonpath='{.status.operationState.phase}{"\n"}'
kubectl -n octelium get serviceaccount cordium-genesis
kubectl get clusterrole/cordium-genesis clusterrolebinding/cordium-genesis
kubectl auth can-i \
  --as=system:serviceaccount:octelium:cordium-genesis \
  create clusterrolebindings
kubectl -n octelium get deploy,svc -l octelium.com/app=cordium
kubectl get namespace cordium --show-labels
kubectl get node zimaboard-1 --show-labels
kubectl get storageclass cordium-local
kubectl -n cordium rollout status daemonset/cordium-user-namespace-sysctl
kubectl -n cordium get deploy,pod,pvc
kubectl -n cordium exec deploy/ws-WORKSPACE -- \
  cat /proc/sys/user/max_user_namespaces
cordium man get clusterconfig -o yaml
octeliumctl get svc default.cordium
octeliumctl get svc default-cordium.octelium-api
octeliumctl get svc kubernetes-api.homelab
curl -I https://cordium.stinkyboi.com
```

Successful hook Jobs are deleted by `HookSucceeded`; the child Application's
operation state is the durable success record. During an active or failed run,
inspect the remaining Jobs and logs:

```sh
kubectl -n octelium get job -l app.kubernetes.io/name=cordium
kubectl -n octelium logs job/cordium-genesis
kubectl -n octelium logs job/cordium-cluster-config
kubectl -n octelium logs job/cordium-genesis-cleanup
```

After a successful full child sync, or a failed sync whose SyncFail cleanup
completed, the two `get` commands for the bootstrap identity must return
`NotFound`, and the authorization check must print `no`. If control-plane or
scheduler failure also prevented cleanup, recover it, inspect these resources,
and start a full `cordium-bootstrap` sync. The cleanup is idempotent, and the
new sync recreates the identity only immediately before genesis.

Verify the human developer path end to end with the named Workspace retained
above:

```sh
cordium run "$boundary_workspace" --domain stinkyboi.com
```

In the resulting Workspace terminal, confirm the clone and then exit:

```sh
git -C /workspace/repo remote get-url origin
octelium config kubernetes-api.homelab --domain stinkyboi.com
# Export the KUBECONFIG path printed above.
chmod 0600 "$KUBECONFIG"
kubectl --request-timeout=15s -n cordium get pods
exit
```

The remote URL must be `https://github.com/Stuhlmuller/homelab.git`. Export and
verify private evidence before deleting the named Workspace; use the earlier
cluster-side PVC check to validate `cordium-local`.

The expected steady state includes ready Cordium controller pods in the
`octelium` namespace, running Workspace Pods in the privileged `cordium`
namespace, and an Octelium-protected browser route for
`cordium.stinkyboi.com` plus workspace app subdomains under
`*.cordium.stinkyboi.com`.

## Rollback

If the Kubernetes read boundary rejects a required diagnostic, remove the two
Cordium `ALLOW` rules from the repository catalog while retaining
`operator-client`, then apply that reviewed catalog. This disables Workspace
Kubernetes access without weakening owner access. Never restore a denylist.

Remove `cordium-bootstrap-application.yaml` from the parent Kustomization and
sync `cordium` before deleting the parent Application. The child has Argo CD's
foreground resources finalizer, so this declarative removal cascades all
tracked bootstrap resources instead of orphaning the privileged identity.
Verify the identity is `NotFound`, then remove the Octelium catalog entries for
`homelab-cordium-user` and
`homelab-cordium-agent` if the platform is being retired.

Removing `cordium-local-path-provisioner` stops new local provisioning but does
not migrate existing Workspace data. Stop and delete disposable Workspaces
before removing the StorageClass or its node-local directories.

After Cordium is retired, remove `user-namespace-sysctl.yaml` from the Cordium
Kustomization and let Argo CD prune the tracked DaemonSet, then restore Talos'
disabled user-namespace default on `zimaboard-1` through the same reviewed
worker-config path. A node reboot restores Talos' default after the DaemonSet
is gone:

```sh
talosctl machineconfig patch .talos/worker.yaml \
  --patch @.talos/patches/worker-zimaboard-1.yaml \
  --patch @.talos/patches/worker-cordium-user-namespaces-rollback.yaml \
  --output /private/tmp/worker-zimaboard-1-cordium-rollback.yaml
talosctl validate \
  --config /private/tmp/worker-zimaboard-1-cordium-rollback.yaml \
  --mode metal \
  --strict
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.201 \
  apply-config \
  --file /private/tmp/worker-zimaboard-1-cordium-rollback.yaml
talosctl --talosconfig .talos/talosconfig \
  --endpoints 10.1.0.199 \
  --nodes 10.1.0.201 \
  read /proc/sys/user/max_user_namespaces
```

The final command must print `0`.
