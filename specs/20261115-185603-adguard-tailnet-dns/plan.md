# Implementation Plan: AdGuard Tailnet DNS

**Branch**: `feat/adguard-tailnet-dns` | **Date**: 2026-11-15 | **Spec**: [spec.md](spec.md)

## Summary

Deploy one AdGuard Home instance in existing `automation`, register it through
Terragrunt/Argo, expose UDP/TCP DNS with a Tailscale operator LoadBalancer Service,
and serve its authenticated UI at `https://adguard.stinkyboi.com` through existing
private Traefik ingress. Retain existing split DNS and MagicDNS. After the new
identity-verified endpoint passes direct acceptance, commit its observed address and apply
only the reviewed DNS configuration change through the administrator-owned
Tailscale unit. Normal client DNS acceptance completes the rollout.

## Technical Context

**Language/Version**: Kubernetes/Kustomize YAML, OpenTofu/Terragrunt HCL, Python
standard-library helpers using the existing pinned Python 3.14.7 image.
**Primary Dependencies**: AdGuard Home v0.107.80 (schema 34), Tailscale operator,
Traefik, External Secrets, AWS SSM, provider tailscale 0.29.2, Harbor mirror.
**Storage**: One retained 1Gi `nfs-default` PVC for work/filter cache. Writable
configuration emptyDir reconstructed from repository-owned template and SSM-backed
admin credential on startup. No unique UI-only configuration is supported.
**Testing**: Python fixture/static checks, Kustomize render, AdGuard runtime
fixture, relevant existing route/DNS/SSM/CI checks, deployment verification
and actual tailnet/system-resolver acceptance.
**Target Platform**: Existing Talos Kubernetes Linux cluster; ordinary tailnet
client with DNS acceptance enabled. Exit-node DNS support requires Tailscale
1.88.1 or later, per provider documentation.
**Project Type**: Infrastructure workload and operator integration.
**Performance Goals**: Three-second direct DNS acceptance deadline, no hidden
retries. No invented throughput or high-availability guarantee.
**Constraints**: Repository-owned desired state, private UI/DNS, no privilege or
trust widening, no plaintext secrets in source/output, verified-before-cutover.
**Scale/Scope**: One filtering replica initially; retain the separate two-replica
private resolver and its established policy.

## Constitution Check

Pre-research and post-design: all five principles pass at design level.

| Principle | Design evidence |
| --- | --- |
| Repository-owned state | App, secret, routes, DNS and rollout checks are committed before application; no ad hoc live patching |
| Secret safety | Generated internal admin password in existing encrypted SSM/state; ESO renders bcrypt; mounted files only |
| Validate before change | Image prerequisite delivery, runtime fixture, targeted preflight, endpoint checks, exact saved DNS plan |
| Reviewable/teachable | Small dependency-ordered PRs and affected inventory/ingress/storage/secret docs; explicit rollback |
| Reproducible ownership | Existing shared app registration and SSM unit; ordinary bootstrap retains declared dependencies |

Runtime prerequisites are not marked passed by these design gates. See
[research](research.md) for observed readiness and unavailable operator access.

## Architecture and configuration

- Kustomize app under `clusters/homelab/apps/adguard`, with `homelab-workloads`
  Application destination `automation`. Do not add a new namespace or broaden
  AppProject access. Registration dependencies: external-secrets, tailscale,
  traefik, tailnet-dns and platform-storage.
- Deployment `adguard`, one replica, `Recreate` strategy; disable service-account
  token mounting and opt out of ambient with the existing per-pod
  `istio.io/dataplane-mode: none` pattern. Non-root UID/GID 65534, fsGroup 65534,
  RuntimeDefault seccomp, read-only root, no privilege escalation; drop all
  capabilities and add only NET_BIND_SERVICE for upstream binary capability/DNS
  compatibility. Verify this exact security context with the pinned image.
- Start with 100m CPU/128Mi memory requests, 500m/512Mi limits. HTTP admin listens
  on 3000 with initialized authentication; DNS on 53. Use bounded TCP startup,
  readiness and liveness probes; direct DNS/HTTP functional checks remain separate.
- Service `adguard-dns`: LoadBalancer class tailscale, hostname `homelab-adguard`,
  tag `tag:homelab-ingress`, UDP/TCP 53 only. Service `adguard-admin`: ClusterIP,
  TCP 3000 only. No Funnel, public ingress, hostPort or NodePort.
- Private Traefik router/service for `adguard.stinkyboi.com`, excluded from Funnel.
  Update routes, approved-name Service annotation and private DNS view allowlist
  together, plus their inventory/static fixtures. Existing wildcard certificate
  covers this first-level name; verify rendered/live coverage rather than assume.
- NetworkPolicy declares DNS ingress from operator proxies and admin ingress from
  Traefik, plus required resolver/filter egress. Existing Flannel does not enforce
  NetworkPolicy: document this accurately. Tailscale grants and app authentication
  provide the external boundary; do not claim Pod-level policy enforcement.
