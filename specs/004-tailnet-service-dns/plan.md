# Implementation Plan: Private Tailnet Service DNS

**Branch**: `codex/tailnet-service-dns` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

## Summary

Deploy a separate CoreDNS instance with the k8s_gateway plugin. It watches only the explicitly labeled `traefik-private` LoadBalancer Service; that Service's reviewed `coredns.io/hostname` annotation
names the approved private hosts. A and AAAA answers follow the Service's Tailscale published IP, so no DNS record writer or stateful DNS database is needed. A CoreDNS `view` handles A/AAAA privately
and forwards other query types to public resolvers. Unmatched A/AAAA names also forward, preserving unrelated public hosts. Traefik remains the HTTPS, authentication, and path-routing owner.

The resolver is published as a Tailscale LoadBalancer on UDP and TCP 53. Reuse the operator-owned `tag:homelab-ingress` and existing member grant, while giving the DNS proxy its own `homelab-dns`
hostname, Service and tailnet IP. Sign that distinct proxy under Tailnet Lock. Deploy and verify the resolver before the owner enters its observed tailnet IPv4 as the restricted nameserver for
`stinkyboi.com`. The 27 public address records are retired only after that handoff and the existing cutover checks; this task stops at the handoff.

## Technical Context

**Language/Version**: Kubernetes YAML, Helm values, HCL, Python 3 for focused validators/operator utilities; upstream k8s_gateway 1.9.0 / Helm chart 4.0.0 with CoreDNS 1.14.7.

**Primary Dependencies**: Tailscale Kubernetes Operator 1.102.3, Argo CD 3.4.2 multi-source/OCI, Traefik 3.7.14, Tailscale Terraform provider 0.29.2, Cloudflare API helper already in repo.

**Storage**: None for DNS answers. Tailscale operator owns its proxy identity state; the resolver reads Kubernetes Service status.

**Testing**: Chart render, Kustomize build, focused Python tests for approval parity and retirement guard, policy/Terragrunt gates, direct UDP/TCP DNS, normal OS DNS and HTTPS acceptance after owner handoff.

**Target Platform**: Talos Kubernetes homelab; ordinary Tailscale clients; DNS over UDP/TCP 53.

**Project Type**: Declarative platform service plus guarded cutover tooling.

**Performance Goals**: The resolver advertises a 30-second TTL/cache maximum. Initial live registration is verified directly; observe add/change/remove convergence on the first later reviewed name change. A repo-owned read-only check verifies direct UDP/TCP queries through the resolver's tailnet IP and supports incident diagnosis and recovery.

**Constraints**: Exact 27-name migration baseline including apex and one-label Cordium wildcard; IPv4-only Traefik ingress status today; preserve unrelated public DNS and apex MX/TXT/CAA; no automatic publication from ordinary Services or Compass discovery Ingresses; no public record retirement before verified tailnet DNS handoff; fail closed after retirement.

**Scale/Scope**: One selected ingress Service, 27 approved names, one resolver Service and two stateless resolver replicas behind one Tailscale proxy.

## Constitution Check

`.specify/memory/constitution.md` is an unratified template. The operative repository gates are in `AGENTS.md` and the onboarding/validation guides:

| Gate | Design result |
| --- | --- |
| Desired state in repository; no ad hoc live mutation | Pass: Terragrunt registers Argo Application; Argo owns chart, namespace and manifests; public retirement uses reviewed repo helper. |
| Preserve ingress and access restrictions | Pass: DNS maps to the existing private Traefik Service; Fleet, Harbor, native API and Funnel contracts remain unchanged and are acceptance checks. |
| Public repo secret boundary | Pass: no TSIG, DNS DB, token, kubeconfig or certificate added. |
| Image provenance and strict Harbor mirrors | Conditional: Codeberg image must be added to the trusted publisher/mirror path, published and verified before the consuming app reaches `main`. |
| Validation before live changes | Pass when chart/Kustomize, approval/policy tests and relevant Terragrunt plan succeed; record unavailable live checks. |
| Reviewable public DNS cutover | Pass: keep current A/AAAA/CNAME until owner DNS handoff and checks; retire only selected names after baseline and TTL review. |

No constitution principle is asserted from the placeholder file. The image publication gate is an ordered prerequisite, not a waived violation.

## Design

1. **Approval source**: Put the comma-separated approved names on `traefik-private` via `coredns.io/hostname` and a dedicated private-DNS label. The Traefik route and Service annotation are one
   reviewed exposure change; the resolver controller syncs in-memory answers from the Service watch, without a separate record edit. A permanent validator compares the annotation with explicit private
   Traefik host rules; an explicit one-time migration check compares it with the 27-name baseline before first rollout. One-label Cordium wildcard is expanded for an actual lookup. Future reviewed
   route changes update that exposure declaration without editing the baseline. Never watch Ingress, HTTPRoute, arbitrary Services, or Compass catalog objects.
2. **Answer path**: The first `.:53` CoreDNS server block uses `view` for A/AAAA, then k8s_gateway with `resources Service`, the private label selector, `loadBalancerAddressPreference ip`, a short TTL
   and `fallthrough`, then `forward` to `1.1.1.1`/`1.0.0.1`. The last `.:53` block forwards other types to public DNS. Explicit public upstreams avoid a kube-dns rewrite/loop. Query tests must prove
   the apex private A, approved AAAA NODATA, public apex MX/TXT, and public unrelated A. On a later removed name, verify the private authoritative answer disappears; during overlap the old public
   record can still appear through fallthrough, so public retirement is a separate gate.
