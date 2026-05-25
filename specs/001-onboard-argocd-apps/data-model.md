# Data Model: Argo CD Application Onboarding

## Entities

### ApplicationOnboarding

Represents one requested application registered for Argo CD ownership.

Fields:

- `name`: stable lowercase hyphenated Argo CD application name.
- `requested_name`: user-facing name from the request when it differs from the
  canonical Kubernetes name.
- `category`: platform, observability, media, automation, AI, or scheduling.
- `namespace`: destination Kubernetes namespace.
- `owner_path`: Terragrunt unit path under `IaC/live/argocd-apps/<app>/`.
- `gitops_path`: repo-owned values/manifests path under
  `clusters/homelab/apps/<app>/`.
- `catalog_module`: `argocd-application` unless exact CRD control requires
  `argocd-application-manifest`.
- `dependencies`: explicit upstream Terragrunt unit paths.
- `secret_refs`: AWS SSM Parameter Store names or paths referenced by
  ExternalSecret resources.
- `storage_profile`: none, controller-runtime-only, or persistent.
- `storage_class`: default NFS-backed StorageClass for persistent workloads
  unless an app-specific exception is documented.
- `storage_dependency`: `IaC/live/argocd-apps/platform-storage/terragrunt.hcl`
  for persistent workloads that depend on the default NFS StorageClass.
- `ingress_policy`: none, tailnet-only, or future-funnel-webhook.
- `sync_expectation`: desired Argo CD sync and health result.
- `rollback_notes`: dependency-aware rollback and data-preservation notes.

Validation rules:

- `name` and `namespace` must be hyphenated when they create Kubernetes objects.
- Every dependency edge must be represented in Terragrunt.
- First rollout must set `ingress_policy` to `none` or `tailnet-only`; no app may
  set `future-funnel-webhook` until a later approved change.
- Secret values are never valid; only AWS SSM names/paths are valid.

### TerragruntApplicationEntry

Represents the catalog-backed unit that registers an Argo CD Application.

Fields:

- `unit_path`: `IaC/live/argocd-apps/<app>/terragrunt.hcl`.
- `include_root`: reference to `IaC/root.hcl`.
- `source_module`: catalog module name.
- `metadata`: Argo CD Application metadata, labels, and annotations.
- `destination`: cluster and namespace target.
- `sources`: Helm, Kustomize, directory, or multi-source app configuration.
- `sync_policy`: automated sync, prune, self-heal, retry, and namespace options.
- `dependencies_block`: Terragrunt dependency paths.
- `info`: operator-facing links to docs, storage profile, and route policy.

Validation rules:

- `dependencies_block` must be present for all apps with upstream requirements.
- `source_module` must come from the configured Terragrunt catalog.
- `sources` must point to deterministic versions or repo-owned paths.
- `sync_policy` must enable automated prune and self-heal by default unless a
  future exception is explicitly documented.
- `info` must identify storage, ingress, and rollback docs.

### DependencyEdge

Represents an explicit ordering relationship.

Fields:

- `from`: upstream application name.
- `to`: downstream application name.
- `reason`: secret, certificate, reverse-proxy, reachability, observability,
  download-client integration, or model-gateway integration.
- `terragrunt_path`: upstream Terragrunt unit path used in `dependencies`.

Validation rules:

- No dependency cycles.
- No downstream app may rely on Tailscale, Istio, cert-manager, external-secrets,
  Prometheus, Deluge, Prowlarr, or LiteLLM without a matching edge.

### RuntimeSecretReference

Represents a safe public pointer to secret material.

Fields:

- `application`: owning application.
- `parameter_path`: AWS SSM Parameter Store path.
- `purpose`: admin password, provider token, OAuth credential, API key, webhook
  secret, Tailscale credential, or model provider key.
- `external_secret_name`: Kubernetes ExternalSecret name.
- `target_secret_name`: Kubernetes Secret name created at runtime.

Validation rules:

- `parameter_path` must not contain the secret value.
- Every runtime secret must use AWS SSM Parameter Store.
- ExternalSecret resources must depend on external-secrets readiness.

### StatefulWorkloadProfile

Represents storage and data-risk expectations for an app.

Fields:

- `application`: owning application.
- `requires_persistence`: true or false.
- `data_classes`: configuration, dashboards, metrics, media, downloads, model
  routing, automation history, or controller-runtime state.
- `storage_class`: selected storage class or documented prerequisite.
- `backup_method`: snapshot, file backup, app export, or not required.
- `restore_steps`: documented restore path.
- `rollback_data_behavior`: preserve, snapshot first, or safe to delete.
- `backup_coverage`: documented NFS backup coverage for persistent data.

Validation rules:

- Stateful applications must define backup and restore behavior before they are
  considered ready.
- Stateful applications must not be considered ready until NFS backup coverage
  is documented for their persistent data.
- Rollback must not delete persistent volumes unless the operator explicitly
  chooses data removal.

