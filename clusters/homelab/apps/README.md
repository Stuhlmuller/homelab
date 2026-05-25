# Homelab App Desired State

Each directory under `clusters/homelab/apps/` contains the repo-owned desired
state consumed by an Argo CD Application registered from Terragrunt.

Typical files:

- `values.yaml`: Helm values or app-template values with non-secret defaults.
- `externalsecret.yaml`: AWS SSM Parameter Store references only.
- `virtualservice.yaml`: Istio tailnet-only route for internal access when
  direct operator ingress is intentionally allowed.
- `kustomization.yaml`: Raw resources included by Argo CD alongside Helm
  sources.
- `README.md`: Storage, backup, restore, rollback, and app-specific notes.

Raw manifests are wired through each app's Argo CD multi-source configuration.
No file in this tree may contain secret values, private keys, raw certificate
material, private kubeconfigs, or private hostnames.

All first-rollout routes are tailnet-only. Public Tailscale Funnel routes are
not enabled in this tree; future webhook exceptions must follow the template in
`docs/networking-tailnet-ingress.md`.

Do not add a route just because an upstream chart exposes a web UI. Prefer the
least direct reviewed access path. For example, Grafana is the operator-facing
metrics UI, so Prometheus stays in-cluster only unless a later PR documents the
authentication and rollback plan for direct access.
