# Research: AdGuard Tailnet DNS

Planning research completed 2026-11-15. These decisions resolve design unknowns;
execution dependencies remain explicitly unverified. No runtime mutation occurred.

## Source coverage

The installed speckit-plan skill and complete upstream plan command at
`github/spec-kit@a227e38315cd38172b04f2fb8f06ce8b69b38331` were read.
A bounded research agent inspected AdGuard/ESO upstream behavior and reported
version, configuration and image evidence; the coordinator inspected the existing
app, secret, ingress, DNS and apply paths and live prerequisite metadata.

XERJ MCP, CLI and retained local corpus were unavailable. No node was installed
or corpus indexed. The declared peer manifest pins
`kn-lim/homelab@1b88ad5c211113d0526a676aa26cdcd8282644ff`; its recursive GitHub tree
was searched for AdGuard/Tailscale, then these complete cited source files read:

- [Peer AdGuard deployment](https://github.com/kn-lim/homelab/blob/1b88ad5c211113d0526a676aa26cdcd8282644ff/kubernetes/bases/adguardhome/deployment.yaml)
- [Peer serve config](https://github.com/kn-lim/homelab/blob/1b88ad5c211113d0526a676aa26cdcd8282644ff/kubernetes/bases/adguardhome/configmap.yaml)
- [Peer DNS resource](https://github.com/kn-lim/homelab/blob/1b88ad5c211113d0526a676aa26cdcd8282644ff/terraform/_modules/tailscale/dns/main.tf)

Manifest licence review says Unlicense; no peer code is copied in this stage.

## Decisions

### Runtime/image

**Decision:** Pin official AdGuard Home v0.107.80 index digest
`sha256:e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c`.
Research observed amd64 child `sha256:8224eeda45e5c0efe014376f239f67b26e4b73bbb19576da6e576e398f1ea763`
and arm64 child `sha256:198924ddb1cd509677e8101b138f58d985a6f0da6502a2fd0a1910e4b0f942b8`.
Recheck public manifest integrity when preparing publisher input; publication
and actual runtime compatibility are later evidence, not assumed here.

**Rationale:** Current stable release and multi-architecture upstream artifact.
The official image has no USER declaration, but uses nobody-owned directories
and `cap_net_bind_service=+eip` on its binary. Explicit non-root security context
with only NET_BIND_SERVICE avoids assuming capability-free execution works.
**Alternatives:** Unpinned latest rejected; custom image unnecessary; high port
alone does not remove the binary file-capability constraint.

Sources: [release](https://github.com/AdguardTeam/AdGuardHome/releases/tag/v0.107.80),
[Dockerfile](https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.80/docker/build.Dockerfile).

### App/access ownership

**Decision:** Existing `automation` namespace, namespaced `homelab-workloads`
Application, Kustomize Deployment/Recreate, operator LoadBalancer DNS Service,
existing private Traefik for admin. Explicit per-pod ambient opt-out follows
existing targeted-apply pattern; preserve other namespace workloads.
**Rationale:** Existing AppProject and ESO permit automation; avoids new namespace
and privileges. Recreate prevents two writers to cache. Peer uses Recreate and
persistent conf/work, supporting the basic workload shape.
**Alternatives:** Peer NET_ADMIN/TUN sidecar rejected in favor of installed
operator; separate Tailscale UI proxy adds unnecessary device identity; public
Funnel not needed. A new application chart duplicates a small manifest boundary.

### Configuration/credentials

**Decision:** Schema 34 JSON-compatible YAML rendered from an OnChange ESO
Secret with a generated SSM password hashed by Sprig bcrypt. Init validates
hash/structure and writes writable working config. Runtime config is rebuilt on
replacement; work/cache retained on NFS. Secret revision and Pod rollout marker
make rotation explicit.
**Rationale:** AdGuard rewrites its YAML, so read-only active mount is wrong.
Empty users disables auth. Bcrypt random salt would cause needless refresh drift
without OnChange. ESO v2.0.1 imports Sprig functions except environment access;
existing Harbor htpasswd template is local evidence of bcrypt support.
**Alternatives:** Plaintext password in ConfigMap rejected; mutable UI-only source
contradicts repository ownership; a custom bcrypt implementation is unnecessary.

Sources: [Configuration](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration),
[defaults](https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.80/internal/home/config.go),
[schema](https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.80/internal/configmigrate/configmigrate.go),
[ESO functions](https://github.com/external-secrets/external-secrets/blob/v2.0.1/runtime/template/v2/template.go),
local aws-ssm-parameters module and Harbor ExternalSecret.

### Filtering/upstreams

**Decision:** Default AdGuard DNS filter
`https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt`, updates every
24 hours, protection enabled. Null-IP blocking with short blocked TTL; disable
query log, file query log and statistics. General upstreams remain Cloudflare
malware DNS IPs. Conditional private-domain forwarding to the existing cluster
resolver; init resolves its Service name to IPv4 before writing numeric upstream.
No fallback resolver list, DHCP, encrypted-DNS server or client-discovery features.
**Rationale:** Default list addresses requested ads; separate private upstream
preserves existing split-zone authority. Explicit upstream IPs avoid recursive
bootstrap through the new global DNS policy. Existing cache survives failed
refresh; empty-cache initial startup still must prove nonempty active rules.
**Alternatives:** Replacing private resolver unnecessarily increases cutover scope;
public alternate global DNS defeats filtering; broad parental lists not requested.

Sources: upstream Configuration/defaults above;
[filter refresh](https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.80/internal/filtering/filter.go).
Runtime fixtures must prove conditional failure does not reach general upstreams
and verify configured blocking responses, including AAAA.

### DNS cutover

**Decision:** Separate verified deployment from observed-IP DNS commit/application.
Keep the single existing tailscale_dns_configuration resource, global
use_with_exit_node=true and override_local_dns=true; preserve split DNS/MagicDNS.
Constrain saved-plan apply with code and negative tests, not prose-only claims.
**Rationale:** Operator-assigned address and peer identity are runtime facts.
Provider supports complete DNS configuration and warns against mixing separate
DNS resources. Exit-node use flag requires client >=1.88.1.
**Alternatives:** Guessed IP, competing provider resource, ad hoc API write,
workload CI administrator privilege rejected.

Source: [provider 0.29.2 DNS resource](https://github.com/tailscale/terraform-provider-tailscale/blob/v0.29.2/docs/resources/dns_configuration.md)
read in full; local tailscale-access runbook and targeted CI apply paths.

## Observed prerequisites and limitations

- Configured kubectl context `homelab` works; read-only namespace and Application
  queries succeeded. Default home kubeconfig absence does not mean no access.
- automation, tailscale and tailnet-dns namespaces exist; nfs-default exists.
- tailscale, tailnet-dns, external-secrets and platform-storage were Synced/Healthy.
- Traefik Application was Synced/Progressing, last operation Succeeded; actual
  Deployment was 1/1 available and its Pod Running. Application-level discrepancy
  remains an explicit rollout preflight dependency; no cause is asserted.
- Existing private DNS Service publishes 100.71.150.27 and ClusterIP 10.97.225.203.
  These are observed existing values, not the future AdGuard endpoint.
- ESO ClusterSecretStore Ready and includes automation in its namespace allowlist.
- Local administrator OAuth files are absent.
  No credentials, enrollment or access-policy change was attempted.
- Planning can finish and source work can continue. Administrator DNS
  apply and actual-client acceptance require the existing authorized operator
  path, or a concrete handoff once the artifacts are ready.

All design decisions are resolved. Image execution, secret render, recovery,
policy enforcement and live rollout are validation tasks, not claimed results.


### Device identity schema

**Decision:** Match the connected client's actual network-map peer with proxy
Self status and Kubernetes ownership. Stable device ID, numeric NodeID, public
key, hostname, tag and addresses must agree. Require online, unexpired identity
and reject missing, ambiguous or changing observations.
**Rationale:** The operator assigns the address; hostname-only or IP-only
matching cannot establish the exact declared endpoint. Device reachability also
does not prove effective DNS, filtering or administration behavior, so retain
all functional and normal-client checks.
**Alternatives:** Skipping identity verification, inventing evidence, reusing
stale receipts and relaxing resource ownership are rejected.

Source: [Tailscale PeerStatus](https://github.com/tailscale/tailscale/blob/53a0d659afa51835dd7a9283873cca44261454f8/ipn/ipnstate/ipnstate.go).
