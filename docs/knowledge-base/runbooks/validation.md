# Validation

Tags: #runbooks #validation #rollout

Source: `docs/validation-runbook.md`

## Pre-Mutation Gate

Run the smallest validation that proves the change before live mutation. The
full runbook currently starts with:

```sh
terragrunt hcl fmt
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
cd IaC/live/aws-ssm-parameters
terragrunt plan
cd IaC/live/argocd-apps
terragrunt run --all --filter-affected --parallelism 1 --source-update -- plan -no-color
```

Expected app-registration plans include the Argo CD Application units affected
by `main...HEAD`; unaffected units are skipped by the Terragrunt run queue.
In pull-request CI, the required `Terragrunt Plan` job opens Octelium and runs a
live OpenTofu/Terragrunt plan only when the diff changes `IaC/**`, flake inputs,
OpenTofu/Terragrunt policy inputs, or live-plan helper scripts. Manifest-only,
workflow-only, and docs-only changes still run static checks and rendered
Conftest policies without requiring the CI Kubernetes access path, and the job
replaces the managed PR plan section with an explicit skip note.

## Render And Diff

Render GitOps sources:

```sh
for overlay in clusters/homelab/platform/* clusters/homelab/apps/*; do
  test -f "$overlay/kustomization.yaml" || continue
  kubectl kustomize "$overlay" >/dev/null
done
```

When cluster access exists, use server-side diff for affected app or platform
overlays.

## Secret Scan

```sh
rg -n "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" clusters IaC docs
```

Expected result: only ExternalSecret names, SSM paths, docs references, and
placeholders.

## Readiness Checks

Upstream apps must be registered, synced, and healthy before dependent apps are
considered available. Check `external-secrets`, `cert-manager`, `istio`,
`tailscale`, `argocd-image-updater`, `kiali`, `platform-dns`, and
`platform-storage`.

Octelium app access has a dedicated gate in `scripts/octelium-e2e-check.sh`.
The gate must prove each existing `*.stinkyboi.com` app hostname resolves to an
Octelium private service address and responds through the matching Octelium
published Service. Policy Bot has extra route checks: the Octelium-backed UI
should redirect to auth, the public webhook should return `400` for an unsigned
empty request, and the Funnel root should not route.

Stateful apps wait for `platform-storage`, `nfs-default`, and backup coverage.
Sonarr, Radarr, and Prowlarr also wait for `media-postgres` and Servarr
PostgreSQL fields. n8n also waits for `n8n-postgres`, the
`n8n-postgres-auth` and `n8n-postgres-client` ExternalSecrets, and an
authenticated `n8n` database connection before the app is considered ready.

## Common Stop Conditions

- Missing Application module.
- Terragrunt dependency cycle.
- Existing unmanaged app.
- External DNS failures.
- Missing SSM parameter.
- External Secrets unavailable.
- NFS provisioner missing.
- Media PostgreSQL unavailable.
- Tailscale unavailable.
- Policy Bot webhook unreachable.
- Image updater misconfiguration.
- Argo CD app unhealthy.
