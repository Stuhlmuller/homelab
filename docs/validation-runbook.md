# Validation Runbook

Run these checks before any live mutation. Record output or a short summary in
the PR.

GitHub Actions now runs the same validation path for pull requests and
post-merge applies. See `docs/ci-cd.md` for required GitHub environment
secrets, Tailscale identity setup, and AWS OIDC role boundaries.

## Pre-Mutation Checks

```sh
terragrunt hcl fmt
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
cd IaC/live/aws-ssm-parameters
terragrunt plan
cd IaC/live/argocd-apps
terragrunt run --all --filter-affected --parallelism 1 --source-update -- plan -no-color
```

Expected result: the Argo CD Application units affected by `main...HEAD` are
planned, their dependencies remain ordered by Terragrunt `dependencies` blocks,
and unaffected units are skipped by the run queue.

Render or dry-run GitOps sources:

```sh
for overlay in clusters/homelab/platform/* clusters/homelab/apps/*; do
  test -f "$overlay/kustomization.yaml" || continue
  echo "rendering $overlay"
  if ! kubectl kustomize "$overlay" >/dev/null; then
    exit 1
  fi
done
```

When cluster access is available:

```sh
kubectl diff --server-side -k clusters/homelab/platform/<service>
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
argocd app get kiali
argocd app get platform-dns
argocd app get platform-storage
```

For Kiali, verify the operator-created custom resource and tailnet UI:

```sh
kubectl -n monitoring get kiali kiali
kubectl -n monitoring get deploy,svc kiali
curl -I https://kiali.stinkyboi.com
```

Expected result: the Kiali Application is synced and healthy, the Kiali custom
resource is successfully reconciled, and the tailnet HTTPS route reaches the
read-only UI.

For image automation, confirm the controller and selector CR exist before
relying on update pull requests:

```sh
kubectl -n argocd get deploy argocd-image-updater-controller
kubectl -n argocd get externalsecret argocd-image-updater-git
kubectl -n argocd get imageupdater homelab-managed-images
```

For Policy Bot, verify the app stays narrow before registering the GitHub App
webhook URL:

```sh
argocd app get policy-bot
kubectl -n automation get deploy,svc,ingress,externalsecret policy-bot policy-bot-hook-funnel policy-bot-config
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=policy-bot-hook-funnel
curl -I https://policy-bot.stinkyboi.com/details/example/example/1
curl -sS -o /dev/null -w '%{http_code}\n' https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook
```

Expected result: details redirect to `/api/github/auth`, the public hook returns
`400` for an unsigned empty request, and the Funnel root is not routed.

Stateful apps auto-sync by default, but they must not be considered ready until
`platform-storage` is synced, the `nfs-default` StorageClass is verified, and
`docs/storage-nfs.md` records backup coverage.

Deluge, Radarr, and Sonarr media-library data is an exception to the default
StorageClass rule: their downloads, movies, and TV library mounts use static
PV/PVC objects backed by the QNAP `/media` export. Before syncing that cutover,
verify `showmount -e 10.1.0.2` lists `/media` for `10.1.0.199` through
`10.1.0.202`, then confirm the `media-downloads-migration`,
`media-movies-migration`, and `media-tv-migration` Jobs complete successfully.

Sonarr, Radarr, and Prowlarr must also wait for `media-postgres` to sync and
become healthy. Verify the ExternalSecrets, StatefulSet, PVC, and logical
databases documented in `clusters/homelab/apps/media-postgres/README.md`
before treating those apps as migrated to PostgreSQL. For each app, also verify
the persistent `/config/config.xml` contains the Servarr-documented
`PostgresUser`, `PostgresPassword`, `PostgresPort`, `PostgresHost`,
`PostgresMainDb`, and `PostgresLogDb` entries before running any SQLite
migration.

## Current Validation Record

- Read-only `showmount -e 10.1.0.2` verified the QNAP `/homelab` export is
  allow-listed to the four Talos node IPs.
- Read-only `showmount -e 10.1.0.2` on 2026-05-26 verified the QNAP `/media`
  export is also allow-listed to the four Talos node IPs.
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
- Prometheus direct tailnet ingress is intentionally absent from desired state;
  Grafana is the reviewed operator-facing metrics UI.
