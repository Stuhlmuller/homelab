<!-- markdownlint-disable MD013 -->

# Cordium

Cordium is bootstrapped into the self-hosted Octelium Cluster with the upstream
`cordium-genesis` component. The Argo CD app runs the genesis command as a
version-pinned sync hook so the Cordium controllers and managed services are
created from the same reviewed desired-state path as the rest of the homelab.

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
directly. Keep those verbs scoped to this hook instead of granting broad
privileges to long-running workloads. The Argo CD app keeps the hook and RBAC
visible in git; the generated Octelium/Cordium runtime resources remain owned
by Octelium controllers.

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

Argo CD then syncs the `cordium` Application and runs the genesis hook. If the
hook needs to be rerun after a Cordium upgrade or bootstrap RBAC change, bump
`homelab.rst.io/cordium-genesis-revision` on the Job template.

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
runs genesis at sync wave 0, then applies
`cluster-config.yaml` at wave 1; no manual `cordium man apply` step is needed.
Do not reuse a human browser session token for agent automation.
Developer shell access should enter through `https://cordium.stinkyboi.com`
and workspace subdomains under `*.cordium.stinkyboi.com`; do not bypass the
Octelium-backed Cordium route with a direct Service, port-forward, or
Tailscale-only URL.

## Validation

```sh
kubectl -n octelium get job cordium-genesis
kubectl -n octelium logs job/cordium-genesis
kubectl -n octelium get job cordium-cluster-config
kubectl -n octelium logs job/cordium-cluster-config
kubectl -n octelium get deploy,svc -l octelium.com/app=cordium
kubectl get namespace cordium --show-labels
kubectl get node zimaboard-1 --show-labels
kubectl get storageclass cordium-local
kubectl -n cordium get deploy,pod,pvc
cordium man get clusterconfig -o yaml
octeliumctl get svc default.cordium
octeliumctl get svc default-cordium.octelium-api
curl -I https://cordium.stinkyboi.com
```

Verify the human developer path end to end with the public repository:

```sh
cordium run --repository https://github.com/Stuhlmuller/homelab.git
```

In the resulting Workspace terminal, confirm the clone and then exit:

```sh
git -C /workspace/repo remote get-url origin
exit
```

The remote URL must be
`https://github.com/Stuhlmuller/homelab.git`, and the new Workspace PVC must
report `cordium-local` in `kubectl -n cordium get pvc`.

The expected steady state includes ready Cordium controller pods in the
`octelium` namespace, running Workspace Pods in the privileged `cordium`
namespace, and an Octelium-protected browser route for
`cordium.stinkyboi.com` plus workspace app subdomains under
`*.cordium.stinkyboi.com`.

## Rollback

Disable or delete the `cordium` Argo CD Application first so the hook does not
recreate its package-managed Services. Then remove the Octelium catalog entries
for `homelab-cordium-user` and
`homelab-cordium-agent` if the platform is being retired.

Removing `cordium-local-path-provisioner` stops new local provisioning but does
not migrate existing Workspace data. Stop and delete disposable Workspaces
before removing the StorageClass or its node-local directories.
