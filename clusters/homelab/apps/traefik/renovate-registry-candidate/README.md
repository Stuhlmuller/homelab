# Hosted Renovate private registry candidate

The candidate is a standalone Kustomization. The relay Deployment starts at
zero replicas, with an offline check guarding its separation from the active
Traefik Application.

The proposed tailnet policy adds one runner tag, `tag:homelab-ci-renovate`,
and one destination tag, `tag:homelab-harbor-registry`. Both enrollment keys
would belong to the existing administrator-owned Tailscale module. The runner
key would be reusable and ephemeral, and the relay key single-use and
persistent. An authorized Tailnet Lock signer signs each key before it enters
its protected credential store. Bind the runner key only to the companion
repository's `renovate-production` environment with a main-only deployment
policy. The current OIDC enrollment resources are dormant under Tailnet Lock.

The only new runner grant would be TCP 443 to the dedicated destination tag.
The companion runner obtains the exact tagged peer IP from authenticated
Tailscale status with tailnet DNS and subnet routes disabled. It maps
`harbor.stinkyboi.com` only for the job, keeping the registry URL, TLS SNI, and
token realm intact. The job maps that hostname to the authenticated peer IP
and reaches only the dedicated registry listener.

The relay uses raw-TCP Tailscale Serve on private port 443 and forwards to a
loopback Traefik listener. That listener accepts only Harbor's SNI and passes
TLS unchanged to the existing `traefik-registry` Service. Ambient Istio
authorizes the relay's dedicated ServiceAccount only at destination port 9443.
That listener permits OCI paths and token exchange. It serves the existing
Harbor certificate and forwards the Authorization header.

An activation change must declare how the signed enrollment Secret and the
pre-created, persistent state Secret are provisioned. The candidate Role can
read and update only its one state Secret. Only the Tailscale container mounts
the projected token. Prove that its state survives a restart and the exact
node remains signed. Then prove certificate validation, the anonymous OCI
challenge, token routing and an eligible read-only lookup, along with denial
at the shared ingress, Kubernetes API and non-registry Harbor paths.
