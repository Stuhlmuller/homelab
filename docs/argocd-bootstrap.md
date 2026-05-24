# Argo CD Bootstrap Runbook

This runbook bootstraps Argo CD into the Talos-backed homelab cluster using the
repository-owned Terragrunt stack at `IaC/bootstrap/argocd`.

## Preconditions

- Work from this repository after the reviewed Argo CD bootstrap desired state
  is available on the default branch `main`.
- The local or CI/CD runtime has authenticated access to Kubernetes through the
  committed provider path `~/.kube/config`.
- External credentials for S3 remote state and KMS encryption are available as
  credential material; they are not desired-state inputs.
- The default branch `main` contains the Argo CD desired-state path before
  expecting the self-management Application to sync.
- No raw repository token, kubeconfig, Talos secret, private key, or certificate
  material is committed.
- AWS Parameter Store contains the OIDC SSO contract described below before
  expecting Dex login to succeed.

## OIDC SSO Secret Contract

Argo CD uses the bundled Dex server for SSO. Dex is configured with an upstream
OpenID Connect connector. The connector references a Kubernetes Secret named
`argocd-oidc-sso`, and that Secret must keep the label
`app.kubernetes.io/part-of: argocd` so Argo CD can resolve `$argocd-oidc-sso:*`
references from `argocd-cm`.

The External Secrets Operator `SecretStore` and `ExternalSecret` that create
`argocd-oidc-sso` from AWS Systems Manager Parameter Store live under
`clusters/homelab/argocd/self-management`. They are intentionally outside the
initial Terragrunt Helm bootstrap so a fresh cluster can install Argo CD before
External Secrets CRDs exist. Install External Secrets Operator and give it
read-only Parameter Store access before syncing the self-management path that
contains `oidc-external-secret.yaml`.

Create these AWS Systems Manager Parameter Store entries before rollout:

| Parameter | Secret key | Expected value |
| --- | --- | --- |
| `/homelab/argocd/oidc/url` | `url` | Browser-facing Argo CD base URL registered with the IdP. |
| `/homelab/argocd/oidc/issuer` | `issuer` | OIDC issuer URL used for provider discovery. |
| `/homelab/argocd/oidc/client-id` | `clientID` | OIDC client ID issued by the IdP. |
| `/homelab/argocd/oidc/client-secret` | `clientSecret` | OIDC client secret stored outside git. |

Store `/homelab/argocd/oidc/client-secret` as a SecureString. The other values
may be String or SecureString depending on local policy. This change does not
create an ingress or DNS record. Register `<url>/api/dex/callback` with the IdP;
Argo CD derives that Dex connector callback from the configured `url`.

## Validate Before Apply

Run formatting and planning from the repo root or stack directory:

```sh
cd IaC
terragrunt hcl fmt --check
```

```sh
cd IaC/bootstrap/argocd
terragrunt init
terragrunt plan
```

Expected plan:

- Installs or updates the `argocd` Helm release only through Terragrunt.
- Keeps the Argo CD service internal with `ClusterIP`.
- Configures Dex with an OIDC connector and Argo CD RBAC defaults.
- Does not render `SecretStore` or `ExternalSecret` resources in the Terragrunt
  bootstrap Helm release.
- Applies `argocd-self-management` with the Terragrunt `after_hook` only after
  `applications.argoproj.io` is established.
- Uses the Terragrunt catalog `helm-release` module pinned to `0.3.0`.
- Shows no raw secrets, kubeconfigs, tokens, keys, or certificate material.

## Apply

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

This is the one-command durable bootstrap path. From a clean cluster, Helm
installs Argo CD and its CRDs first. The Terragrunt `after_hook` then waits for
`applications.argoproj.io` and applies the self-management Application manifest
from this repository.

## Verify Healthy State

```sh
kubectl get namespace argocd
kubectl -n argocd get pods
kubectl -n argocd get applications.argoproj.io argocd-self-management
kubectl -n argocd describe applications.argoproj.io argocd-self-management
```

Expected result within 10 minutes:

- The `argocd` namespace exists.
- Argo CD pods are running or progressing normally.
- `argocd-self-management` exists in the `argocd` namespace.
- The Application source points at
  `clusters/homelab/argocd/self-management` in this repository.

After External Secrets Operator is installed and the self-management path is
synced, verify the OIDC secret bridge:

```sh
kubectl -n argocd get secretstores.external-secrets.io argocd-ssm
kubectl -n argocd get externalsecrets.external-secrets.io argocd-oidc-sso
kubectl -n argocd get secret argocd-oidc-sso
```

Expected OIDC result:

- `argocd-oidc-sso` reports as synced.
- The generated Kubernetes Secret is labeled as part of Argo CD.

## First Handoff

The first handoff is intentionally manual. Confirm the Application source path,
target revision, and rendered manifests before enabling automated
reconciliation.

After validation, update repository desired state:

- Uncomment or add the Application `syncPolicy.automated` block in
  `clusters/homelab/argocd/self-management/application.yaml`.

