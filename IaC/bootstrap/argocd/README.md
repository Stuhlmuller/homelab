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
CD Application CRD and applies the repo-owned `argocd-self-management`
manifest.

The `terraform.source` value points directly at the Terragrunt catalog
`helm-release` module pinned to version `0.3.0`. There are no repository-local
OpenTofu modules in this bootstrap stack.

All desired-state inputs here are committed non-secret values. Do not add
`get_env`, `TF_VAR_*`, shell-exported values, raw kubeconfigs, repository
tokens, private keys, or certificate material to this stack. CI/CD may inject
credentials at runtime; the desired state must remain visible in this file or
the module defaults it calls.
