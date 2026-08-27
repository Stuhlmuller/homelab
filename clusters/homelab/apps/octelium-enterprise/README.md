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
- A bounded emergency dataplane on `acer` for the control paths, CI API, and
  current public WEB Services while both normal dataplane nodes are NotReady.

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

`octeliumee-rscstore` includes an incident-specific, completion-marked init
container for the 2026-08-26 DuckDB recovery. It renames the unreplayable
`store.db.wal` to `store.db.wal.quarantined-20260826` before startup and never
deletes it. The earlier `20260821` marker and quarantined WAL remain untouched.
If the new quarantine already exists while its completion marker is absent, the
init container fails instead of overwriting evidence. Remove it only after
rscstore is healthy and the preserved WAL is no longer needed for recovery.

The `svc-console-octelium`, `svc-dirsync-octelium`,
`svc-enterprise-octelium-api`, and `svc-public-octelium` Deployments are
generated service proxies. The committed package capture keeps their images
pinned as `tag@sha256:digest`, but the Octelium controller normalizes those
live Deployments back to tag-only image references. The Argo CD Application
therefore ignores only the `vigil` and `managed` container image fields on
those four Deployments and uses `RespectIgnoreDifferences=true` so self-heal
does not fight the controller-owned values.

`emergency-dataplane.yaml` reuses each existing Octelium Service selector and
runs a uniquely named, digest-pinned fallback Deployment on the primary
Kubernetes network. The 18 newly added public WEB fallbacks extend the existing
OctoBot fallback, giving 19 public WEB proxies in this recovery manifest.
`default.cordium` and `console.octelium` include their required managed
sidecars; Cordium also gets a bounded writable `/tmp` for its bbolt cache. Do
not add the Multus annotation or a dataplane node label to these temporary
Pods. If Octelium recreates a Service, refresh its generated
`octelium.com/svc-uid` here before relying on the fallback.

Keep this recovery file until a correctly sized native dataplane worker has
run the full package-managed fleet for 24 hours. Follow the direct native Pod
probe and public end-to-end removal gate in
`docs/knowledge-base/architecture/cluster-topology.md`; Service-level probes
alone can be satisfied by these emergency replicas.

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