### DefaultStorageClass

Represents the cluster default StorageClass for persistent application data.

Fields:

- `name`: stable StorageClass name.
- `provisioner`: existing NFS provisioner name discovered through read-only
  cluster inspection.
- `parameters`: public-safe non-secret StorageClass parameters.
- `is_default`: true.
- `owned_by_feature`: StorageClass only; the provisioner remains outside this
  feature's ownership.
- `backup_coverage`: documented NFS backup coverage and restore expectation.

Validation rules:

- The provisioner must be discovered read-only before desired state is
  committed.
- Unsafe private provisioner values must use placeholders or safe references.
- The StorageClass must be marked as default before stateful application
  rollout.
- Persistent application registrations must depend on the supporting
  `platform-storage` Terragrunt unit.

### IngressExposurePolicy

Represents route and reachability decisions.

Fields:

- `application`: owning application.
- `reverse_proxy`: Istio.
- `reachability`: none or tailnet-only for first rollout.
- `dns_strategy`: initial wildcard or equivalent setup that avoids per-app DNS
  edits.
- `funnel_enabled`: false for first rollout.
- `future_public_paths`: documented only for later approved webhook exceptions.

Validation rules:

- `funnel_enabled` must be false for every first-rollout application.
- Tailnet routes must depend on Istio and Tailscale readiness.
- Future public paths must name owner, path, purpose, and rollback.

### ImageUpdatePolicy

Represents Argo CD Image Updater automation.

Fields:

- `application`: owning Argo CD Application.
- `controller`: `argocd-image-updater`.
- `selection_model`: opt-in label and annotation selector.
- `write_back_method`: default `argocd` unless a future credential-backed Git
  write-back contract is added.
- `registry_refs`: public registry endpoints or ExternalSecret-backed private
  registry credentials.

Validation rules:

- The controller must be installed through an Argo CD Application registered by
  Terragrunt.
- Applications must not be updated unless they carry the opt-in label and image
  annotations.
- Git write-back credentials must not be committed.

## Application Matrix

| App | Namespace | Category | Dependencies | Storage | Ingress | Secret Model |
|-----|-----------|----------|--------------|---------|---------|--------------|
| argocd-image-updater | argocd | platform | Argo CD bootstrap | none | none | no Git write credentials by default |
| external-secrets | external-secrets | platform | Argo CD bootstrap | none | none | AWS access references only |
| cert-manager | cert-manager | platform | external-secrets | controller-runtime only | none | issuer/provider refs if needed |
| istio | istio-system | platform | cert-manager | none | tailnet route target | cert refs if needed |
| tailscale | tailscale | platform | external-secrets, istio | none | tailnet reachability | SSM-backed credentials |
| platform-storage | cluster-scoped | storage | existing NFS provisioner | default NFS StorageClass only | none | none |
| prometheus | monitoring | observability | external-secrets, platform-storage | persistent metrics on default NFS StorageClass | tailnet-only | optional scrape/auth refs |
| grafana | monitoring | observability | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage | persistent dashboards/config on default NFS StorageClass | tailnet-only | SSM-backed admin/auth refs |
| descheduler | kube-system | scheduling | prometheus | none | none | none expected |
| deluge | media | media | cert-manager, istio, tailscale, platform-storage | persistent config/downloads on default NFS StorageClass | tailnet-only | config PVC-managed app credentials |
| prowlarr | media | media | cert-manager, istio, tailscale, platform-storage | persistent indexer and app integration config on default NFS StorageClass | tailnet-only | config PVC-managed app credentials |
| radarr | media | media | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage | persistent config/media refs on default NFS StorageClass | tailnet-only | config PVC-managed app and integration credentials |
| sonarr | media | media | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage | persistent config/media refs on default NFS StorageClass | tailnet-only | config PVC-managed app and integration credentials |
| litellm | ai | AI gateway | external-secrets, cert-manager, istio, tailscale, platform-storage | persistent if configured with DB/config store on default NFS StorageClass | tailnet-only | SSM-backed model provider refs |
| openclaw | ai | AI service | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage | persistent config/runtime state on default NFS StorageClass | tailnet-only | SSM-backed app/model refs |
| n8n | automation | automation | external-secrets, cert-manager, istio, tailscale, platform-storage | persistent workflows, SQLite data, and config on default NFS StorageClass | tailnet-only | SSM-backed encryption key |

## State Transitions

1. `Specified`: application is listed in the feature spec.
2. `Planned`: application has dependencies, storage, ingress, and secret model
   documented.
3. `Registered`: Terragrunt plan shows an Argo CD Application registration.
4. `Synced`: Argo CD reports the application synced.
5. `Healthy`: Argo CD reports the application healthy or the documented
   acceptable health exception is recorded.
6. `RolledBack`: application registration is removed or disabled in dependency
   order, with persistent data handled according to the workload profile.
