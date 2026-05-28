# Argo CD Bootstrap Stack

This is the single Terragrunt entry point for seeding Argo CD into the homelab
cluster:

```sh
cd IaC/bootstrap/argocd
terragrunt apply
```

The stack installs Argo CD into the `argocd` namespace with the pinned
`argo-cd` chart version `9.5.15` and keeps the service internal with
`ClusterIP`. After Helm succeeds, a Terragrunt `after_hook` waits for the Argo
CD Application and AppProject CRDs, applies the repo-owned `homelab`
AppProject, and then applies the `argocd-self-management` Application
manifest.

The Helm values also configure Argo CD SSO through the bundled Dex server with
an OpenID Connect connector. The browser-facing Argo CD URL is committed here
as non-secret desired state; the connector reads its provider-specific secret
values through the Argo CD secret reference syntax from a Kubernetes Secret
named `argocd-oidc-sso`.

The Helm values enable metrics services for the application controller, repo
server, and API server. Prometheus `ServiceMonitor` resources live in
`clusters/homelab/apps/prometheus` so the bootstrap stack does not depend on
Prometheus Operator CRDs existing before Argo CD is installed.

External Secrets Operator resources for creating `argocd-oidc-sso` from AWS
Systems Manager Parameter Store live in the Argo CD self-management path at
`clusters/homelab/argocd/self-management/oidc-external-secret.yaml`. Keeping
those CRD-backed resources out of this initial Helm release lets the bootstrap
install Argo CD before External Secrets Operator is available.

Required Parameter Store paths:

| Path | Kubernetes key | Purpose |
| --- | --- | --- |
| `/homelab/argocd/oidc/issuer` | `issuer` | OIDC issuer URL used for provider discovery. |
| `/homelab/argocd/oidc/client-id` | `clientID` | OIDC client ID issued by the IdP. |
| `/homelab/argocd/oidc/client-secret` | `clientSecret` | OIDC client secret kept out of git. |

Register `https://argocd.stinkyboi.com/api/dex/callback` as the IdP callback
URL. Argo CD derives the Dex connector callback from its configured `url`; do
not store a separate callback value in git or Parameter Store.

For Microsoft Entra, keep the Dex connector's requested scopes to standard
OpenID Connect scopes: `openid`, `profile`, and `email`. Do not request a
`groups` OAuth scope; Entra rejects that request. Group-based Argo CD RBAC
still uses the token's `groups` claim through Dex `insecureEnableGroups`, so
the Entra application registration must emit group membership claims.

The `terraform.source` value points directly at the Terragrunt catalog
`helm-release` module pinned to version `0.3.0`. There are no repository-local
OpenTofu modules in this bootstrap stack.

All desired-state inputs here are committed non-secret values. Do not add
`get_env`, `TF_VAR_*`, shell-exported values, raw kubeconfigs, repository
tokens, private keys, or certificate material to this stack. CI/CD may inject
credentials at runtime; the desired state must remain visible in this file or
the module defaults it calls. Keep OIDC client secrets and IdP-specific values
in AWS Parameter Store, not in this repository or Helm values.