- First live rollout on 2026-05-24 applied AWS SSM Parameter Store placeholders
  through `IaC/live/aws-ssm-parameters` and registered Argo CD Applications
  through `IaC/live/argocd-apps`.
- Prometheus disables the `kube-prometheus-stack` node-exporter subchart during
  this rollout because the cluster's baseline Pod Security policy rejects its
  host namespaces, hostPath mounts, and host port `9100`.
- Grafana disables the chart `initChownData` job because the QNAP NFS-backed
  volume rejects root `chown`; the NFS provisioner-created directory permissions
  are used instead.
- Grafana dashboards, Prometheus and Alertmanager datasources, Grafana metrics
  scraping, and Grafana-managed alert rules are now provisioned from
  `clusters/homelab/apps/grafana`. Validate the kustomize output and Helm chart
  render before relying on those dashboards or alert rules.
- The PR-readiness checklist was incomplete when implementation began; the
  operator explicitly waived the checklist gate to continue, and this runbook
  records the resulting validation evidence.
- Prowlarr desired state was added on 2026-05-24. `terragrunt hcl fmt --check`,
  `terragrunt hcl validate`, `kubectl kustomize clusters/homelab/apps/prowlarr`,
  a full `kubectl kustomize` pass across app and storage overlays,
  `git diff --check`, repository secret scanning, and
  `nix flake check --no-build --all-systems` passed before live rollout.
  Focused Prowlarr Terragrunt initialization and validation use the
  repository-local `IaC/modules/argocd-application-kubernetes` module.
- Kiali desired state was added on 2026-05-26. `terragrunt hcl fmt --check`,
  `terragrunt hcl validate`, `kubectl kustomize clusters/homelab/apps/kiali`,
  `helm template kiali-operator kiali-operator --repo
  https://kiali.org/helm-charts --version 2.26.0 --namespace istio-system -f
  clusters/homelab/apps/kiali/values.yaml`, focused
  `terragrunt --log-disable validate -no-color`, focused
  `terragrunt --log-disable plan -no-color`, `git diff --check`, repository
  secret scanning, and `nix develop --command bash scripts/ci/static-checks.sh`
  passed before any live rollout. The focused Kiali plan showed `1 to add, 0
  to change, 0 to destroy`.

## Failure Modes

| Failure | Operator response |
|---------|-------------------|
| Missing Application module | Stop, fix the local `IaC/modules/argocd-application-kubernetes` module or explicitly document a temporary catalog fallback before applying. |
| Dependency cycle | Stop, remove the cycle from Terragrunt dependencies before applying. |
| Existing unmanaged app | Stop, document adoption or delete/recreate strategy before Argo CD takes ownership. |
| External DNS lookup failures from pods | Verify `platform-dns` is synced and CoreDNS forwards through `1.1.1.3` and `1.0.0.3`; do not manually patch the live CoreDNS `ConfigMap`. |
| Missing AWS SSM parameter | Create the parameter outside the repo, then re-sync the owning ExternalSecret. |
| External Secrets unavailable | Hold dependent apps until `external-secrets` is synced and healthy. |
| NFS provisioner missing | Restore `platform-storage` readiness first; do not rely on stateful apps until PVC validation passes. |
| Media PostgreSQL unavailable | Hold Sonarr, Radarr, and Prowlarr; verify `media-postgres-auth`, `media-postgres-arr-env`, the StatefulSet, and the six logical databases before app sync. |
| Tailscale unavailable | Do not expose tailnet VirtualServices as ready, even if workloads are healthy. |
| Policy Bot webhook unreachable | Confirm the Tailscale `funnel` node attribute for `tag:k8s`, then inspect the `policy-bot-hook-funnel` Ingress and the operator-managed proxy Pod; do not expose additional Policy Bot routes. |
| Image updater misconfiguration | Remove the affected `applicationRefs` image entry or write-back target from `clusters/homelab/apps/argocd-image-updater/imageupdater.yaml`, then fix the repository desired state. |
| Argo CD app unhealthy | Record status, operator action, and rollback decision in `docs/argocd-app-onboarding.md`. |
