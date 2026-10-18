# Idea Intake: Tailnet service DNS

- **Slug**: tailnet-service-dns
- **Created**: 2026-10-18
- **Source**: user-provided text
- **Type**: exploration

## Idea (as captured)

> I want to deploy a DNS server to the k8s homelab and then point my tailscale tailnet DNS to the tailnet IP of this DNS server, from there, I want to resolve my stinkyboi.com services from that dns
> server. Is there a service to deploy that allows me to dynamically register the DNS of my k8s services so that they will resolve as they do now with traefik? We would replace traefik with this new
> self-hosted DNS server.

## Restated

Deploy a self-hosted DNS server reachable over the tailnet for `stinkyboi.com`, and dynamically register names for selected Kubernetes services. Explore whether this setup can replace the current Traefik role.

## Origin & Context

- **Raised by**: homelab owner
- **Trigger**: [NEEDS CLARIFICATION: What problem with the current DNS and Traefik setup prompted this idea?]
- **Related repository paths**: `clusters/homelab/apps/traefik/`, `clusters/homelab/platform/dns/`, `scripts/config/tailscale-private-dns.json`

## First-Glance Unknowns

- [NEEDS CLARIFICATION: Should tailnet DNS answer the full `stinkyboi.com` zone or only selected private names?]
- [NEEDS CLARIFICATION: Should names register from Kubernetes Services, HTTP routes, or an explicit approved inventory?]
- [NEEDS CLARIFICATION: Should existing HTTPS hostnames, certificates, path restrictions, public callbacks, and Harbor node image pulls keep working the same way?]
- [NEEDS CLARIFICATION: What should happen to DNS resolution if the cluster or tailnet DNS endpoint is unavailable?]
