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

The External Secrets Operator `ExternalSecret` that creates `argocd-oidc-sso`
from the shared `aws-ssm` ClusterSecretStore live under
`clusters/homelab/argocd/self-management`. They are intentionally outside the
initial Terragrunt Helm bootstrap so a fresh cluster can install Argo CD before
External Secrets CRDs exist. Install External Secrets Operator and give it
read-only Parameter Store access before expecting the automated
self-management sync to make `oidc-external-secret.yaml` healthy.

Create these AWS Systems Manager Parameter Store entries before rollout:

| Parameter | Secret key | Expected value |
| --- | --- | --- |
| `/homelab/argocd/oidc/issuer` | `issuer` | OIDC issuer URL used for provider discovery. |
| `/homelab/argocd/oidc/client-id` | `clientID` | OIDC client ID issued by the IdP. |
| `/homelab/argocd/oidc/client-secret` | `clientSecret` | OIDC client secret stored outside git. |

Store `/homelab/argocd/oidc/client-secret` as a SecureString. The other values
may be String or SecureString depending on local policy. Dex startup uses the
literal Microsoft Entra issuer committed in
`IaC/bootstrap/argocd/terragrunt.hcl`; the SSM issuer path is kept as a
compatibility copy for the generated `argocd-oidc-sso` Secret. Do not reset it
to `REPLACE_ME`, because Dex provider discovery fails before it can serve OIDC
login when the issuer is a placeholder.

The browser-facing Argo CD URL is committed as non-secret desired state in
`IaC/bootstrap/argocd/terragrunt.hcl`, not stored in Parameter Store. This
change does not create an ingress or DNS record. Register
`https://argocd.stinkyboi.com/api/dex/callback` with the IdP; Argo CD derives
that Dex connector callback from the configured `url`.

For Microsoft Entra, keep Dex requested scopes to `openid`, `profile`, and
`email`. Do not add `groups` as an OAuth scope; Entra rejects it with
`AADSTS650053`. Argo CD group authorization still uses the token `groups` claim
through Dex `insecureEnableGroups`, so configure the Entra application
registration to emit group membership claims. Entra may omit the
`email_verified` claim from the ID token; the Dex connector sets
`insecureSkipEmailVerified: true` for this trusted upstream and still relies on
the Entra app registration, callback URL, client secret, and Argo CD RBAC for
access control.

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
- Enables the Argo CD application controller, repo server, and API server
  metrics services for Prometheus scraping.
- Configures Dex with an OIDC connector and Argo CD RBAC defaults.
- Does not render `SecretStore` or `ExternalSecret` resources in the Terragrunt
  bootstrap Helm release.
- Applies the `homelab` AppProject and `argocd-self-management` Application
  with the Terragrunt `after_hook` only after `applications.argoproj.io` and
  `appprojects.argoproj.io` are established.
- Uses the Terragrunt catalog `helm-release` module pinned to `0.3.0`.
- Shows no raw secrets, kubeconfigs, tokens, keys, or certificate material.

## Apply

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

This is the one-command durable bootstrap path. From a clean cluster, Helm
installs Argo CD and its CRDs first. The Terragrunt `after_hook` then waits for
`applications.argoproj.io` and `appprojects.argoproj.io`, applies the
repo-owned `homelab` AppProject, and applies the self-management Application
manifest from this repository.

## Verify Healthy State

```sh
kubectl get namespace argocd
kubectl -n argocd get pods
kubectl -n argocd get svc argocd-application-controller-metrics argocd-repo-server-metrics argocd-server-metrics
kubectl -n argocd get applications.argoproj.io argocd-self-management
kubectl -n argocd describe applications.argoproj.io argocd-self-management
```

Expected result within 10 minutes:

- The `argocd` namespace exists.
- Argo CD pods are running or progressing normally.
- The Argo CD metrics services exist for the application controller, repo
  server, and API server.
- `argocd-self-management` exists in the `argocd` namespace.
- The `homelab` AppProject exists and no workload Application needs the live
  `default` project.
- The `default` AppProject has no source repositories or destinations.
- The Application source points at
  `clusters/homelab/argocd/self-management` in this repository.

After External Secrets Operator is installed and the self-management path is
synced, verify the OIDC secret bridge:

```sh
kubectl describe clustersecretstore aws-ssm
kubectl -n argocd get externalsecrets.external-secrets.io argocd-oidc-sso
kubectl -n argocd get secret argocd-oidc-sso
```

Expected OIDC result:

- `aws-ssm` reports as ready.
- `argocd-oidc-sso` reports as ready.
- The generated Kubernetes Secret is labeled as part of Argo CD.

If `argocd-oidc-sso` reports `ClusterSecretStore "aws-ssm" is not ready`, wait
for `scripts/ci/install-external-secrets-aws-auth.sh` to create the
`external-secrets/aws-ssm-auth` Secret from protected CI secrets. The
ExternalSecret uses
`refreshPolicy: OnChange`; if only SSM values changed, make a repo-owned
metadata or spec change and let Argo CD sync it rather than patching the live
resource.

## First Handoff

The self-management Application now enables automated prune and self-heal from
repository desired state by default. Before applying bootstrap changes, confirm
the Application source path, target revision, and rendered manifests in
`clusters/homelab/argocd/self-management/application.yaml`.

After bootstrap, Argo CD owns steady-state configuration under
`clusters/homelab/argocd/self-management`. Keep automation changes in this
repository; do not patch the live Application as the permanent fix for source
path, revision, or sync policy changes.

The OIDC ExternalSecret resources in the self-management path require External
Secrets Operator CRDs and AWS SSM access. Automated sync may retry those
resources until External Secrets Operator is installed by the app onboarding
stack.

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
   in `us-west-2`.
3. Confirm the `argocd-oidc-sso` Kubernetes Secret exists and has the
   `app.kubernetes.io/part-of: argocd` label.
4. Confirm the IdP app uses the same client ID as Parameter Store and has
   `<url>/api/dex/callback` registered as the callback URL.
5. Inspect `kubectl -n argocd logs deploy/argocd-dex-server` for OIDC
   validation errors. Do not paste raw assertion, token, or secret values into
   the repository.
6. If Dex logs `AADSTS650053` for the `groups` scope, remove `groups` from the
   requested Dex scopes and configure the IdP app to emit a `groups` claim
   instead.
7. If Dex logs `missing "email_verified" claim`, keep
   `insecureSkipEmailVerified: true` in the connector for Microsoft Entra and
   re-apply the Argo CD bootstrap desired state.

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
  remote revision `main` with automated prune and self-heal enabled; sync may
  remain `Unknown` until `main` contains
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
