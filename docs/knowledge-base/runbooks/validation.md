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
terragrunt run --all plan -no-color
```

Expected app-registration plan currently references 17 requested Argo CD
Applications plus `platform-dns`, `platform-storage`, and `media-postgres`.

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
`tailscale`, `argocd-image-updater`, `platform-dns`, and `platform-storage`.

Policy Bot has extra route checks: the tailnet UI should redirect to auth, the
public webhook should return `400` for an unsigned empty request, and the
Funnel root should not route.

Stateful apps wait for `platform-storage`, `nfs-default`, and backup coverage.
Sonarr, Radarr, and Prowlarr also wait for `media-postgres` and Servarr
PostgreSQL fields.

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
