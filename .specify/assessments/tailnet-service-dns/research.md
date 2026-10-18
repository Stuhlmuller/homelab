# Idea Research: Tailnet service DNS

- **Slug**: tailnet-service-dns
- **Created**: 2026-10-18
- **Evidence confidence (overall)**: medium

## Users & Demand

- The homelab owner requests a tailnet-reachable DNS server and automatic names for Kubernetes services. The owner clarified that private DNS answers are the priority, Traefik may remain, all 27
  current names are in scope, public records for those names should be removed after cutover, and resolver failure should fail closed. This is direct owner input, not observed usage data. [source:
  `intake.md`, `decision.md` (owner clarifications)] (confidence: high; cited)
- No measured DNS maintenance cost, client success rate, or live DNS cutover result was supplied. [source: `problem.md`, `clusters/homelab/apps/traefik/CUTOVER.md`] (confidence: high; cited)

## Prior Art

- The repository declares a fixed inventory of 27 `stinkyboi.com` names for Cloudflare DNS-only A/AAAA records derived from the verified Tailscale ingress Service. The helper preserves unrelated
  records. The cutover runbook distinguishes ingress preflight from DNS cutover, so source alone does not prove these records are live. [source: `scripts/config/tailscale-private-dns.json`,
  `docs/networking-tailnet-ingress.md`, `scripts/tailscale-private-dns.sh`, `clusters/homelab/apps/traefik/CUTOVER.md`] (confidence: high; cited)
