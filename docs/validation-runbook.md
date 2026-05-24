# Validation Runbook

Run these checks before any live mutation. Record output or a short summary in
the PR.

## Pre-Mutation Checks

```sh
terragrunt hcl fmt
cd IaC/live/argocd-apps
terragrunt run --all plan -no-color
```

Expected result: 13 requested Argo CD Applications plus `platform-storage` are
planned, and every upstream relationship appears in a Terragrunt `dependencies`
block.

Render or dry-run GitOps sources:

```sh
for overlay in clusters/homelab/platform/storage clusters/homelab/apps/*; do
  test -f "$overlay/kustomization.yaml" || continue
  echo "rendering $overlay"
  if ! kubectl kustomize "$overlay" >/dev/null; then
    exit 1
  fi
done
```

When cluster access is available:

```sh
kubectl diff --server-side -k clusters/homelab/platform/storage
kubectl diff --server-side -k clusters/homelab/apps/<app>
```

Secret scan:

```sh
rg -n "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" clusters IaC docs
```

Expected result: only ExternalSecret names, SSM paths, and documentation
references are present.

## Readiness Checks

An upstream app is available only when Argo CD reports it registered, synced,
and healthy:

```sh
argocd app get external-secrets
argocd app get cert-manager
argocd app get istio
argocd app get tailscale
argocd app get platform-storage
```

Stateful apps must not be synced until `platform-storage` is synced, the
`nfs-default` StorageClass is verified, and `docs/storage-nfs.md` records backup
coverage.

## Current Validation Record

- Read-only `showmount -e 10.1.0.2` verified the QNAP `/homelab` export is
  allow-listed to the four Talos node IPs.
- Read-only `kubectl get storageclass` returned no resources before the QNAP
  NFS provisioner desired state was added.
- Stateful rollout is blocked until `platform-storage` is synced and a PVC
  write/delete/recreate test passes.
- `terragrunt hcl fmt` passed on 2026-05-24.
- `terragrunt run --all plan -no-color` from `IaC/live/argocd-apps`
  succeeded for all 14 units and planned one Argo CD Application create per
  unit.
- `kubectl kustomize` passed for every app overlay under
  `clusters/homelab/apps` and for `clusters/homelab/platform/storage`.
- Repository secret scan found no raw secret material. The only matches were
  the LiteLLM `os.environ/OPENAI_API_KEY` placeholder and the documented scan
  command itself.
- First-rollout Funnel review found no enabled public Funnel paths; route
  manifests use `homelab.rst.io/public-funnel: "false"`.
- The PR-readiness checklist was incomplete when implementation began; the
  operator explicitly waived the checklist gate to continue, and this runbook
  records the resulting validation evidence.
- No live mutation was performed.

## Failure Modes

| Failure | Operator response |
|---------|-------------------|
| Missing catalog module | Stop, switch only that app to documented `argocd-application-manifest` fallback or update the catalog in a separate PR. |
| Dependency cycle | Stop, remove the cycle from Terragrunt dependencies before applying. |
| Existing unmanaged app | Stop, document adoption or delete/recreate strategy before Argo CD takes ownership. |
| Missing AWS SSM parameter | Create the parameter outside the repo, then re-sync the owning ExternalSecret. |
| External Secrets unavailable | Hold dependent apps until `external-secrets` is synced and healthy. |
| NFS provisioner missing | Sync only `platform-storage`; keep stateful apps paused until PVC validation passes. |
| Tailscale unavailable | Do not expose tailnet VirtualServices as ready, even if workloads are healthy. |
| Argo CD app unhealthy | Record status, operator action, and rollback decision in `docs/argocd-app-onboarding.md`. |
