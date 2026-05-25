# Validation Runbook

Run these checks before any live mutation. Record output or a short summary in
the PR.

## Pre-Mutation Checks

```sh
terragrunt hcl fmt
cd IaC/live/aws-ssm-parameters
terragrunt plan
cd IaC/live/argocd-apps
terragrunt run --all plan -no-color
```

Expected result: 14 requested Argo CD Applications plus `platform-storage` are
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
argocd app get argocd-image-updater
argocd app get platform-storage
```

For image automation, confirm the controller and selector CR exist before
adding opt-in labels to any workload Application:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get imageupdater homelab-annotation-opt-in
```

Stateful apps auto-sync by default, but they must not be considered ready until
`platform-storage` is synced, the `nfs-default` StorageClass is verified, and
`docs/storage-nfs.md` records backup coverage.

## Current Validation Record

- Read-only `showmount -e 10.1.0.2` verified the QNAP `/homelab` export is
  allow-listed to the four Talos node IPs.
- Read-only `kubectl get storageclass` returned no resources before the QNAP
  NFS provisioner desired state was added.
- Stateful readiness is blocked until `platform-storage` is synced and a PVC
  write/delete/recreate test passes.
- `terragrunt hcl fmt --check` passed on 2026-05-24.
- Focused `terragrunt --log-disable plan -no-color` passed for
  `IaC/live/argocd-apps/argocd-image-updater` with `1 to add, 0 to change,
  0 to destroy`.
- `kubectl kustomize` passed for every app overlay under
  `clusters/homelab/apps`, for `clusters/homelab/argocd/self-management`, and
  for `clusters/homelab/platform/storage`.
- `helm template` passed for `argocd-image-updater` chart `1.2.2` with
  `clusters/homelab/apps/argocd-image-updater/values.yaml`.
- Repository secret scan found no raw secret material. Matches were expected
  ExternalSecret names, AWS SSM paths, documentation references, and existing
  placeholder environment variable names.
- First-rollout Funnel review found no enabled public Funnel paths; route
  manifests use `homelab.rst.io/public-funnel: "false"`.
- First live rollout on 2026-05-24 applied AWS SSM Parameter Store placeholders
  through `IaC/live/aws-ssm-parameters` and registered Argo CD Applications
  through `IaC/live/argocd-apps`.
- Prometheus disables the `kube-prometheus-stack` node-exporter subchart during
  this rollout because the cluster's baseline Pod Security policy rejects its
  host namespaces, hostPath mounts, and host port `9100`.
- Grafana disables the chart `initChownData` job because the QNAP NFS-backed
  volume rejects root `chown`; the NFS provisioner-created directory permissions
  are used instead.
- The PR-readiness checklist was incomplete when implementation began; the
  operator explicitly waived the checklist gate to continue, and this runbook
  records the resulting validation evidence.

## Failure Modes

| Failure | Operator response |
|---------|-------------------|
| Missing Application module | Stop, fix the local `IaC/modules/argocd-application-kubernetes` module or explicitly document a temporary catalog fallback before applying. |
| Dependency cycle | Stop, remove the cycle from Terragrunt dependencies before applying. |
| Existing unmanaged app | Stop, document adoption or delete/recreate strategy before Argo CD takes ownership. |
| Missing AWS SSM parameter | Create the parameter outside the repo, then re-sync the owning ExternalSecret. |
| External Secrets unavailable | Hold dependent apps until `external-secrets` is synced and healthy. |
| NFS provisioner missing | Restore `platform-storage` readiness first; do not rely on stateful apps until PVC validation passes. |
| Tailscale unavailable | Do not expose tailnet VirtualServices as ready, even if workloads are healthy. |
| Image updater misconfiguration | Remove the opt-in label or annotations from the affected Application, then fix the repository desired state. |
| Argo CD app unhealthy | Record status, operator action, and rollback decision in `docs/argocd-app-onboarding.md`. |