- Cluster CoreDNS already discovers `cluster.local` Services and rewrites two application names to the private Traefik Service. It is a cluster-internal resolver today. [source: `clusters/homelab/platform/dns/coredns-configmap.yaml`] (confidence: high; cited)
- ExternalDNS watches Kubernetes sources and updates DNS providers; it is a controller, not a DNS server. Its Service source can derive names from annotations and targets from Service type/status.
  [source: [ExternalDNS](https://kubernetes-sigs.github.io/external-dns/v0.21.0/), [ExternalDNS Service source](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/sources/service/)]
  (confidence: high; cited)
- ExternalDNS documents dynamic updates to BIND9 through RFC 2136 with TSIG, plus PowerDNS and CoreDNS with an etcd backend. The CoreDNS example adds etcd as record storage. These are documented
  precedents, not evidence of a working deployment in this homelab. [source: [ExternalDNS RFC 2136](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/rfc2136/),
  [ExternalDNS PowerDNS](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/pdns/),
  [ExternalDNS CoreDNS and etcd](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/coredns-etcd/)] (confidence: high; cited)
- ExternalDNS recommends a stable record owner ID and dry-run review. With its RFC 2136 provider, record listing for synchronizing deletions requires AXFR; without it, deletion reconciliation is
  unavailable. [source: [ExternalDNS](https://kubernetes-sigs.github.io/external-dns/v0.21.0/), [ExternalDNS RFC 2136](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/rfc2136/)]
  (confidence: high; cited)

## Market & Context

- Tailscale supports a restricted nameserver for a matching domain; its documentation does not promise public-DNS fallback when that server lacks an answer. Exit-node users need a separate setting to
  use the restricted resolver. Its Kubernetes Operator supports tailnet Service exposure for TCP/UDP; exact combined TCP+UDP port-53 behavior was not verified.
  [source: [Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale), [Tailscale Kubernetes Operator](https://tailscale.com/docs/kubernetes-operator/ingress)] (confidence: high for
  documented behavior, low for unverified port-53 combination; cited)
- Tailscale notes that publicly published names pointing to tailnet IPs can be looked up by anyone, even though only tailnet members can reach those IPs. Removing public answers changes name visibility, not the tailnet access control itself. [source: [Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale)] (confidence: high; cited)
- ExternalDNS's Service source needs an approved hostname declaration or template. A normal application's ClusterIP is not a tailnet-reachable target; a tailnet-exposed LoadBalancer publishes its
  assigned address. This does not establish that watching arbitrary app Services would reproduce the current Traefik route inventory.
  [source: [ExternalDNS Service source](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/sources/service/), `clusters/homelab/apps/traefik/routes.yaml`] (confidence: high; cited inference)
- The existing alternative is to keep public DNS records pointing at a tailnet-only ingress IP and maintain the explicit hostname list; this already has a declared repository workflow. [source: `docs/networking-tailnet-ingress.md`, `scripts/tailscale-private-dns.sh`] (confidence: high; cited)
- Kubernetes Ingress assigns HTTP/HTTPS traffic to backends by rules and needs a controller; DNS records alone do not implement those routes. [source: [Kubernetes Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)] (confidence: high; cited)

## Data & Constraints

- The repository has 27 private DNS inventory entries and 28 Traefik routers, including separate private, Funnel callback, and Harbor registry listeners. These are counts of declared entries, not
  measured traffic. [source: `scripts/config/tailscale-private-dns.json`, `clusters/homelab/apps/traefik/routes.yaml`, `clusters/homelab/apps/traefik/values.yaml`, `scripts/ci/traefik-routes-test.py`]
  (confidence: high; cited)
- Traefik currently terminates the `stinkyboi.com` certificate, routes private apps, denies Fleet setup paths, restricts public callback paths, and limits Talos Harbor pulls to OCI/token endpoints.
  Replacing the data path touches more than DNS publication. [source: `clusters/homelab/apps/traefik/README.md`, `clusters/homelab/apps/traefik/routes.yaml`,
  `clusters/homelab/apps/traefik/certificate.yaml`] (confidence: high; cited)
- The declared Tailscale ingress Service is IPv4-only; the repo records one published tailnet IPv4 destination and explicitly leaves AAAA empty. The documented DNS workflow derives addresses from Service status. [source: `docs/networking-tailnet-ingress.md`, `clusters/homelab/apps/traefik/values.yaml`] (confidence: high; cited)
- The repo separates private `stinkyboi.com` names from public `*.ts.net` callbacks and a planned public Mastodon host. A restricted nameserver for all of `stinkyboi.com` would receive queries for
  both private and any unrelated names under that suffix; preserving their answers needs investigation.
  [source: `docs/networking-tailnet-ingress.md`, [Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale)] (confidence: high; cited inference)
- The current Tailscale IaC declares policy and identity resources, but the inspected repo paths contain no tailnet nameserver setting. The repository prohibits manual cloud changes for desired state,
  so the delivery specification must account for a repository-owned DNS-setting path. [source: `IaC/modules/tailscale-access/main.tf`, `scripts/config/tailscale-policy.json`, `AGENTS.md`] (confidence:
  medium; cited inspection)
- Compass Ingress objects use a discovery-only class and route every declared host to the Compass Service. An unfiltered Ingress source would misidentify them as application routing declarations. [source: `clusters/homelab/apps/compass/ingress-discovery.yaml`, `clusters/homelab/apps/traefik/README.md`] (confidence: high; cited)
- The existing cutover demands normal client DNS and HTTPS checks, Fleet access, per-node Harbor pulls, native API behavior, and public callback checks before final retirement. The recorded ingress preflight explicitly does not prove DNS cutover. [source: `clusters/homelab/apps/traefik/CUTOVER.md`] (confidence: high; cited)
- Tailscale's standalone layer-3 exposure uses one proxy Pod; its documented high-availability mode uses multiple active proxies. This is an availability choice for a DNS endpoint, not evidence that the current homelab has such a deployment. [source: [Tailscale Kubernetes Operator](https://tailscale.com/docs/kubernetes-operator/ingress)] (confidence: high; cited)

## Evidence Against the Idea

- DNS automation does not provide the current HTTPS hostname routing, certificate handling, path restrictions, or distinct private and public listeners. Removing Traefik without another data path
  would break those declared behaviors. [source: [Kubernetes Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/), `clusters/homelab/apps/traefik/routes.yaml`,
  `clusters/homelab/apps/traefik/values.yaml`] (confidence: high; cited inference)
- Dynamic publication could replace the explicit 27-name inventory, but the repo currently uses that inventory as a review boundary and deliberately excludes some retired names. Automatic discovery
  needs a defined exposure boundary before its benefit can be assessed. [source: `scripts/config/tailscale-private-dns.json`, `clusters/homelab/apps/traefik/README.md`] (confidence: medium; cited
  inference)
- An in-cluster resolver used by tailnet clients would depend on cluster and tailnet availability for those names. No observed uptime data or failover requirement was supplied. [source: [Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale), `intake.md`] (confidence: medium; cited inference)
- The selected public-record retirement includes the apex and Cordium wildcard, both still present in retained legacy public routing. Off-tailnet callers of those names will lose DNS access unless
  they migrate; Mastodon remains a separate public host under the same zone. Name-by-name use must be checked before retirement. [source: `scripts/config/tailscale-private-dns.json`,
  `clusters/homelab/apps/octelium-public/configmap.yaml`, `clusters/homelab/apps/mastodon/README.md`, `decision.md` (owner clarification)] (confidence: medium; cited inference)

## Gaps & Open Questions

- [NEEDS CLARIFICATION: Which Kubernetes objects may publish names, and who approves a new tailnet-visible service?]
- [NEEDS CLARIFICATION: How should the private resolver answer public or unrelated `stinkyboi.com` names, including the apex and future services?]
- [NEEDS CLARIFICATION: What recovery time and resolver redundancy are required under the confirmed fail-closed policy, including exit-node clients?]
- [NEEDS CLARIFICATION: Which cutover checks prove current live DNS and client behavior before public records change?]

## Sources

- `intake.md` (local assessment; user request)
- `scripts/config/tailscale-private-dns.json`, `scripts/tailscale-private-dns.sh`, `scripts/ci/traefik-routes-test.py`, `docs/networking-tailnet-ingress.md` (repository source)
- `clusters/homelab/platform/dns/coredns-configmap.yaml`, `clusters/homelab/apps/traefik/README.md`, `clusters/homelab/apps/traefik/routes.yaml`, `clusters/homelab/apps/traefik/values.yaml`, `clusters/homelab/apps/traefik/certificate.yaml`, `clusters/homelab/apps/traefik/CUTOVER.md` (repository source)
- `clusters/homelab/apps/compass/ingress-discovery.yaml`, `clusters/homelab/apps/octelium-public/configmap.yaml`, `clusters/homelab/apps/mastodon/README.md`, `IaC/modules/tailscale-access/main.tf`, `scripts/config/tailscale-policy.json`, `AGENTS.md` (repository source)
- [Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale) (host: tailscale.com; policy: confirmed-by-user)
- [Tailscale Kubernetes Operator](https://tailscale.com/docs/kubernetes-operator/ingress) (host: tailscale.com; policy: confirmed-by-user)
- [Kubernetes Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/) (host: kubernetes.io; policy: confirmed-by-user)
- [ExternalDNS](https://kubernetes-sigs.github.io/external-dns/v0.21.0/) (host: kubernetes-sigs.github.io; policy: confirmed-by-user)
- [ExternalDNS Service source](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/sources/service/) (host: kubernetes-sigs.github.io; policy: confirmed-by-user)
- [ExternalDNS RFC 2136](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/rfc2136/) (host: kubernetes-sigs.github.io; policy: confirmed-by-user)
- [ExternalDNS PowerDNS](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/pdns/) (host: kubernetes-sigs.github.io; policy: confirmed-by-user)
- [ExternalDNS CoreDNS and etcd](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/tutorials/coredns-etcd/) (host: kubernetes-sigs.github.io; policy: confirmed-by-user)
