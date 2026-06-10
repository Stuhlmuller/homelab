# Octelium Enterprise GitOps State

This app lets Argo CD own the Kubernetes steady state for the
`octeliumee` Enterprise package after the package has been installed with
`octops install-package`.

The upstream Enterprise package still creates Octelium-native resources and
runtime Secrets. This directory intentionally commits only non-secret
Kubernetes resources that are safe for this public repository:

- `octeliumee-*` Enterprise Deployments and Services.
- Enterprise service-proxy Deployments, Services, and ConfigMaps for
  `console.octelium`, `enterprise.octelium-api`, `public.octelium`, and
  `dirsync.octelium`.
- ServiceAccounts required by Enterprise package components.
- PVC declarations for `octelium-rscstore`, `octelium-logstore`, and
  `octelium-metricstore`, each protected from Argo CD deletion with
  `argocd.argoproj.io/sync-options: Delete=false`.

Do not commit generated Secrets such as `sys-init-kek`, Octelium database
credentials, license material, or kubeconfigs here. Those remain runtime state
created by Octelium or stored through the existing secret contracts.

The Deployment manifests keep the upstream package security context and probe
shape. Checkov exceptions are scoped per Deployment for that adoption boundary;
change them only after validating the new runtime constraints against the
Enterprise package.

## Updating

Use `scripts/octelium-enterprise-package.sh --upgrade` first when changing the
Enterprise package version. After the package settles, refresh
`resources.yaml` from the healthy live resources, scrub generated metadata, pin
images as `tag@sha256:digest`, and re-run validation.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-enterprise
kubectl -n octelium get deploy,pod,svc,pvc -l octelium.com/app=octeliumee
scripts/octelium-e2e-check.sh
```
