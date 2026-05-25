# Tailnet Ingress

Istio is the reverse proxy for this onboarding. Tailscale is the reachability
layer. The first rollout is internal-only: no Tailscale Funnel routes are
enabled.

## Initial DNS Assumption

The repository expects one initial DNS or tailnet naming setup that covers all
internal app routes. For this homelab, `*.stinkyboi.com` must resolve to the
Tailscale-exposed Istio ingress address from tailnet clients. This feature does
not add or edit public DNS records after that initial setup.

Because no DNS provider resources are added in this repository, external DNS
infrastructure is unaffected by this change. If DNS becomes repo-managed later,
that must be added through a separate Terragrunt/OpenTofu entry point.

## First-Rollout Route Inventory

| App | HTTPS host | Public Funnel |
|-----|------------------|---------------|
| argocd | `https://argocd.stinkyboi.com` | disabled |
| prometheus | `https://prometheus.stinkyboi.com` | disabled |
| grafana | `https://grafana.stinkyboi.com` | disabled |
| deluge | `https://deluge.stinkyboi.com` | disabled |
| prowlarr | `https://prowlarr.stinkyboi.com` | disabled |
| radarr | `https://radarr.stinkyboi.com` | disabled |
| sonarr | `https://sonarr.stinkyboi.com` | disabled |
| litellm | `https://litellm.stinkyboi.com` | disabled |
| openclaw | `https://openclaw.stinkyboi.com` | disabled |
| tines | `https://tines.stinkyboi.com` | disabled |

Istio terminates HTTPS with the `stinkyboi-com-tls` certificate in
`istio-system`. cert-manager requests this wildcard certificate through the
`letsencrypt-cloudflare` ClusterIssuer, which uses DNS-01 challenges for
`stinkyboi.com` and reads its Cloudflare token from the External Secrets-managed
`cloudflare-api-token` Secret in the `cert-manager` namespace. The
`homelab-selfsigned` issuer remains available only as a local fallback and is
not referenced by the ingress wildcard certificate.

Validation on 2026-05-24 found no enabled first-rollout Funnel routes. The
Istio gateway and every VirtualService route manifest are annotated with
`homelab.rst.io/public-funnel: "false"`.

## Homelab VPN Exit Node

Tailscale also provides the homelab VPN exit path. The `tailscale` Argo CD
Application installs the upstream Tailscale Kubernetes Operator and applies the
repo-owned `homelab-exit-node` `Connector` from
`clusters/homelab/apps/tailscale/exit-node-connector.yaml`.

The connector is cluster-scoped, creates one operator-managed proxy device, and
advertises that device as a Tailscale exit node with hostname
`homelab-exit-node` and tag `tag:k8s`. Tailnet clients can select that device as
their exit node to route internet-bound traffic through the homelab cluster
egress path.

This repository cannot approve tailnet routes by itself. The tailnet policy must
allow `tag:k8s-operator` to own `tag:k8s`, and either auto-approve exit-node
advertisement for `tag:k8s` with `autoApprovers.exitNode`, or rely on an admin
manually approving `homelab-exit-node` in the Tailscale Machines page after
sync.

Validate the exit node after Argo CD syncs Tailscale:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

Expected result: the connector reports exit-node status, its ready condition is
true, and a single Tailscale proxy Pod is running. Then select
`homelab-exit-node` on a client and verify the public egress IP changes to the
homelab network. Keep local-network access enabled on clients that still need
nearby LAN access while using the exit node.

## Future Funnel Webhook Exception Template

Future public exposure must be limited to webhook paths and reviewed separately.

```text
Owning application:
Public path:
Purpose:
Source system:
Authentication or signature check:
Tailscale Funnel hostname:
Rollback command:
Data exposed:
```
