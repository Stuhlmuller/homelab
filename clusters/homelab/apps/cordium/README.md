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
  the `cordium-agent-api.homelab` gRPC Service for automation.
- Workspace defaults stay with upstream Cordium until this repository adds a
  reviewed Cordium-native workspace configuration resource.

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

Create a workload credential for automation after the `homelab-cordium-agent`
User exists:

```sh
octeliumctl create cred \
  --user homelab-cordium-agent \
  --policy homelab-cordium-agent-api-access \
  homelab-cordium-agent
```

Store that token outside git wherever the caller that drives agent workspaces
expects it. Do not reuse a human browser session token for agent automation.
Developer shell access should enter through `https://cordium.stinkyboi.com`
and workspace subdomains under `*.cordium.stinkyboi.com`; do not bypass the
Octelium-backed Cordium route with a direct Service, port-forward, or
Tailscale-only URL.

## Validation

```sh
kubectl -n octelium get job cordium-genesis
kubectl -n octelium logs job/cordium-genesis
kubectl -n octelium get deploy,svc -l octelium.com/app=cordium
octeliumctl get svc default.cordium
octeliumctl get svc cordium-agent-api.homelab
curl -I https://cordium.stinkyboi.com
```

The expected steady state includes ready Cordium controller pods in the
`octelium` namespace and an Octelium-protected browser route for
`cordium.stinkyboi.com` plus workspace app subdomains under
`*.cordium.stinkyboi.com`.

## Rollback

Disable or delete the `cordium` Argo CD Application first so the hook does not
recreate its package-managed `default.cordium` Service. Then remove the
Octelium catalog entries for `cordium-agent-api.homelab`,
`homelab-cordium-user`, and
`homelab-cordium-agent` if the platform is being retired.
