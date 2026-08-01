# Crossplane

This path documents the Crossplane core deployment for the homelab cluster. The
`platform-crossplane` Argo CD Application is registered by the Terragrunt unit
at `IaC/live/argocd-apps/platform-crossplane` and installs the upstream
Crossplane chart with default values into the `crossplane-system` namespace.

This installs only Crossplane core. Providers, ProviderConfigs, Compositions,
and cloud credentials should be added in later, purpose-specific changes with
their secret contracts documented before rollout.

Before declaring the rollout healthy, verify:

```sh
kubectl -n crossplane-system get pods
kubectl get crd | rg 'crossplane.io|pkg.crossplane.io'
```

If Argo CD starts managing Crossplane Provider, Composition, or managed-resource
objects, configure Argo CD annotation-based resource tracking and health
customizations first. Crossplane documents those requirements in its Argo CD
guide.