3. **Tailnet exposure**: Chart Service has `loadBalancerClass: tailscale`, the distinct hostname `homelab-dns`, the existing operator-owned `tag:homelab-ingress`, and both UDP/TCP 53. Two CoreDNS Pods
   use probes/resources and restricted Pod security. The existing `autogroup:member` wildcard grant permits member DNS traffic without a policy edit; restricted CI tags receive no new grant. Extend
   the fixed Tailnet Lock signing utility to verify and sign this proxy. A healthy Kubernetes Service without a signed, reachable proxy is not accepted. A repo-owned read-only check queries the
   observed tailnet IP over UDP and TCP and compares approved A answers with the private Traefik Service; use it at handoff and during recovery.
4. **Supply chain**: Pin the public OCI chart to version `4.0.0` (observed OCI digest `sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7`) and the Codeberg image by index digest
   (`sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4`). Use a chart digest target revision if the Argo render validates it; otherwise keep the repository's exact-version chart
   pattern and verify the digest in the publication review. Argo CD pulls the chart; nodes pull a direct
   `harbor.stinkyboi.com/mirror/codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4` reference only after publication. Add Codeberg to
   the reviewed publisher allowlist and catalog, plus the Talos registry map required by coverage checks. Add a fixed one-image `dns` publisher scope; the existing full-catalog run fails on an
   unrelated LiteLLM index. Update its workflow/policy pins with the publisher change. Publish and verify DNS before merging the consuming app; this direct Harbor reference does not require applying
   the Talos mirror map first. GHCR `ghcr.io/k8s-gateway/k8s_gateway:1.9.0` returned manifest unknown.
5. **Delivery and boundary**: Add a `platform/tailnet-dns` source, `tailnet-dns` namespace, explicit Terragrunt stack/Application, and AppProject OCI source allowance. Keep cluster-internal
   `platform/dns` untouched. Record the resolver's actual Service IP only after read-only live inspection; the owner applies a restricted `stinkyboi.com` tailnet nameserver (including the exit-node
   option if used). Do not set a global nameserver or change tailnet DNS automatically.
6. **Public retirement**: Extend the existing Cloudflare helper with a guarded all-27 retirement/readback path that cannot run before verified client and off-tailnet impact evidence. Remove public
   A/AAAA/CNAME only for approved names; keep unrelated records and types. Disable its old automatic publication mode for the retired set so a later run cannot recreate those records. After prior
   maximum TTL, verify public absence, normal-client private answers, route restrictions, Harbor pulls, native API and callbacks. Resolver-outage rollback restores private service health only;
   restoring public app records would reverse the owner's private-DNS policy and is outside this feature.

## Project Structure

```text
clusters/homelab/platform/tailnet-dns/   # namespace, chart values, supporting declarations/runbook
clusters/homelab/apps/traefik/values.yaml # selected Service hostname annotation/label
IaC/stacks/tailnet-dns/stack.hcl           # Argo multi-source registration
IaC/terragrunt.stack.hcl                  # generated unit index
clusters/homelab/argocd/self-management/appproject.yaml
scripts/config/tailscale-policy.json      # existing tag ownership/member grant verified by tests
scripts/config/harbor-images.json         # pinned DNS image source
scripts/tailscale-ingress-sign.py         # fixed proxy identity/signature contract
scripts/tailnet-dns-check.py              # read-only direct UDP/TCP and approved-answer check
scripts/tailscale-private-dns.sh          # guarded retirement (not executed before handoff)
scripts/ci/                               # narrow DNS declaration/cutover tests
docs/networking-tailnet-ingress.md        # tailnet DNS setting, recovery and rollback
openwiki/                                  # affected topology/inventory/validation note after source change
```

**Structure Decision**: Add the resolver as a platform Application; keep one reviewed Traefik Service as the only DNS publication source. Use the existing Cloudflare and Tailnet Lock utilities rather than adding a DNS database or a second writer.

## Ordered Delivery

1. Publish the pinned Codeberg image through the reviewed one-image Harbor `dns` scope after its prerequisite publisher/policy change. Do not merge a consuming app while strict Talos mirrors cannot pull it.
2. Merge and apply the resolver, approval annotation, signing and validation changes through normal protected PR/Terragrunt/Argo paths. Verify the existing tailnet policy grants; preserve all current public app records.
3. Sign the new proxy with the trusted Tailnet Lock signer; read the exact Service and peer IP; run the read-only check from that signer Mac to prove UDP/TCP 53, all 27 answers, apex mail records and
   unrelated public names. Prove direct reachability from an ordinary tailnet member and verify HTTPS entry points. The permanent declaration test covers add/change/remove; observe live convergence on
   the first later reviewed name change.
4. **User handoff/pause**: give the owner the verified IPv4 and the restricted `stinkyboi.com` setting. Wait for the owner's tailnet DNS change and normal OS client acceptance.
5. Later, after live baseline and explicit off-tailnet apex/Cordium impact acceptance, run the guarded public-record retirement through reviewed desired state; wait old TTL, recheck all contracts, and recover private resolver health through declared state if needed.

## Post-Design Constitution Check

The design retains every operative gate above. The release blocker is image publication/mirror coverage before the consuming Argo source reaches `main`; the public-retirement stage is separately blocked by the owner handoff and live acceptance.
