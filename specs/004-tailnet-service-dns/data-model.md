# Data Model: Private Tailnet Service DNS

No application database is added. These entities describe repository declarations, observed Kubernetes/Tailscale state and cutover evidence.

## Approved private name

| Field | Source | Rule |
| --- | --- | --- |
| `name` | `traefik-private` Service `coredns.io/hostname` annotation | FQDN under `stinkyboi.com`; exact host or `*.cordium.stinkyboi.com`; unique; reviewed. |
| `route` | `clusters/homelab/apps/traefik/routes.yaml` | Must match an HTTPS router on the private `websecure` listener; no Funnel/registry-only or Compass discovery host. |
| `target` | `traefik-private.status.loadBalancer.ingress[*].ip` | Use published, reachable Tailscale IPv4 only; do not infer from all peer addresses. |
| `ttl` | Resolver plugin values | 30 seconds; live watch convergence is observed at initial registration and on the first later reviewed name change. |

Initial membership equals the 27 `hostnames` in `scripts/config/tailscale-private-dns.json`. The four `retired_hostnames` never become approved names. This JSON file remains a migration snapshot, while the Service annotation is the live approval source.

State: **declared** (reviewed annotation + matching route) → **published** (selected Service has ready status IP and resolver returns it) → **retired** (annotation/route removed and old answer expires). If the Service address disappears, publication becomes unavailable; no stale static address is substituted.

## Resolver endpoint

| Field | Source | Rule |
| --- | --- | --- |
| `service` | Resolver chart LoadBalancer Service | One `tailscale` class Service with UDP and TCP 53. |
| `tailnet_name` | Service annotation | Fixed `homelab-dns` peer name. |
| `tailnet_ip` | Live Service status and signed proxy peer | Record actual matching IPv4 after rollout; pass it to owner only after direct queries work. |
| `trust` | Tailnet policy and Lock status | Existing operator-owned `tag:homelab-ingress` and member wildcard grant; distinct signed proxy identity and public node/rotation keys. |

State: **declared** → **proxy ready** → **signed and reachable** → **owner handoff**. A Kubernetes Ready Service alone does not advance the state.

## DNS answer

| Input | Source | Expected answer |
| --- | --- | --- |
| Approved name, A | k8s_gateway Service watch | Authoritative A equal to the current Traefik private Service IPv4. |
| Approved name, AAAA | k8s_gateway Service watch | NODATA while the Traefik Service is IPv4-only. |
| Unrelated `stinkyboi.com` name, A/AAAA | Public forward | Existing public answer or public NXDOMAIN. |
| Any name, MX/TXT/CAA/SOA/NS | Public forward view | Public zone's answer, including apex mail/security records. |
| Approved name after public retirement, missing resolver/declaration | No usable private/public address | Fail closed; never return a stale public application address. |

## Public record and cutover evidence

The existing Cloudflare utility manages only selected A/AAAA/CNAME records. The live record baseline stores type, name, content, proxy flag and TTL privately during cutover; unrelated names and other record types are never targeted.

The evidence record includes reviewed main SHA, 27-name set, old public TTL maximum, resolver Service/peer identity and IP, Tailnet Lock signature, direct UDP/TCP answers, owner tailnet DNS change,
normal OS answers, HTTPS/critical client checks, off-tailnet apex/Cordium decision, retirement readback and post-TTL public results. Keep credentials and raw private outputs outside the public
repository.

Cutover states: **public active** → **private resolver verified** → **owner DNS handoff complete** → **normal clients accepted** → **public retirement permitted** → **cache expiry verified**. Any failed gate holds its current state. Rollback restores reviewed desired state and retests routes; it does not loosen access policies.