- AdGuard config: protection/filtering enabled; default AdGuard DNS filter, daily
  update; null-IP blocking; query log and on-disk query log disabled; statistics
  disabled. Use explicit Cloudflare malware-filtering upstream IPs 1.1.1.2 and
  1.0.0.2, matching existing general DNS policy. Empty fallback list; disable
  automatic private PTR resolvers and client discovery to prevent DNS loops and
  retained client metadata. No DHCP, DoH listener or other unrequested services.
- Private domain upstream points to existing tailnet-dns Kubernetes Service,
  with no public fallback for its failures. Resolve the Service's cluster-local
  hostname during init using cluster DNS and validate an IPv4 result; substitute
  it into the config's conditional upstream. Do not use AdGuard/Tailscale global
  DNS to resolve its own upstream endpoint. Test routing and failure behavior
  with controlled upstream fixtures, including private AAAA NODATA.

## Secret, state and recovery contract

Generate `/homelab/adguard/admin-password` through the existing shared SSM unit,
32 characters and no more than bcrypt's 72-byte limit. Username `admin` is public.
Grant only that exact parameter to ESO; `automation` is already allowed.
ExternalSecret `adguard-config` uses OnChange and an explicit revision marker;
render a bcrypt hash with the installed Sprig function, never plaintext into the
runtime config. Render JSON-compatible YAML to permit standard-library validation.
An init helper validates schema, user count and bcrypt format, substitutes the
private Service endpoint, and atomically writes mode-0600 config to emptyDir.
AdGuard may rewrite its working config; every replacement reconstructs declared
settings. New config or credential revisions require a repository rollout marker.
No background uncontrolled hash regeneration/restart loop.

The PVC holds replaceable filter cache and must survive routine replacement or
failed list updates. Never delete it on rollback. Durable settings are Git plus
the protected SSM credential and encrypted state. Recovery drills reconstruct an
isolated instance from those recovery sources and verify authentication/filtering.
Do not export real credentials to public fixtures; fixture uses synthetic ones.
A real recovery receipt must identify protected source versions without values.
UI edits are transient and not the supported persistent configuration path.

## Delivery sequence

1. Prerequisite PR adds immutable AdGuard image to Harbor inventory. Merge through
   protected delivery, dispatch the existing publisher at exact main, verify full
   authenticated pulls/platform preservation before merging consuming manifests.
2. App PR adds workload, secret contract, route/name additions and targeted apply preflight. Test fixtures and docs accompany it.
   Extend targeted apply for `adguard` with exact namespace/SSM
   handling, but check `nfs-default` and the correct upstream applications.
3. Apply exact reviewed main through existing workflow, verify SSM/ESO/PVC,
   workload, private route and operator-created DNS Service. Verify its online peer and Service-owned device identity.
4. Validate observed Service IP against the online peer and run all direct
   acceptance. Save private receipts tied to source/config/peer identity.
5. Only then author the cutover commit: replace the two globals with the observed
   AdGuard IPv4, `use_with_exit_node=true`, `override_local_dns=true`; retain
   MagicDNS, search paths and exact split resolver. No guessed placeholder IP
   can enter an active nameserver list. Merge protected cutover source.
6. On the authorized administrator host, use the existing encrypted saved-plan
   path for tailscale-access. Add a repository-owned DNS cutover helper that
   reruns endpoint checks, rejects any saved-plan change except the intended
   `tailscale_dns_configuration.homelab` update, and verifies current main and
   the explicit freshness/binding contract below before applying that exact plan. Negative fixtures
   must reject stale identity/address, wrong DNS policy, failed preflight,
   unrelated resource changes, incomplete plan evidence and replacement/delete.
   Normal workload CI does not acquire administrator scopes.
7. Read back effective tailnet DNS; run normal-client acceptance and revision
   checks. Keep the issue open until required functional evidence passes.

If administrator access is unavailable, complete source delivery that is safe
without it, preserve the exact pending operation, and request only that missing
operator handoff when concrete. Do not mutate access policy to unblock the task.

## Cutover evidence freshness and binding

The helper defaults to preview; `--mode cutover --execute` reruns all required
direct DNS, active-filter, administration and endpoint checks in that same
invocation. A stored success receipt alone never authorizes execution. The full
check set must finish within 300 monotonic seconds. Its completion-to-apply
interval must be at most 60 monotonic seconds; otherwise repeat the check set.
Reject negative ages, future-dated persisted receipts and wall-clock regression;
monotonic timing governs live deadlines. Persist UTC start/end only for audit.

Bind the live result to clean current-main SHA, deployed app revision, config
revision, DNS Service UID/IP, peer public key/name/tag, exact saved-plan
SHA-256, and the complete before/after DNS policies. Immediately before apply,
re-read source/main, configuration and endpoint identity, live DNS policy and
plan-file digest; require equality with the checked snapshot. Any change
invalidates acceptance and requires a new plan/check run. Reject unknown or
incomplete planned DNS values, other changed resources, replacement/deletion,
wrong before/after policy and incompatible state. Preserve native OpenTofu state
locking/stale-plan rejection; never force-unlock or retry a write blindly.

