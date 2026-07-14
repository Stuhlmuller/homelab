# Homelab App Desired State

Each directory under `clusters/homelab/apps/` contains the repo-owned desired
state consumed by an Argo CD Application registered from Terragrunt.

Typical files:

- `values.yaml`: Helm values or app-template values with non-secret defaults.
- `externalsecret.yaml`: AWS SSM Parameter Store references only.
- `virtualservice.yaml`: Istio SNI routing for an app hostname that is published
  through Octelium, or a separately reviewed non-app exception such as a webhook
  Funnel route.
- `kustomization.yaml`: Raw resources included by Argo CD alongside Helm
  sources.
- `README.md`: Storage, backup, restore, rollback, and app-specific notes.

Raw manifests are wired through each app's Argo CD multi-source configuration.
No file in this tree may contain secret values, private keys, raw certificate
material, private kubeconfigs, or private hostnames.

Repo-declared workload images that should move automatically must also be listed
in `clusters/homelab/apps/argocd-image-updater/imageupdater.yaml`; Image Updater
opens pull requests for those values instead of relying on live-only overrides.

Human app access targets the Octelium `.homelab` service catalog in
`docs/examples/octelium/homelab-services.yaml`. App `VirtualService` objects are
the private Istio backend routing layer for Octelium `WEB` Services; they must
stay annotated with `homelab.rst.io/access-plane: octelium` and
`homelab.rst.io/public-funnel: "false"`. External callbacks that cannot use
Octelium browser login must use reviewed first-level callback hostnames through
the `octelium-public` tunnel and carry `homelab.rst.io/public-callback`
annotations. Do not add Tailscale Funnel routes for app UI or callback traffic.
AFFiNE is the reviewed app exception: its Octelium Service is anonymous so the
native client can use AFFiNE's own authentication, with public signup disabled.

Do not add a route just because an upstream chart exposes a web UI. Prefer the
least direct reviewed access path. For example, Grafana is the operator-facing
metrics UI, so Prometheus stays in-cluster only unless a later PR documents the
authentication and rollback plan for direct access.
