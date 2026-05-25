# Argo CD Self-Management

This directory is the repository-owned desired-state path for Argo CD managing
its own steady-state configuration in the `homelab` cluster.

Terragrunt owns only the first seed:

- Install the Argo CD Helm release.
- Create the `homelab` AppProject that scopes repository, chart source, and
  destination access for this cluster.
- Create the `argocd-self-management` Application.
- Hand off to repository-defined automated prune and self-heal.

Argo CD owns changes under this directory after bootstrap. Automated prune and
self-heal are part of the repository desired state, so changes to the source
path, revision, or sync policy must still be reviewed in git instead of patched
as permanent live mutations.

Keep the `homelab` AppProject source repository, destination namespace, and
cluster-resource allow-lists aligned with the Applications registered under
`IaC/live/argocd-apps`. If an app needs a new chart repository, namespace, or
cluster-scoped kind, update `appproject.yaml` in the same PR as the app
registration.

This path also owns the External Secrets Operator resources that create the
`argocd-oidc-sso` Kubernetes Secret from AWS Systems Manager Parameter Store.
Keep those resources here instead of the Terragrunt bootstrap Helm values so a
fresh cluster can install Argo CD before External Secrets CRDs exist. Sync
`oidc-external-secret.yaml` only after External Secrets Operator is installed
and allowed to read the Argo CD OIDC issuer, client ID, and client secret
parameters in `us-west-2`. The browser-facing Argo CD URL is non-secret
desired state in the bootstrap Terragrunt values, not an SSM parameter.
The ExternalSecret refreshes every 5 minutes so bootstrap recovery is picked up
soon after the shared `aws-ssm` ClusterSecretStore becomes ready.
