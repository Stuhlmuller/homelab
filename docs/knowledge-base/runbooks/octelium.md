# Octelium

Tags: #runbooks #octelium #networking #secrets

Source: `docs/octelium.md`

## Model

Octelium runs as a parallel client bridge, not as a replacement for Tailscale.
The current app registration is `octelium`, the Kubernetes namespace is
`octelium-client`, and Tailscale continues to own the active tailnet ingress
and homelab exit node.

The Argo CD Application installs the official Octelium client Helm chart plus
repo-owned support manifests. The connector is prepared for rootless gVisor
mode, enrolled in Istio ambient mesh, and kept at `replicaCount: 0` until the
external Octelium API, Enterprise package, service catalog, and workload
credential are verified.

## Service Catalog

`docs/examples/octelium/homelab-services.yaml` is the Octelium Cluster resource
catalog. It creates Namespace `homelab`, Policy `homelab-human-web-access`,
workload User `homelab-octelium-client`, and WEB Services for Argo CD, Compass,
Deluge, Grafana, Kiali, LiteLLM, n8n, OctoBot, OpenClaw, Policy Bot, Prowlarr,
Radarr, Sonarr, and `homelab-demo`.

The policy allows authenticated human client sessions to WEB Services in the
`homelab` namespace. The Kubernetes connector serves the same service list with
matching `--scope` flags.

## Enterprise Package

Octelium Enterprise is represented by the `octeliumee` package from
`https://github.com/octelium/octelium-ee`. It installs into an already running
Octelium Cluster with `octops`; it is not Argo CD-synced Kubernetes desired
state and it does not replace the `octelium-client` connector in this homelab.

Current desired package version: `0.22.0`.

The Octelium Cluster domain is `octelium.stinkyboi.com`, which makes the client
contact `octelium-api.octelium.stinkyboi.com`. The Istio wildcard certificate
requests both `octelium.stinkyboi.com` and `*.octelium.stinkyboi.com`; the
one-level `*.stinkyboi.com` wildcard alone is not enough for the API hostname.

Install or upgrade with:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0

scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

The operator workstation needs `octops` `v0.29.0` or later and kubeconfig
access to the Octelium Cluster. Keep commercial or production license material
outside git; add only safe references or secret contracts here.

## Bootstrap Access

When DNS or VPN access to the Octelium Cluster is not available yet, bootstrap
the UI and API through a local port-forward to the Octelium Cluster ingress:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

On the bootstrap workstation only, add temporary host entries for:

```text
octelium.stinkyboi.com
portal.octelium.stinkyboi.com
octelium-api.octelium.stinkyboi.com
```

Then run `octelium login --domain octelium.stinkyboi.com`, apply
`docs/examples/octelium/homelab-services.yaml`, create the
`homelab-octelium-client` credential, store it in SSM, and sync the Argo CD
Application. Remove the temporary host entries after real DNS or the first VPN
path reaches the same Octelium ingress.

## Secret Contract

`octelium-client-auth` reads `/homelab/octelium/client-auth-token` from AWS SSM.
The token is created with `octeliumctl create cred --user
homelab-octelium-client homelab-octelium-client` and must stay outside git.

## Isolation

The connector service-account principal is:

```text
cluster.local/ns/octelium-client/sa/octelium-client
```

Protected Istio ambient workloads that Octelium serves must allow that
principal in their `AuthorizationPolicy`. Workloads with Kubernetes
`NetworkPolicy` should also allow the `octelium-client` namespace, but that is
intent-only while kube-flannel remains the CNI.

## Full Cluster Gate

A full in-homelab Octelium Cluster is not modeled yet. The official existing
Kubernetes install path needs `octops init`, Multus, node labels, PostgreSQL,
Redis, DNS, and TLS. Treat that as a separate platform design before any live
cluster mutation.

## Validation

Render the Kubernetes side with:

```sh
kubectl kustomize clusters/homelab/apps/octelium
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
scripts/octelium-enterprise-package.sh --help
```

After activation, confirm External Secrets, the service catalog, and the
connector Deployment in `octelium-client`. Activate the connector only after
`https://octelium-api.octelium.stinkyboi.com` serves the Octelium API, not a
generic Istio `404` or gRPC `Unimplemented` response. Stop the connector by
returning `replicaCount` to `0`.

Rollback for the Enterprise package is an Octelium package operation, not an
Argo CD sync. Update the desired package version in this runbook first, then
run the wrapper with the intended `--version` and `--upgrade` flags.

## Failure Notes

If Argo CD is `Synced` but `Degraded`, inspect the child pods and events before
changing the Application. On June 6, 2026 the first rollout degraded because the
Podinfo demo had only `args: [--port=9898]`, which made containerd try to
execute the flag as the binary. The image's upstream Dockerfile sets
`WORKDIR /home/app` and `CMD ["./podinfo"]`, so the explicit command must be
`./podinfo` when passing custom args.

The first rollout also started the connector before the external Octelium API
was verified. The nested Octelium domain makes the client call
`octelium-api.octelium.stinkyboi.com`, so certificate coverage for
`*.octelium.stinkyboi.com` must remain in place. The stable GitOps state keeps
`replicaCount: 0` until the real Octelium API/package path is ready and the
nested API hostname serves Octelium instead of a generic Istio `404` or gRPC
`Unimplemented` response.
