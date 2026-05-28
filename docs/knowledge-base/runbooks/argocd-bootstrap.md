# Argo CD Bootstrap

Tags: #runbooks #argocd #bootstrap #terragrunt

Source: `docs/argocd-bootstrap.md`

## Purpose

Bootstrap Argo CD into the Talos cluster using
`IaC/bootstrap/argocd`. The durable path is one reviewed `terragrunt apply`
from that stack. The bootstrap Helm values also enable Argo CD application
controller, repo server, and API server metrics services for Prometheus.

## Preconditions

- Desired state is available on `main`.
- Kubernetes access works through the approved kubeconfig path.
- S3 remote state and KMS credentials are available as credential material.
- No raw tokens, kubeconfigs, Talos secrets, private keys, or certificate
  material are committed.
- AWS SSM contains the OIDC SSO contract before Dex login is expected to work.

## OIDC Contract

Argo CD uses bundled Dex with an upstream OIDC connector. The
`argocd-oidc-sso` Kubernetes Secret comes from External Secrets and AWS SSM:

- `/homelab/argocd/oidc/issuer`
- `/homelab/argocd/oidc/client-id`
- `/homelab/argocd/oidc/client-secret`

The Secret must keep `app.kubernetes.io/part-of: argocd` so Argo CD can resolve
Dex connector references from `argocd-cm`.

For Microsoft Entra, Dex requests only `openid`, `profile`, and `email`. Do not
add `groups` as a requested OAuth scope; Entra rejects it with `AADSTS650053`.
Group-based RBAC depends on Entra emitting a token `groups` claim and Dex
`insecureEnableGroups` passing that claim through to Argo CD.

## Apply And Verify

Validate first:

```sh
cd IaC
terragrunt hcl fmt --check
cd bootstrap/argocd
terragrunt init
terragrunt plan
```

Apply:

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

Verify:

```sh
kubectl get namespace argocd
kubectl -n argocd get pods
kubectl -n argocd get svc argocd-application-controller-metrics argocd-repo-server-metrics argocd-server-metrics
kubectl -n argocd get applications.argoproj.io argocd-self-management
kubectl -n argocd describe applications.argoproj.io argocd-self-management
```

Expected steady state: Argo CD is internal, `argocd-self-management` exists in
the `argocd` namespace, the `homelab` AppProject exists, and the default
AppProject is locked down.

## Recovery Rules

- Missing CRDs: fix the Helm release before retrying Application registration.
- Bad repo path or target revision: fix repo-owned code, then re-plan and apply.
- Missing credentials: inject through CI/CD or external secret paths; never
  commit the secret material.
- Partial install: capture read-only state, fix or revert repo code, and re-run
  the same stack.
- Break-glass live changes must be backfilled into git.

## Related Notes

- [[../architecture/gitops-flow]]
- [[secrets-aws-ssm]]
- [[validation]]
