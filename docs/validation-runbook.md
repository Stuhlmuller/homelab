# Validation Runbook

Run these checks before any live mutation. Record output or a short summary in
the PR.

GitHub Actions now runs the same validation path for pull requests and
post-merge applies. See `docs/ci-cd.md` for required GitHub environment
secrets, Octelium CI identity setup, and AWS OIDC role boundaries.

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

For Kiali, verify the operator-created custom resource and Octelium-backed UI:

```sh
kubectl -n monitoring get kiali kiali
kubectl -n monitoring get deploy,svc kiali
curl -I https://kiali.stinkyboi.com
```

Expected result: the Kiali Application is synced and healthy, the Kiali custom
resource is successfully reconciled, and the `kiali.stinkyboi.com` hostname
reaches the read-only UI through Octelium.

For Octelium app-access readiness, run the e2e gate before declaring app UI
access healthy:

```sh
scripts/octelium-e2e-check.sh
```

Use `--octelium-context <octelium-cluster-context>` and
`--homelab-context <homelab-context>` when those are separate Kubernetes
clusters.

Expected result: the Octelium control plane exists, `octelium-client` has a
ready replica, the Cluster/API/portal hostnames are serving Octelium instead of
generic Istio 404 responses, every homelab app Service is present in the
Octelium catalog, each existing `*.stinkyboi.com` app hostname resolves
publicly through Cloudflare into the `octelium-public` tunnel, and each app
responds over HTTPS through its matching Octelium published service with the
real URL and SNI preserved. The gate also probes the reviewed public callback
hosts. If any probe fails, the gate should print one or more `FAIL:` lines and
exit nonzero; a quiet early exit is a validation harness bug.

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
kubectl -n automation get deploy/policy-bot svc/policy-bot virtualservice/policy-bot-octelium virtualservice/policy-bot-webhook-octelium externalsecret/policy-bot-config
kubectl -n octelium-public get deploy cloudflared
curl -I https://policy-bot.stinkyboi.com/
curl -I https://policy-bot.stinkyboi.com/details/example/example/1
curl -sS -o /dev/null -w '%{http_code}\n' https://policy-bot-hook.stinkyboi.com/api/github/hook
```

Expected result: the internal host serves normal Policy Bot UI routes, details
redirect to `/api/github/auth`, the public hook returns `400` for an unsigned
empty request, and the callback root is not routed.

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

For Radarr access lockout checks, validate that the auth-normalized
`config.xml` contains exactly one `AuthenticationMethod=External` entry and
one `AuthenticationRequired=DisabledForLocalAddresses` entry, with no
`AuthenticationEnabled` or `AuthenticationType` entries. Also verify the UI
bootstrap endpoint returns success while discarding the response body:

```sh
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'grep -nE "<Authentication(Enabled|Method|Required|Type)>" /config/config.xml || true'
kubectl -n media exec deploy/radarr -c app -- \
  sh -c 'curl -fsS -o /dev/null http://127.0.0.1:7878/initialize.json'
```

Do not print `/initialize.json`; it contains the live Radarr API key. A bare
`/api/v3/...` request without that key may still return `401` and is not, by
itself, a lockout signal.

n8n must also wait for `n8n-postgres` to sync and become healthy. Verify the
`n8n-postgres-auth` and `n8n-postgres-client` ExternalSecrets, the StatefulSet,
the PVC, and an authenticated connection to the `n8n` database documented in
`clusters/homelab/apps/n8n-postgres/README.md` before treating n8n as migrated
to PostgreSQL.

n8n startup probes use `/healthz`, while readiness and liveness use the
database-aware `/healthz/readiness` endpoint. This distinction lets migrations
finish during startup but replaces an n8n process whose PostgreSQL connection
pool stays closed after a database interruption. A pod that is Ready while
`/healthz/readiness` returns HTTP 503 is running stale probe configuration.

n8n webhooks use the reviewed Octelium-public callback route at
`https://n8n-webhook.stinkyboi.com`. After sync, verify the callback
VirtualService and `octelium-public` tunnel exist, then check that the
Octelium-backed editor host works and the public host only reaches n8n under
webhook path prefixes:

```sh
kubectl -n automation get virtualservice n8n-webhook-octelium
kubectl -n octelium-public get deploy cloudflared
kubectl -n automation exec deploy/n8n -c app -- \
  node -e 'fetch("http://127.0.0.1:5678/healthz/readiness").then((response) => console.log(response.status))'
curl -I https://n8n.stinkyboi.com/
curl -sS -D /tmp/n8n-webhook-headers.txt -o /tmp/n8n-webhook-body.txt -w '%{http_code}\n' https://n8n-webhook.stinkyboi.com/webhook/__missing__
grep -i webhook /tmp/n8n-webhook-body.txt
```

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
- First-rollout Funnel review found no enabled public Funnel paths. Current
  rendered policy rejects Tailscale Funnel; reviewed external callbacks must
  use Octelium-public first-level hostnames with
  `homelab.rst.io/public-callback-reviewed: "true"` and be documented in
  `docs/networking-tailnet-ingress.md`.
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
| External DNS lookup failures from pods | Verify `platform-dns` is synced and CoreDNS forwards through `1.1.1.1` and `1.0.0.1`; confirm the upstream answer is not a sinkhole response such as `0.0.0.0`; do not manually patch the live CoreDNS `ConfigMap`. |
| Missing AWS SSM parameter | Create the parameter outside the repo, then re-sync the owning ExternalSecret. |
| External Secrets unavailable | Hold dependent apps until `external-secrets` is synced and healthy. |
| NFS provisioner missing | Restore `platform-storage` readiness first; do not rely on stateful apps until PVC validation passes. |
| Media PostgreSQL unavailable | Hold Sonarr, Radarr, and Prowlarr; verify `media-postgres-auth`, `media-postgres-arr-env`, the StatefulSet, and the six logical databases before app sync. |
| Tailscale unavailable | Do not mark secondary LAN/egress as ready, but app, callback, CI, and VPN readiness should be evaluated through Octelium. |
| Policy Bot webhook unreachable | Inspect the `policy-bot-webhook-octelium` VirtualService, `octelium-public` tunnel logs, DNS CNAME, and Policy Bot webhook HMAC handling; do not expose additional Funnel routes. |
| n8n webhook unreachable | Inspect the `n8n-webhook-octelium` VirtualService, `octelium-public` tunnel logs, DNS CNAME, and n8n webhook path config; keep editor/API routes off the callback host. |
| Image updater misconfiguration | Remove the affected `applicationRefs` image entry or write-back target from `clusters/homelab/apps/argocd-image-updater/imageupdater.yaml`, then fix the repository desired state. |
| Argo CD app unhealthy | Record status, operator action, and rollback decision in `docs/argocd-app-onboarding.md`. |
