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

The `octeliumee-logstore`, `octeliumee-metricstore`, and
`octeliumee-rscstore` Deployments intentionally use `Recreate` instead of a
rolling update. Each process opens a DuckDB-backed `store.db` on its PVC, so a
second pod against the same volume can fail on the single-writer lock while the
old pod is still terminating. The resource-level
`argocd.argoproj.io/sync-options: Replace=true` annotation makes Argo replace
those adopted Deployments instead of server-side applying the strategy change;
that replacement clears the package-adopted rolling-update field from live
Deployments. Do not keep an explicit `rollingUpdate: null` field because it can
compare differently from the live object's absent field.

The `svc-console-octelium`, `svc-dirsync-octelium`,
`svc-enterprise-octelium-api`, and `svc-public-octelium` Deployments are
generated service proxies. The committed package capture keeps their images
pinned as `tag@sha256:digest`, but the Octelium controller normalizes those
live Deployments back to tag-only image references. The Argo CD Application
therefore ignores only the `vigil` and `managed` container image fields on
those four Deployments and uses `RespectIgnoreDifferences=true` so self-heal
does not fight the controller-owned values.

## Updating

Use `scripts/octelium-enterprise-package.sh --upgrade` first when changing the
Enterprise package version. After the package settles, refresh
`resources.yaml` from the healthy live resources, scrub generated metadata, pin
images as `tag@sha256:digest`, preserve `Recreate` and resource-level
`Replace=true` on the three store Deployments, omit `rollingUpdate`, preserve
the Argo image ignore rule for the four generated service proxy Deployments,
and re-run validation.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-enterprise
kubectl -n octelium get deploy,pod,svc,pvc -l octelium.com/app=octeliumee
scripts/octelium-e2e-check.sh
```
