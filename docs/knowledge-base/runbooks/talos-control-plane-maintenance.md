# Talos Control-Plane Maintenance

Tags: #runbooks #talos #kubernetes #maintenance

Source: `docs/talos-control-plane-maintenance.md`

## Current Audit Findings

- Live Kubernetes OIDC discovery issuer: `https://10.1.0.216:6443`
- Canonical Kubernetes API endpoint: `https://10.1.0.199:6443`
- Live versions from audit: Kubernetes `v1.34.1`, Talos `v1.11.3`

Treat `10.1.0.216` as stale. Desired service-account issuer is:

```text
https://10.1.0.199:6443
```

The repository patch is `.talos/patches/controlplane-service-account-issuer.yaml`.

## Render And Validate Issuer Fix

When `.talos/controlplane.yaml` is available locally:

```sh
talosctl machineconfig patch .talos/controlplane.yaml \
  --patch @.talos/patches/controlplane-service-account-issuer.yaml \
  --output /private/tmp/controlplane-service-account-issuer.yaml

talosctl validate \
  --config /private/tmp/controlplane-service-account-issuer.yaml \
  --mode metal \
  --strict
```

Confirm only the endpoint, cert SAN, and service-account issuer changes are
intended. Do not regenerate cluster secrets.

## Apply Sequence

Only apply after validation and explicit operator approval:

1. Confirm `kubectl get nodes -o wide`.
2. Confirm Talos services with authenticated `talosctl`.
3. Apply the validated rendered config to `10.1.0.199`.
4. Watch Talos services and Kubernetes node readiness.
5. Verify issuer discovery with `kubectl get --raw /.well-known/openid-configuration`.
6. Refresh kubeconfig after the API is healthy.

## Upgrade Checklist

Before Talos or Kubernetes upgrades:

- Refresh official release info.
- Choose compatible Talos and Kubernetes targets.
- Run `nix flake check` and Talos config validation.
- Preflight live nodes and pods with read-only commands.
- Upgrade Kubernetes from the control-plane node.
- Upgrade Talos one node at a time, workers first, control plane last.
- Verify nodes, pods, issuer discovery, and system disks afterward.

## Risks

Single control-plane clusters have no API-server redundancy. Schedule a
maintenance window, keep machine-config schema migrations in git, and verify
stateful workloads after node reboots.