Use `prune: true` and `selfHeal: true` only after the source path has been
verified. Argo CD owns steady-state configuration under
`clusters/homelab/argocd/self-management` after the handoff.

## Drift And Reconciliation

Do not hand-edit the live Application as a permanent change. If Argo CD-owned
state drifts, correct the repository file and let Argo CD reconcile it. A live
mutation is incomplete until the final desired state is backfilled into this
repository and validated.

## Recovery

Missing CRDs:

1. Check the Helm release and pods:
   `kubectl -n argocd get pods` and `kubectl -n argocd get crd | grep argoproj`.
2. Re-run `terragrunt plan` from `IaC/bootstrap/argocd`.
3. Fix Helm install failures before retrying Application registration.

Bad repository path or target revision:

1. Inspect `kubectl -n argocd describe application argocd-self-management`.
2. Correct `repo_url`, `path`, or `target_revision` in repo-owned code.
3. Re-run `terragrunt plan` and `terragrunt apply`.

Missing credentials:

1. Confirm the repository is public or that Argo CD repository credentials are
   created by an external secret or CI/CD-injected path.
2. Do not commit tokens, deploy keys, or private kubeconfigs.
3. Commit only safe references, encrypted manifests, or contracts.

OIDC login fails:

1. Inspect `kubectl -n argocd describe externalsecret argocd-oidc-sso`.
2. Confirm the External Secrets Operator controller can read AWS Parameter Store
   in `us-east-1`.
3. Confirm the `argocd-oidc-sso` Kubernetes Secret exists and has the
   `app.kubernetes.io/part-of: argocd` label.
4. Confirm the IdP app uses the same client ID as Parameter Store and has
   `<url>/api/dex/callback` registered as the callback URL.
5. Inspect `kubectl -n argocd logs deploy/argocd-dex-server` for OIDC
   validation errors. Do not paste raw assertion, token, or secret values into
   the repository.

Partial install:

1. Capture `kubectl -n argocd get all` and Helm release status.
2. Fix the repository code that caused the partial state.
3. Re-run the same Terragrunt stack. If rollback is required, revert to the
   previous reviewed repo state and apply that state.

Existing manual Argo CD install conflict:

1. Inspect the existing release and namespace with read-only commands.
2. Decide whether Terragrunt should adopt or replace it in a reviewed change.
3. Do not force adoption with live patches that are not represented in code.

Break-glass live change:

1. Make the smallest live change needed to recover service.
2. Record the command and output.
3. Backfill the final desired state into this repository before the work is
   considered complete.

## Storage And Backup Impact

This feature introduces no workload persistent volumes. Durable state is limited
to S3 OpenTofu state, Kubernetes objects in the `argocd` namespace, and AWS
Parameter Store values under `/homelab/argocd/oidc`. Back up the remote state
bucket according to the existing infrastructure policy and keep Argo CD runtime
state recoverable from this repository plus external secret material.

## Validation Log

Validation results are recorded during implementation:

- Terragrunt HCL formatting: passed with `terragrunt hcl fmt --check`.
- OpenTofu formatting: no repository-local module files remain; the bootstrap
  stack uses the remote Terragrunt catalog module pinned to `0.3.0`.
- OpenTofu validation: passed with `terragrunt --log-disable validate
  -no-color` after `terragrunt --log-disable init -backend=false -no-color`.
- Terragrunt remote backend init: passed after refreshing AWS SSO credentials.
- Terragrunt plan: passed with `1 to add, 0 to change, 0 to destroy` for the
  Argo CD Helm release.
- Terragrunt apply: passed with `1 added, 0 changed, 0 destroyed`; the
  `after_hook` waited for `applications.argoproj.io` and created
  `argocd-self-management`.
- Kustomize build: passed with
  `kubectl kustomize clusters/homelab/argocd/self-management`.
- Kubernetes read-only preflight: API access worked after sandbox escalation;
  `argocd` namespace and `applications.argoproj.io` CRD were not present before
  apply, which matched a clean bootstrap target.
- Post-apply Kubernetes verification: `argocd` namespace is active, Argo CD pods
  are running, `applications.argoproj.io` exists, and
  `argocd-self-management` is healthy. The self-management Application tracks
  remote revision `main`; sync remains `Unknown` until `main` contains
  `clusters/homelab/argocd/self-management`.
- Secret/input scan: passed for raw secret patterns and forbidden desired-state
  environment input patterns across the bootstrap stack and self-management
  files.
- OIDC SSO update validation: `terragrunt hcl fmt --check`, `terragrunt
  validate -no-color`, `terragrunt plan -no-color`, `kubectl kustomize
  clusters/homelab/argocd/self-management`, `helm template` with the evaluated
  Terragrunt values, `nix flake check`, and `git diff --check` passed. The plan
  updates the existing `argocd` Helm release in place with `0 to add, 1 to
  change, 0 to destroy`.
