# Inventory evidence

Read-only snapshot during image-prerequisite implementation. Lifecycle is a
source-backed classification obligation for T006; runtime health alone does not
classify an app as active. No app is activated or repaired by this inventory.

Source entries: 55; live Applications: 56; union: 60.

| Application | Source registration | Live sync/health |
| --- | --- | --- |
| affine | IaC/homelab/us-west-2/apps/affine/stack.hcl | Synced/Healthy |
| argocd-image-updater | IaC/homelab/us-west-2/apps/argocd-image-updater/stack.hcl | absent/absent |
| argocd-self-management | child/bootstrap owner: classify in T006 | Synced/Healthy |
| bazarr | IaC/homelab/us-west-2/apps/bazarr/stack.hcl | Synced/Healthy |
| bulldozer | IaC/homelab/us-west-2/apps/bulldozer/stack.hcl | OutOfSync/Healthy |
| cert-manager | IaC/homelab/us-west-2/apps/cert-manager/stack.hcl | Synced/Healthy |
| compass | IaC/homelab/us-west-2/apps/compass/stack.hcl | Synced/Healthy |
| cordium | IaC/homelab/us-west-2/apps/cordium/stack.hcl | Synced/Healthy |
| cordium-bootstrap | child/bootstrap owner: classify in T006 | Synced/Healthy |
| cordium-local-path-provisioner | child/bootstrap owner: classify in T006 | Synced/Healthy |
| deluge | IaC/homelab/us-west-2/apps/deluge/stack.hcl | Synced/Healthy |
| descheduler | IaC/homelab/us-west-2/apps/descheduler/stack.hcl | Synced/Healthy |
| dispatcharr | IaC/homelab/us-west-2/apps/dispatcharr/stack.hcl | Synced/Healthy |
| external-secrets | IaC/homelab/us-west-2/apps/external-secrets/stack.hcl | Synced/Healthy |
| fleet | IaC/homelab/us-west-2/apps/fleet/stack.hcl | Synced/Healthy |
| grafana | IaC/homelab/us-west-2/apps/grafana/stack.hcl | Synced/Healthy |
| harbor | IaC/homelab/us-west-2/apps/harbor/stack.hcl | Synced/Healthy |
| istio | IaC/homelab/us-west-2/apps/istio/stack.hcl | Synced/Healthy |
| kiali | IaC/homelab/us-west-2/apps/kiali/stack.hcl | Synced/Healthy |
| langfuse | IaC/homelab/us-west-2/apps/langfuse/stack.hcl | Synced/Healthy |
| litellm | IaC/homelab/us-west-2/apps/litellm/stack.hcl | Synced/Healthy |
| live | child/bootstrap owner: classify in T006 | Unknown/Unknown |
| mastodon | IaC/homelab/us-west-2/apps/mastodon/stack.hcl | OutOfSync/Healthy |
| media-postgres | IaC/homelab/us-west-2/apps/media-postgres/stack.hcl | Synced/Healthy |
| metrics-server | IaC/homelab/us-west-2/apps/metrics-server/stack.hcl | Synced/Healthy |
| multica | IaC/homelab/us-west-2/apps/multica/stack.hcl | Synced/Healthy |
| n8n | IaC/homelab/us-west-2/apps/n8n/stack.hcl | Synced/Healthy |
| n8n-postgres | IaC/homelab/us-west-2/apps/n8n-postgres/stack.hcl | Synced/Healthy |
| nfs-subdir-external-provisioner | child/bootstrap owner: classify in T006 | Synced/Healthy |
| nix-builder | IaC/homelab/us-west-2/apps/nix-builder/stack.hcl | Synced/Healthy |
| nofx | IaC/homelab/us-west-2/apps/nofx/stack.hcl | Synced/Healthy |
| octelium | IaC/homelab/us-west-2/apps/octelium/stack.hcl | Synced/Healthy |
| octelium-cluster | IaC/homelab/us-west-2/apps/octelium-cluster/stack.hcl | Synced/Healthy |
| octelium-enterprise | IaC/homelab/us-west-2/apps/octelium-enterprise/stack.hcl | Synced/Progressing |
| octelium-public | IaC/homelab/us-west-2/apps/octelium-public/stack.hcl | Synced/Healthy |
| octelium-storage | IaC/homelab/us-west-2/apps/octelium-storage/stack.hcl | Synced/Healthy |
| openclaw | IaC/homelab/us-west-2/apps/openclaw/stack.hcl | Synced/Healthy |
| openclaw-enterprise | IaC/homelab/us-west-2/apps/openclaw-enterprise/stack.hcl | OutOfSync/Missing |
| openclaw-enterprise-foundation | IaC/homelab/us-west-2/apps/openclaw-enterprise-foundation/stack.hcl | OutOfSync/Missing |
| platform-crossplane | IaC/homelab/us-west-2/apps/platform-crossplane/stack.hcl | Synced/Healthy |
| platform-dns | IaC/homelab/us-west-2/apps/platform-dns/stack.hcl | Synced/Healthy |
| platform-envoy-gateway | IaC/homelab/us-west-2/apps/platform-envoy-gateway/stack.hcl | OutOfSync/Missing |
| platform-gateway-api-crds | IaC/homelab/us-west-2/apps/platform-gateway-api-crds/stack.hcl | absent/absent |
| platform-image-policy | IaC/homelab/us-west-2/apps/platform-image-policy/stack.hcl | Synced/Healthy |
| platform-istio-egress | IaC/homelab/us-west-2/apps/platform-istio-egress/stack.hcl | absent/absent |
| platform-multus | IaC/homelab/us-west-2/apps/platform-multus/stack.hcl | Synced/Healthy |
| platform-network-policy | IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl | OutOfSync/Missing |
| platform-network-policy-canary | IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl | Synced/Healthy |
| platform-network-policy-cleanup | IaC/homelab/us-west-2/apps/platform-network-policy-cleanup/stack.hcl | OutOfSync/Missing |
| platform-storage | IaC/homelab/us-west-2/apps/platform-storage/stack.hcl | Synced/Healthy |
| policy-bot | IaC/homelab/us-west-2/apps/policy-bot/stack.hcl | Synced/Healthy |
| prometheus | IaC/homelab/us-west-2/apps/prometheus/stack.hcl | Synced/Healthy |
| prowlarr | IaC/homelab/us-west-2/apps/prowlarr/stack.hcl | Synced/Healthy |
| radarr | IaC/homelab/us-west-2/apps/radarr/stack.hcl | Synced/Healthy |
| renovate | IaC/homelab/us-west-2/apps/renovate/stack.hcl | Synced/Healthy |
| sonarr | IaC/homelab/us-west-2/apps/sonarr/stack.hcl | Synced/Healthy |
| tailnet-dns | IaC/homelab/us-west-2/apps/tailnet-dns/stack.hcl | Synced/Healthy |
| tailscale | IaC/homelab/us-west-2/apps/tailscale/stack.hcl | Synced/Healthy |
| traefik | IaC/homelab/us-west-2/apps/traefik/stack.hcl | Synced/Progressing |

Prior read-only workload snapshot found zero replicas for AFFiNE, legacy
OpenClaw, Mastodon web/worker/streaming, Bulldozer, Crossplane and nix-builder.
Source intent and still-active components must be reconciled during T006.
Staged Missing Applications and live-only child/bootstrap registrations remain
in the table; no monitor coverage has yet been claimed.