Saved-plan inspection is always fresh in the invocation; a plan file's mtime is
not evidence. Historical receipts may document prior checks but cannot substitute
for fresh checks. Record mismatches without printing private plan/credential data.
This bounds the race window; no claim is made that external state cannot change
between the final read and the provider write. Inspect effective policy afterward.

Negative fixtures cover expired 300-second checks, >60-second apply delay,
future/negative timestamps, changed plan bytes, source/config/peer/Service drift,
changed live DNS, incomplete plan and unrelated mutations.

## Rollback

Before cutover, failure leaves existing DNS policy intact. After cutover, use a
reviewed rollback commit and explicit `--mode rollback` on the administrator
saved-plan helper to restore the captured previous global DNS/override fields,
preserving split DNS and MagicDNS. Explicit rollback returns prior unfiltered behavior; it is not an
automatic fallback. Retain AdGuard storage, secrets and peer for diagnosis.
Rollback has separate gates: authenticate with the existing administrator path;
require clean reviewed current main containing the restoration; validate the
protected pre-cutover policy snapshot against the reviewed pre-cutover source;
require the fresh live policy to equal the recorded activated policy (or report
already-restored no-op); and require the exact saved plan to change only the DNS
singleton from that live policy to the captured previous policy. Immediately
recheck live policy, main SHA and saved-plan digest before applying. Reuse the
300-second validation and 60-second final-delay bounds. Refuse unrelated drift,
unknown values, resource replacement/deletion or a missing prior-policy record.

Do not call AdGuard health, DNS, active-filter or admin checks in rollback mode.
Do not require its peer to be online or its current Service address to match:
those may be the failure being recovered. Existing private resolver availability
may be recorded diagnostically but must not prevent restoration of the prior
global policy; rollback preserves its configuration and does not repair it.
Verify effective policy after restoration, then report public/private/MagicDNS
client results independently. An unreachable control plane still blocks apply;
this path does not bypass administrator access or transport verification.

Regression fixture: with AdGuard DNS/UI and its peer unavailable, an exact reviewed
restoration plan is eligible; changed unrelated DNS fields or stale live-policy
snapshots remain rejected. Neither mode modifies or deletes app state/secrets.

App rollback restores the previous pinned config/image through GitOps; it does
not claim to restore unrelated state. Recovery must remain operable without
relying on AdGuard for operator-host DNS.

## Project Structure

Feature docs: `spec.md`, `plan.md`, `research.md`, `data-model.md`,
`contracts/dns-and-admin.md`, `quickstart.md`, `checkpoints/`.
`tasks.md` is generated in the later tasks stage, not here.

Source changes:

- `clusters/homelab/apps/adguard/`: workload, services, ESO, init config helper,
  retained PVC, network policy and README.
- `IaC/homelab/us-west-2/apps/adguard/`: shared Application registration.
- `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl`: credential.
- `clusters/homelab/apps/traefik/` and `platform/tailnet-dns/`: private route/name.
- `scripts/config/harbor-images.json`: prerequisite image inventory.
- `scripts/adguard-check.py`, `scripts/adguard-dns-cutover.py`: new acceptance
  and constrained saved-plan helper, with behavioral fixtures under `scripts/ci/`.
- `scripts/ci/terragrunt-apply.sh` and tests: bounded registration/SSM path.
- `IaC/terragrunt-catalog/modules/tailscale-access/main.tf`: final observed-IP cutover.
- Relevant OpenWiki inventory, ingress, storage, secret and validation docs.

## Complexity Tracking

No constitution exception. Separate app rollout and DNS cutover are necessary
because the operator assigns the endpoint; verify its identity before activation. Existing source owners remain authoritative.


## Endpoint identity and evidence

The owner Mac must be online in the expected tailnet. Read only the fixed
`automation/adguard-dns` Service and its single ready, non-deleting operator-owned
Pod in `tailscale`. Parent-resource labels, Service UID, Pod UID and app label
must agree. Read the proxy's actual device status and compare it with exactly
one peer in the Mac's current network map. Require matching stable device ID,
positive integer NodeID, nonzero node public key, expected hostname/tag and
unique nonempty addresses in the tailnet ranges. Require online, unexpired
identity, `InNetworkMap=true` and the expected map-key binding. Published Service
hostname and addresses must match that identity; re-read the Service afterward.

Capture the full observed peer with source, deployed and config revisions in
private acceptance evidence. Missing or inconsistent observations fail. Repeat
identity checks before and after direct functional acceptance and immediately
before applying the saved DNS plan. Any observed drift invalidates prior results;
observations are not atomic across machines. No override substitutes for the
connected client's actual status. Rollback remains independent of resolver health.

Validator and collector fixtures cover wrong ownership, ready state, key,
address, stable/numeric IDs, network-map membership, offline/expiry, duplicate
peers and identity drift. Direct/cutover regressions must reject drift without
applying DNS, and retain filtering, authentication, TLS, revision, timeout,
normal-client and independent rollback checks. Owner-run Mac evidence remains
necessary for UDP/TCP, private administration, recovery and normal-client use.
