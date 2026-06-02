# Octelium

Tags: #runbooks #octelium #networking #secrets

Source: `docs/octelium.md`

## Model

Octelium is introduced as a parallel client bridge, not as a replacement for
Tailscale. The current app registration is `octelium`, the Kubernetes namespace
is `octelium-client`, and Tailscale continues to own the active tailnet ingress
and homelab exit node.

The Argo CD Application installs the official Octelium client Helm chart plus
repo-owned support manifests. The Helm values keep `replicaCount: 0` until a
real external Octelium Cluster and workload authentication token exist.

## Demo

`clusters/homelab/apps/octelium/demo.yaml` creates `octelium-demo`, a tiny
ClusterIP HTTP service. `docs/examples/octelium/homelab-demo.yaml` is the
matching Octelium resource example: Namespace `homelab`, workload User
`homelab-octelium-client`, and WEB Service `homelab-demo.homelab` upstreaming
to `http://octelium-demo.octelium-client.svc:8080`.

The client serves `homelab-demo.homelab` with rootless gVisor mode so the
namespace can stay at baseline Pod Security rather than privileged.
`octelium-demo-allow-client` limits demo ingress to the Octelium client pod.

## Secret Contract

`octelium-client-auth` reads `/homelab/octelium/client-auth-token` from AWS SSM.
The token is created with `octeliumctl create cred --user
homelab-octelium-client homelab-octelium-client` and must stay outside git.

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
```

After activation, confirm External Secrets, the demo Service, and the connector
Deployment in `octelium-client`. Stop the connector by returning
`replicaCount` to `0`.
