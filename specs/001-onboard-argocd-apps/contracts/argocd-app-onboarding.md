# Contract: Argo CD Application Onboarding

## Terragrunt Unit Contract

Each application MUST have one Terragrunt unit:

```text
IaC/live/argocd-apps/<app>/terragrunt.hcl
```

The unit MUST:

- Include `IaC/root.hcl`.
- Source the configured Terragrunt catalog module `argocd-application` unless
  `argocd-application-manifest` is documented as necessary.
- Set Argo CD Application metadata with a stable hyphenated `name`.
- Set destination namespace.
- Set deterministic `sources` using chart versions, Git revisions, or
  repo-owned values paths.
- Set sync policy and namespace creation behavior explicitly.
- Enable automated prune and self-heal by default unless a future exception is
  documented beside the app.
- Declare all ordering requirements with Terragrunt `dependencies`.
- Include app `info` entries or adjacent docs for storage, route, secret, and
  rollback expectations.

Required shape:

```hcl
include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "<terragrunt-catalog-source>/modules/argocd-application"
}

dependencies {
  paths = [
    "../external-secrets",
    "../cert-manager",
  ]
}

inputs = {
  metadata = {
    name      = "<app>"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
    }
  }

  project = "default"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "<namespace>"
  }

  sources = [
    {
      repo_url        = "<helm-or-git-source>"
      chart           = "<chart-when-helm>"
      path            = "<path-when-git-source>"
      target_revision = "<pinned-version-or-revision>"
      helm = {
        value_files = ["$values/clusters/homelab/apps/<app>/values.yaml"]
      }
    },
    {
      repo_url        = "<this-repository-url>"
      target_revision = "<branch-or-revision>"
      ref             = "values"
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    sync_options = [
      "CreateNamespace=true"
    ]
    retry = {
      limit = "5"
      backoff = {
        duration     = "30s"
        factor       = "2"
        max_duration = "2m"
      }
    }
  }
}
```

Implementation MUST use the configured Terragrunt catalog source for the exact
source address while preserving the `argocd-application` module choice.

## Dependency Contract

Every dependency in this table MUST be represented in Terragrunt:

| Application | Required Dependencies |
|-------------|-----------------------|
| platform-storage | existing NFS provisioner prerequisite |
| argocd-image-updater | Argo CD bootstrap |
| external-secrets | none beyond Argo CD bootstrap |
| cert-manager | external-secrets |
| istio | cert-manager |
| tailscale | external-secrets, istio |
| prometheus | external-secrets, platform-storage |
| grafana | external-secrets, cert-manager, istio, tailscale, prometheus, platform-storage |
| descheduler | prometheus |
| deluge | cert-manager, istio, tailscale, platform-storage |
| prowlarr | cert-manager, istio, tailscale, platform-storage |
| radarr | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage |
| sonarr | cert-manager, istio, tailscale, deluge, prowlarr, platform-storage |
| litellm | external-secrets, cert-manager, istio, tailscale, platform-storage |
| openclaw | external-secrets, cert-manager, istio, tailscale, litellm, platform-storage |
| tines | external-secrets, cert-manager, istio, tailscale, platform-storage |

## Secret Reference Contract

ExternalSecret resources and app values MAY commit:

- AWS SSM Parameter Store names or paths.
- Kubernetes Secret names created by External Secrets.
- Non-secret defaults.

They MUST NOT commit:

- Secret values.
- Tailscale auth material.
- LiteLLM model-provider keys.
- App admin passwords.
- Raw certificate material.
- Kubeconfigs with credentials.

Each secret reference MUST identify:

- Owning application.
- AWS SSM parameter path.
- Runtime Kubernetes Secret name.
- Purpose of the secret.

## Image Update Contract

Argo CD Image Updater MUST be installed as an Argo CD-managed Application using
the Terragrunt catalog module.

Default behavior:

- Watch Applications in the `argocd` namespace.
- Select only Applications labeled
  `homelab.stuhlmuller.dev/image-updater=enabled`.
- Read image configuration from `argocd-image-updater.argoproj.io/*`
  annotations on the selected Application.
- Use `argocd` write-back unless a future Git write-back credential contract is
  added.

Application opt-in MUST document the image list, update strategy, and Helm or
Kustomize target keys. Git credentials, registry credentials, webhook secrets,
and private tokens MUST use ExternalSecret-backed runtime material.

## Ingress Contract

First rollout:

- Reverse proxy: Istio.
- Reachability: Tailscale tailnet.
- Public surface: zero Tailscale Funnel paths.
- DNS: initial configuration must support future app routes without per-app DNS
  record edits.

Future webhook exception:

- May use Tailscale Funnel only.
- Must name owning application, public path, purpose, source system, rollback
  behavior, and whether any secret validates inbound requests.

## Storage Contract

Default storage:

- The feature adds one NFS-backed Kubernetes StorageClass.
- The StorageClass is registered through the supporting
  `IaC/live/argocd-apps/platform-storage/terragrunt.hcl` unit using a
  Terragrunt catalog Argo CD Application module.
- The StorageClass uses an existing NFS provisioner discovered by read-only
  cluster inspection.
- The StorageClass is marked as the cluster default.
- The feature does not install, replace, or take ownership of the NFS
  provisioner.
- Only public-safe provisioner details may be committed; unsafe private values
  must use placeholders or safe references.
- NFS backup coverage must be documented before stateful apps roll out.

Every application MUST document one storage profile before rollout:

- `none`
- `controller-runtime-only`
- `persistent`

For `persistent`, documentation MUST include:

- Default NFS StorageClass usage or an approved app-specific exception.
- Data classes retained.
- NFS backup coverage.
- Restore steps.
- Rollback behavior for persistent volumes.
