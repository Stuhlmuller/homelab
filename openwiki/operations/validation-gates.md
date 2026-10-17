---
type: operation
title: "Validation Gates"
description: "Static, policy, render, secret-scan and live acceptance gates for homelab workloads."
tags: [operations, validation]
sources:
  - id: openwiki-source-5639384dcb82d59768eb1132
    resource: repo://.github/workflows/harbor-core-images.yml
  - id: openwiki-source-f3c1ec74b74e361ea2192c05
    resource: repo://.github/workflows/mastodon-public-dns.yml
  - id: openwiki-source-7f1128611d8d832ea8e26c38
    resource: repo://.github/workflows/validate.yml
  - id: openwiki-source-55e66a93073b222af31dbd6b
    resource: repo://.talos/patches/nix-builder-seccomp.yaml
  - id: openwiki-source-d776ebf3a4d179a97fb3c239
    resource: repo://builds/harbor-core/build.sh
  - id: openwiki-source-5a4bc495baa769b6a5e9cae2
    resource: repo://builds/harbor-core/csrf-compat_test.go
  - id: openwiki-source-8ab7fab142e4f564e8f17f97
    resource: repo://builds/harbor-core/Dockerfile
  - id: openwiki-source-06f6e19e20cbeda12ce6f3b0
    resource: repo://builds/harbor-core/patches/0003-security-dependencies.patch
  - id: openwiki-source-4809fcf6b821691d424ca089
    resource: repo://builds/harbor-core/registry-test.py
  - id: openwiki-source-ce77d7835e45f7370160e6c6
    resource: repo://builds/harbor-core/signer-test.sh
  - id: openwiki-source-db4fcfb731a7d9f94926969c
    resource: repo://builds/harbor-core/token-trust_test.go
  - id: openwiki-source-9f4d1b63d947cd42e3af68b2
    resource: repo://clusters/homelab/apps/deluge/README.md
  - id: openwiki-source-58caddf8069d72479935ea1e
    resource: repo://clusters/homelab/apps/fleet/FREE-ENTRA.md
  - id: openwiki-source-ffe9c2c54bc78625ce9efd78
    resource: repo://clusters/homelab/apps/mastodon/README.md
  - id: openwiki-source-4fbefc48f7f8bb8df22af69f
    resource: repo://clusters/homelab/apps/nix-builder/deployment.yaml
  - id: openwiki-source-2dc1935a1c837b3ac0cd9adf
    resource: repo://clusters/homelab/apps/nix-builder/README.md
  - id: openwiki-source-a11878298975bc4bd3bbaf7d
    resource: repo://clusters/homelab/apps/policy-bot/README.md
  - id: openwiki-source-8f628fd33437cf63e7f9b8c2
    resource: repo://clusters/homelab/apps/traefik/CUTOVER.md
  - id: openwiki-source-f7b4195d4d622f91da5cc07b
    resource: repo://clusters/homelab/apps/traefik/funnel.yaml
  - id: openwiki-source-e0d1dba87aa9213350b1234a
    resource: repo://docs/ci-cd.md
  - id: openwiki-source-2d23b8001d89196fa1eba48a
    resource: repo://docs/evidence/harbor-core-advisory-assessment-2026-10-11.json
  - id: openwiki-source-e6fd9160ab2341143a5d45c8
    resource: repo://docs/image-egress-hardening.md
  - id: openwiki-source-e081ebe342fc946979516883
    resource: repo://docs/nix-builder-seccomp.md
  - id: openwiki-source-1247eded2dab9841fec2a345
    resource: repo://docs/nix-cache.md
  - id: openwiki-source-b17e212516ed4cf97993dd01
    resource: repo://IaC/modules/entra-owner-mail/README.md
  - id: openwiki-source-a3ec8939cc4b10401bd16cd8
    resource: repo://policy/kubernetes.rego
  - id: openwiki-source-ebb70c48f85bc6100b070f01
    resource: repo://scripts/ci/deluge-daemon-status-test.py
  - id: openwiki-source-c6bd7de8d27299a6b6fb92d3
    resource: repo://scripts/ci/harbor-core-scan-check-test.py
  - id: openwiki-source-6bf00c52458ec78a0c3b6077
    resource: repo://scripts/ci/harbor-core-scan-check.py
  - id: openwiki-source-faf0c71b216725764a045c19
    resource: repo://scripts/ci/harbor-core-source-test.py
  - id: openwiki-source-0e4e3673c8be0ce1ef65beca
    resource: repo://scripts/ci/harbor-publish-test.py
  - id: openwiki-source-9572753e0a38126e57fa7042
    resource: repo://scripts/ci/multica-desktop-connect-test.py
  - id: openwiki-source-3b37d159fd7aec286d251f6b
    resource: repo://scripts/ci/n8n-github-webhooks-test.py
  - id: openwiki-source-263c9c13d476aa142f8ebd42
    resource: repo://scripts/ci/network-policy-enforcement-check.py
  - id: openwiki-source-47792446a9e092544c3c1857
    resource: repo://scripts/ci/nix-checks.sh
  - id: openwiki-source-f6fba8ad33526ba318c4d722
    resource: repo://scripts/ci/octelium-api-response-test.py
  - id: openwiki-source-9d1513ec6ffec6dad14a5d87
    resource: repo://scripts/ci/octelium-entra-oidc-test.py
  - id: openwiki-source-c7852b586f8f1a45684f7ab4
    resource: repo://scripts/ci/offline-checks.sh
  - id: openwiki-source-020791e1237c864b31f43a39
    resource: repo://scripts/ci/offline-static-checks.sh
  - id: openwiki-source-54912e76b9bc176f1d28ff87
    resource: repo://scripts/ci/policy-bot-webhook-test.py
  - id: openwiki-source-7f41167da18dbfa043cfc3ca
    resource: repo://scripts/ci/static-checks.sh
  - id: openwiki-source-2ec3653fcc5fbc3a0f24c7a1
    resource: repo://scripts/ci/tailscale-access-check-test.py
  - id: openwiki-source-f8287cec4efc309562629516
    resource: repo://scripts/ci/tailscale-access-check.py
  - id: openwiki-source-fc269dae2f6a8501f0c0fb75
    resource: repo://scripts/ci/tailscale-ci-configure-test.py
  - id: openwiki-source-4ac432ebb03e57e6e256a336
    resource: repo://scripts/ci/tailscale-ingress-sign-test.py
  - id: openwiki-source-511191e55632b55651ad4318
    resource: repo://scripts/ci/tailscale-private-dns-test.py
  - id: openwiki-source-bd3e0276a60a943533e8286a
    resource: repo://scripts/ci/talos-harbor-mirror-credential-test.py
  - id: openwiki-source-b5db2a15b5e0f805364647e7
    resource: repo://scripts/ci/talos-harbor-mirrors-test.py
  - id: openwiki-source-c65516e351b2fe2cbdfc5a79
    resource: repo://scripts/ci/talos-nix-builder-seccomp-test.py
  - id: openwiki-source-c5bae48eacfc2b48af15ad5a
    resource: repo://scripts/ci/traefik-routes-test.py
  - id: openwiki-source-c78947a32d84fb4e618c32da
    resource: repo://scripts/ci/traefik-runtime-check.py
  - id: openwiki-source-4bbfe00c406fec8a213babcb
    resource: repo://scripts/nix-builder.py
  - id: openwiki-source-b4247f9b4622fc86c02f0ce3
    resource: repo://scripts/octelium-api-response.py
  - id: openwiki-source-3a59e2e385041c09f8b021a1
    resource: repo://scripts/policy-bot-webhook.py
  - id: openwiki-source-c5a2a233fdc6138ea6e6bb69
    resource: repo://scripts/tailscale-private-dns-check.py
  - id: openwiki-source-43db0977cfa60875fd0350f6
    resource: repo://scripts/talos-harbor-mirror-credential.py
  - id: openwiki-source-b4d9581a96236cc288a1836f
    resource: repo://scripts/talos-harbor-mirrors.py
  - id: openwiki-source-1c2e8ef619584eb7386e226a
    resource: repo://scripts/talos-nix-builder-seccomp.py
generated: { by: "codex", at: "2026-10-17T20:13:59.415Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-17T21:07:34.573Z
---

# Validation Gates

## Default Gate

Run the smallest validation that proves the change and record unavailable
checks in the PR or final response.

The static wrapper verifies source-bound offline fixture and manifest-policy
Nix outputs, then runs remaining provider, network and security checks fresh.
Fixture calls live in `scripts/ci/offline-checks.sh`; source contracts live in
`offline-static-checks.sh`. CI uses protected-main cache trust with signatures
and sandboxing. Cache reuse does not replace live plans or runtime acceptance.
See [signed offline validation](../../docs/nix-cache.md).

The [Linux builder](../../clusters/homelab/apps/nix-builder/README.md) uses
`NET_ADMIN` to raise loopback in each private Nix network namespace when
Talos disables user namespaces. That capability also permits Pod networking
changes; reviewed homelab source remains the trust boundary. Keep strict
sandbox/signature checks, Pod RuntimeDefault and the dedicated container
Localhost profile, the 1 GiB reservation/limit,
serial substitutions and original-Pod/attempt-ID cancellation. Fresh node
health, leases, metrics and at least 1.5 GiB measured headroom gate each attempt.
A render or healthy rollout proves neither full-check memory sufficiency nor
signed cache publication; verify actual substitution in fresh CI separately.

The [dedicated builder seccomp profile](../../docs/nix-builder-seccomp.md)
is declared separately from container selection. It preserves the captured
containerd 2.1.4 amd64 builder rules and adds only `pivot_root` while retaining
the deny-by-default action. Stage 1 installs the named profile on the two
eligible workers through `talos-nix-builder-seccomp.py`, after protected merge
and explicit release. The helper requires matching active/persistent configs,
preserves other profiles, rejects configuration/boot drift, validates strictly,
and uses a no-reboot apply with bounded exact profile readback, waiting
for asynchronous controller convergence without repeating apply. Stage 2 may select
Localhost only for the builder container after both node files are verified.
The current manifest declares that container-only selection and retains Pod
RuntimeDefault. Source/render validation proves neither applied OCI rules nor
successful publication. Offline validation
runs nine focused profile tests, including the exact one-syscall baseline
hash, idempotence, conflicting-profile refusal, configuration races and
refusal to remove a profile still selected by a Pod, delayed readback,
wrong content and deadline expiry. Rollback must verify actual file absence;
authentication or transport failures cannot establish deletion. Read the pinned
Talos 1.11.3 host path `/var/lib/kubelet/seccomp/profiles`; Kubernetes selection
stays relative to kubelet as `profiles/<name>`. The initial worker-0 helper
installed the approved file but stopped at a legacy-path readback. Worker-1
installation and all selection/publication were held at that failure. After
the protected path repair, worker 0 was verified read-only and worker 1's first
released helper completed. Both node files matched the reviewed profile with
active/persistent agreement and unchanged boots; the original builder remained
RuntimeDefault at that receipt. Stage 2 still requires exact protected review,
Argo rollout and actual OCI-profile verification. Retain sandboxing,
signatures, the 1 GiB limit and fresh preflight before a separately released
single bounded publication retry; any terminal failure consumes that attempt.

The dated [post-rollout receipt](../../docs/nix-builder-seccomp.md#verified-rollout-publication-headroom-hold)
records exact Argo revision `6dd7b02c`, a Ready replacement Pod and matching
running OCI profile, capabilities, sandbox/signature settings and actual 1 GiB
cgroup limit. At 2026-10-13 05:09 UTC, publication preflight still failed:
the selected worker had 1243.4 MiB measured headroom against the 1536 MiB guard.
No publication command or build attempt had run at that receipt; the newly
approved retry was still unused. Wait for fresh natural headroom and a separate release, or obtain
explicit approval for a concrete protected capacity change. Never lower the
guard, alter other workloads, restart Pods or reclaim host caches ad hoc.
That historical hold did not establish signed publication, warm-CI substitution
or full-check capacity. The later [signed publication and warm CI receipt](../../docs/nix-builder-seccomp.md#signed-publication-and-warm-ci-receipt)
records natural headroom recovery to 1589.9 MiB, fresh full preflight and a
separately released bounded retry on exact main `6dd7b02c`. Both Linux checks
completed, were signed and published, and passed independent fresh-store
signature acceptance plus unknown-key/unsigned rejection. Original-Pod cleanup
passed; peak memory was 905 MiB with no max/OOM/OOM-kill events. Main validation
run `38349343865` attempt 2, repo job `115167993774`, copied both exact published
outputs from the committed release URL without rebuilding either check and
finished successfully with remaining validation fresh. Acceptance applies to
that exact source tree; later tracked docs change the broad fingerprint. The separate fresh plan-only run `38506080728` completed successfully on signed
PR #1277 head `12eaf629`, base `0a442055`. Live plan job `115665635536` and its
policy gate passed fresh API-proxy checks and Terraform planning. Independent
cluster checks found four Ready nodes without pressure and the original builder
Ready with its 1GiB limit; Argo was Synced/Healthy/Succeeded at that base. Those
live checks ran separately from cached offline receipts. Migration apply,
retirement and further cache publication remain held; merging this docs receipt
releases none of them.

Deleted-unit cleanup is limited to deployed units under `IaC/bootstrap` and
`IaC/live`, including removals from the explicit stack. Catalog templates and
`IaC/operator` are never retired by the workflow. Every saved destroy plan must
pass the same Conftest policy as ordinary plans before production applies it;
protected resource deletion cannot bypass policy through unit removal.
Synthetic retirement units reuse the canonical Kubernetes and Helm connection
configuration. Encrypted-state retirement remains gated on the decoder work in
[PR #837](https://github.com/Stuhlmuller/homelab/pull/837).

For most repo changes, start with:

```sh
terragrunt hcl fmt --check
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
git diff --check
```

The static gate's `scripts/ci/terragrunt-stack-test.py` generates sparse and
overridden Applications from the real shared template, checking default
inheritance, list replacement, historical backend keys, changed-unit selection,
Azure credential isolation, and retirement ownership. Catalog fixtures carry
shape only; production defaults belong in `IaC/stack-defaults.hcl`, with app
inputs in `IaC/stacks/<app>/stack.hcl`.
For a stack refactor, also compare every affected generated unit's inputs,
dependencies, backend configuration, provider generation, and module source
against the pre-change revision. HCL validity alone does not prove equivalence.

The static gate runs `scripts/ci/job-alert-recovery-check.py` with the Nix-pinned
promtool against the actual Job recovery rules. Its synthetic histories cover
failure/success ordering, false/unknown condition gauges and transitions to true,
overlap, later failed runs, namespace isolation,
missing metrics, conflicting owners, duplicate recovered and unrecovered
scrapes, target turnover during a pending alert, recreated names, and
the existing 15-minute firing hold after five-minute group detection. The check
also requires the custom rule's
Kustomize registration, the chart-default replacement switch, and matching
15-day retention. Live rollout must leave one healthy `KubeJobFailed` rule;
see `clusters/homelab/apps/prometheus/README.md` for verification and rollback.

The static gate also runs `scripts/ci/memory-overcommit-check.py` against the
repository-owned `KubeMemoryOvercommit` rule. It checks the accepted non-HA
total-capacity threshold, the 10-minute hold, recovery, cluster isolation, and
replacement registration. Live rollout must leave one healthy rule in
`homelab.memory` and no alert while requests fit total allocatable capacity.
See `clusters/homelab/apps/prometheus/README.md#memory-capacity-policy`.

Operator-owned AWS bootstrap units require a focused backend-free validation
and an administrator-authenticated plan before apply:

```sh
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_role.github_actions' Github-TF-State
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
umask 077
plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-operator.XXXXXX")"
trap 'rm -rf -- "$plan_dir"' EXIT
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan \
  -out="$plan_dir/plan.out" -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color "$plan_dir/plan.out"
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color "$plan_dir/plan.out"
```

Run each import only on the first rollout, or during state recovery, when
`state list` does not contain its address: `aws_iam_role.github_actions` or
`aws_iam_user.external_secrets`. Backend-free validation deliberately leaves
the working directory detached from shared state, so the authenticated
`init -reconfigure` must precede every import, production plan, or apply from
that directory.

The GitHub workflow role must not plan or apply `IaC/operator`; those units own
the permissions that protect the workflow from self-administration.
Keep `--no-auto-init` on the backend-free validation and test commands;
otherwise Terragrunt can initialize the real S3 backend before running them.

## Tailscale and Traefik foundation

Offline validation runs `traefik-routes-test.py` and
`install-kubeconfig-test.py`. The first checks the fixed private inventory,
callback/registry boundaries, Fleet setup denial, and the exact four LAN, four
bridge, and four overlay `/32` sources for registry port 9443 in both ingress
policies. Adjacent LAN addresses and ordinary Pod addresses remain outside that
source boundary. The second checks tokenless API-proxy configuration and
plan-only dry-run admission. Render the exact Traefik chart plus Kustomization
and run Conftest on all declared routing resources.

Separately invoke `traefik-runtime-check.py --binary /absolute/path/to/traefik`
with the declared version to exercise the actual proxy on loopback. It downloads
nothing and checks Host/path isolation, encoded path rejection, WebSockets, h2c,
console upstream TLS/SNI, Harbor Authorization preservation, and projected
certificate reload. Test certificate verification bypasses are confined to this
local harness. Neither fixture replaces live ingress acceptance.

Private DNS readiness uses the transport-neutral `octelium-api-response.py`
parser. It checks only the final HTTP/2 response, retains duplicate fields for
rejection, accepts native `+proto` and gRPC-Web trailer frames, and requires one
unambiguous unauthenticated status. Focused tests reject conflicting statuses,
earlier-response confusion, and malformed bodies before DNS can change.

Validate and test the Tailscale provider module, compare the complete live policy,
and import the existing ACL before the private authenticated saved plan. Do not
apply a plan that replaces the existing ACL. After foundation adoption, the
Tailnet Lock addition must create exactly three scoped CI auth keys and preserve
the ACL and dormant federated identities. Keep state, tokens and saved plans
private. Generation rotation must replace keys, not merely update a description.

Offline validation also runs the fixed ingress signer and CI publisher tests. They
reject wrong proxy ownership/identity, wrong tailnet or signing profile, stale or
unsigned main, misplaced secrets, invalid provider keys, and unsafe private cache
permissions. Signer fixtures also cover the CLI's null empty peer classes before
any proxy is visible and after every proxy is signed. Publisher fixtures use
distinct delegated and trusted signer keys. They reject missing, ambiguous or
unrelated trust changes after signing, and mismatched cached authority identities
or metadata. Publication tests require all three secret writes and metadata
checks before deleting the old variables, reuse cached signatures on retry, and
restrict authority retirement to previous generations. Retirement regressions
corrupt each current or previous record, including later list positions, and
require both preview and execution to fail with zero removals, unchanged cache,
and no signing/publication. They also cover target drift after preflight and
already-absent previous authority retries. Pending-receipt regressions cover
lagging readback, timeout/retry without re-signing, durable cache replay after a
partial write, and preview/retirement refusal while a receipt remains. Narrow
orphan-recovery fixtures require exact provider/Mac/time metadata, no published
fixed secrets and an empty binary affected-signature lookup; malformed, populated
or failed lookups and unrelated trust drift stop removal. Mock provider tests cover
tag, expiry and explicit-rotation contracts; real provider planning remains the
proof of replacement behavior.

Before mesh acceptance, run `tailscale-ingress-sign.py` in preview mode, then
execute only from reviewed current main. Each proxy's public node and rotation
keys must match the exact controller-owned Kubernetes resource and local lock
peer. Tailnet approval and a Ready Pod alone do not prove a valid signature.

Before traffic cutover, verify observed Argo revision and health, certificate
readiness, real mesh application access, Fleet device check-in, native Cordium
execution/reconnection, and an uncached Talos registry pull from every node.
Converge the exact LAN/bridge/overlay source policies before host-only node migration;
a successful mapping or loopback preflight does not prove the node's SNAT path.
Prove callback
admin/root rejection off mesh and actual signed webhook delivery. Run protected
CI plan/apply through the operator API proxy, with a denied real plan-identity
write. Local tests and HTTP health alone do not satisfy these gates.

The retained ambient `octelium-client` is an authenticated principal, so the
private TLS listener temporarily permits its exact service account on 8443.
The focused regression rejects wrong namespace/account identities and callback
or registry ports, and requires the matching exact Pod/namespace NetworkPolicy
selector. Require connector readiness and authenticated native API access after
CoreDNS reconciliation; offline assertions do not prove live authorization.

The Talos helper regression covers full active/persistent resource capture,
additional-document divergence, a normal STATE-only boot with active version 1,
missing persistent after a later active change, duplicate resources, read failure,
and missing active config. Those checks repeat before and after apply while
preserving the node identity, configuration-scope and no-reboot gates.

The private DNS readiness checker accepts AFFiNE HTTP 502 or 503 only when
the repository and live Deployment explicitly declare zero replicas and no
live replicas remain. This accounts for Traefik's static ClusterIP backend
while AFFiNE is suspended. All other application 5xx responses fail; this
exception does not establish AFFiNE runtime health.

The DNS regression includes a dual-address peer whose LoadBalancer Service
publishes only IPv4: it must produce A records and no AAAA. Probe each published
address, never synthesize application endpoints from the peer's other family.
PolicyBot's safe GET probe requires hook HTTP 404 with one valid 20-character
backend `X-Request-ID`, and root HTTP 404 without that header. Tests reject wrong
statuses, missing/malformed/duplicate IDs and a root forwarded to the backend.
This proves routing only; fresh successful signed GitHub delivery proves the
callback path after cutover. No webhook POST or redelivery is part of preflight.
The CI publisher test separately requires all three raw signing keys on stdin,
never arguments or temporary files, with private captured command failures.

Phase 2a removes the public DNS restoration workflow and helper, changes internal
CoreDNS routing, and advertises n8n's Funnel URL. Confirm Funnel readiness before
n8n rolls out because it can register hooks on startup. External DNS execution,
Mac hosts migration, old-TTL expiry and normal canonical DNS/API verification
remain ordered steps; callback receipts require fresh natural deliveries. Old
CI and native operator transport stay until their later acceptance stage.

The current Flannel CNI does not enforce NetworkPolicy. Do not count those
manifests as isolation evidence; validate Tailscale ACLs, Istio authorization,
listener path boundaries and application authentication through their real paths.
See [ingress](../runbooks/tailnet-ingress.md) and the
[provider runbook](../../IaC/modules/tailscale-access/README.md).

The `network-policy` job in [validate](../../.github/workflows/validate.yml)
runs a 30-minute disposable dual-stack Kind
[enforcement check](../../scripts/ci/network-policy-enforcement-check.py) on
pull requests and `main` pushes. It checks unrestricted baseline traffic,
NRI registration, denied startup connections, allowed Service and DNS traffic,
established-connection revocation, and denial while the worker enforcer process
is paused without cleanup. A passing fixture does not establish production
Flannel enforcement or approve a worker rollout.

The additive cutover utilities have focused static tests for fixed DNS ownership,
Mac credential/profile preservation, bounded same-profile reconnect and carrier
rollback, non-executing webhook
preflights, and fresh delivery receipts. DNS API readback is separate from normal
OS resolution: migrate the owned Mac hosts override, wait the previous DNS TTL,
then run `tailscale-private-dns-check.py --verify-dns`. The
[staged cutover](../../clusters/homelab/apps/traefik/CUTOVER.md) retains old access
until replacement acceptance.

The CI boundary helper is
`scripts/ci/tailscale-access-check.py`. Its `plan` mode verifies the impersonated
tag, permits an empty server-side dry-run patch and requires the identical real
empty patch to receive the specific admission denial. Its `apply` mode verifies
the protected tag's administration permission without changing resources.

## Entra owner-mail and Octelium identity checks

Offline validation runs `scripts/ci/octelium-entra-oidc-test.py` against mocked
native APIs. Static validation separately runs the plan-only tests in
`IaC/modules/entra-owner-mail`. Together they cover disabled email fallback,
implicit fallback-user inventory, native empty lists, partial migration retry,
preserved contact fields, mail-only PATCH scope, current-mail and identity drift,
and rollback.

Before live work, run `scripts/octelium-entra-oidc.sh --dry-run` with the three
privately supplied admin flags. Follow the [Octelium migration sequence](../../docs/octelium.md#entra-identity-migration)
and retain an independent session. Verify immutable owner binding and disabled
email fallback before email reuse. The owner operator unit requires a private
`-var-file` with current-mail and identity baselines and an encrypted saved plan;
inspect that plan privately for exactly one
`msgraph_update_resource.mail` PATCH containing only `mail`. Follow the
[module contract](../../IaC/modules/entra-owner-mail/README.md), then verify
unchanged owner identity, fresh owner access and actual SMTP proxy release.
Offline tests and a valid plan do not prove Graph alias recalculation, owner
access, SMTP proxy release, or Mac SSO. The
[Fleet acceptance checks](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#platform-differences-and-acceptance)
remain required after the pilot rename.

## GitHub Workflow Checks

A September 26 protected squash was blocked by an unsigned ancestor despite a
verified tip. Check GitHub's verification for every PR-introduced commit.
Authorized signed-history repair must preserve a backup ref and exact content,
use `--force-with-lease=<ref>:<expected-old-head>`, then rerun exact-head CI and
obtain fresh approval; never bypass protection. See
[GitHub's signed-commit rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-signed-commits).

Cordium identity retirement requires removing both `cordium-check.yml` and
`cordium-login-denial.yml` in the reviewed retirement commit. The offline
retirement check rejects either remaining dispatch before any client access.

Workflow changes are covered by `scripts/ci/conftest-policies.sh` and
`policy/workflows.rego`. External `uses:` references must be pinned to a full
40-character commit SHA; keep an optional trailing version comment when it helps
reviewers map the immutable pin back to the upstream release tag.

### Chainguard Actions

GitHub workflows pin their Chainguard Actions references by full commit SHA.
Checkout, artifact publication, Nix installation, AWS credential setup, CodeQL,
semantic release and linting retain explicit reviewed versions.

This uses hardened **actions**, not replacement runner images. Super-Linter's
[hardened manifest](https://github.com/chainguard-actions/super-linter-super-linter/blob/bf49e660c836f9c76777ae48293f937565e314d7/action.yml)
still runs the upstream GHCR container, pinned by digest. Other
actions use JavaScript or composite steps. Ubuntu hosted runners and Nix-managed
tools remain; application images built or inspected by CI are separate workload
contracts. `terragrunt-apply-request.yml` has no external actions to replace.

`nix-community/cache-nix-action` remains pinned upstream: no corresponding
Chainguard repository was available at the recorded review. Recheck the catalog
before replacing it; do not remove caching or substitute a different cache
implementation merely to change the publisher.

Before enabling CI, confirm the repository owner's Chainguard Actions entitlement;
its status has not been verified locally. GitHub's repository policy was checked:
Actions are enabled, all publishers are allowed, and SHA pinning is required.
See the
[vendor prerequisites](https://edu.chainguard.dev/chainguard/actions/overview/).
The selected Nix and semantic-release actions include vendor usage telemetry;
the Nix action sends repository/action identity and uses an audience-specific
OIDC token when the job already permits it. No new credentials or permissions
are added. Review each pinned `source.json`, `action.yml`, and `HARDENING.md`
when updating these dependencies.

Keep the artifact-upload prohibition effective for both upstream and Chainguard
names in `policy/workflows.rego`. Refresh the exact workflow security hashes only
after reviewing the full definitions. Validate with `actionlint`,
`conftest verify --policy policy`, workflow policy evaluation, and the static
gate. GitHub execution remains the integration check; rollback restores the
previous action references and their matching workflow security hashes.

### Workflow security contracts

The pull-request `Terragrunt Gate` is an always-present aggregate. Its
unprivileged static job runs for every PR and owns live-scope detection. Only a
trusted same-repository PR whose diff contains a declared live input may enter
the `homelab-plan` environment; forks and other changes must leave the live job
skipped. The aggregate fails unless static checks succeed and the applicable
live plan or same-repository skip-note job has the expected result. Keep the
exact workflow contract asserted in `scripts/ci/static-checks.sh`.
That assertion pins the normalized live-scope and aggregate-gate bodies by
SHA-256 and pins each credentialed job as normalized JSON, so comments, dead
code, or added post-authentication steps cannot satisfy the check. Its closed
inventory rejects new environment-, secret-, token-, or write-permission jobs
until their complete job definition is reviewed and hashed. Conftest also
rejects direct live `kubectl`, `talosctl`, AWS, Terragrunt, OpenTofu, Terraform,
or non-rendering Helm output and any command after the private-log wrapper;
credentials stay scoped to the one live step.
The live-plan and protected-apply diagnostic exceptions check a classifier's
SHA-256 inside the hashed workflow before reading private output. A changed or
missing helper is not executed; only the fixed withheld error remains. The
live-plan classifier reports a fixed last-recognized-stage label and the first
recognized error hint (`aws-auth`, `kubernetes-auth`, `network`, `provider`,
`policy`, or `unknown`); the apply classifier reports only its fixed phase
label. These are not verified causes: misleading private text can change a
label but cannot expose its text. Raw output, plans, and credentials remain
withheld and deleted.

On September 26, PR #970 head `a51a820d` against base `ad91327d` passed the local
declared read-only plan: bootstrap, all 39 app registrations, and plan policies;
AzureAD was skipped without local credentials. Protected CI run `36272981407`
failed at the app stage. Its cause remains unknown; the fixed hints improve the
next failure report without changing plan behavior or proving a CI fix. Local
operator credentials, transport, and provider cache differ from CI.

On October 7, 2026 UTC, PR #1219's live plan failed at the application stage.
A private reproduction identified Harbor's Kubernetes provider `spec.sources`
tuple reconciliation as the sole application failure. Stored, desired, and live
source counts were all three; the resource was not tainted, so the existing
untaint path is inapplicable. The operator-stack addition selects all application
plans and exposed this blocker. The subsequent protected plan
[37580800923](https://github.com/Stuhlmuller/homelab/actions/runs/37580800923)
passed on `861fb9d7` against `427b01ad`, including the aggregate gate, without
a Harbor repair by this investigation. Keep the required gate intact; if the
error recurs, follow the [recorded recovery finding](../../docs/ci-cd.md#harbor-provider-plan-blocker-observed-october-7-2026-utc).
The separate reviewed owner operator plan later applied, with fresh owner
Octelium sessions verified before and after the mail change. The old SMTP alias
remained secondary, so the pilot rename was not retried. This operator execution
does not satisfy or bypass the protected CI plan gate; see the
[dated migration outcome](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#owner-address-migration-alias-release-blocked).

The Tunnel DNS workflow is also bound to an explicit reviewed main SHA and
included in that closed credentialed-workflow inventory. It uses only the
existing production AWS role and Cloudflare rule-removal secret, with private
API output withheld. Validate its full definition before updating the hash.

The `NOFX Registry Credential` workflow uses the same reviewed-main and protected
environment boundaries. Its AWS session can update only the dedicated NOFX
registry parameter after validating the PAT's owner, exact `read:packages`
scope, and both pinned image pulls. The static gate runs offline failure and
secret-handling tests for its helper; the runtime gate validates the dedicated
ExternalSecret and requires pull-secret references only with the private
maintained images. See [private-image bootstrap](../../docs/nofx-private-images.md).

The local secret hook rejects common plan/state filenames and inspects ZIP
members or JSON structure for OpenTofu plan/state signatures, including staged
blobs whose working-tree file was removed.

The local Checkov hook scans the full `clusters` directory for Kubernetes YAML
changes. A changed-files-only scan omits unchanged NetworkPolicies and can
incorrectly fail `CKV2_K8S_6` for a Deployment. Other files retain the diff scan;
the dedicated secrets hook still scans every changed file with the upstream
`--enable-secret-scan-all-files` entry and required `-f` argument. Do not override
that argument with `-v`, which prints Checkov's version instead of scanning.
The file-based secrets hook skips an empty selection, including conflict-free
merges, because `-f` requires at least one filename.

Do not require a new Actions context in ruleset `14700233` before the workflow
that emits it is merged. First observe `Terragrunt Gate` on a no-live-plan PR, a
trusted live-plan PR, and a fork; then add only that context while preserving
the existing required checks and verify a fresh no-live-plan PR does not
deadlock.

The CodeQL workflow in `.github/workflows/codeql.yml` runs on pushes
and pull requests targeting `main` and on its weekly schedule. It has one
buildless `actions` analysis job because this repository has no compiled
application source. Treat it as CI/CD security automation: workflow edits
should pass the static policy gate locally before relying on GitHub's code
scanning result.
The Chainguard CodeQL action v4.38.2 pin (`05a2b18f97905888db8f883471cc925f1a97a01c`)
is recorded in the exact normalized workflow security hash. Updating action
revisions requires reviewing that workflow and refreshing its hash alongside
the pin; the credentialed-job inventory and permission checks still apply.

For docs-only or wiki-only changes, run the OpenWiki navigation check plus
focused Markdown and whitespace checks when the infrastructure graph is untouched:

```sh
git diff --check -- AGENTS.md ONBOARDING.md openwiki .agents/skills
rg -n \
  "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" \
  openwiki .agents/skills
```

## Kubernetes Source Checks

`scripts/ci/langfuse-valkey-recovery-test.py` checks stopped-writer guards,
backup integrity and candidate-only AOF repair. Its optional `--checker` runs
a synthetic corrupt tail through the matching Valkey 8.0.11 executable.
The [capture runbook](../../clusters/homelab/apps/langfuse/README.md#valkey-offline-capture-and-candidate-inspection)
requires offline live guards, off-NAS hashes and measured loss before requesting
live replacement; fixture success alone is not production recovery.

AI routing requires both the source gates and per-caller live evidence in
[AI observability](../architecture/ai-observability.md).
`scripts/ci/litellm-native-auth-test.py` runs with the pinned attribution-test
dependencies and exercises native key lookup, blocking/deletion, model and
route restrictions against an in-memory store. It does not prove database
import, UI revocation or cache invalidation in production.
`scripts/ci/litellm-native-database-test.py` runs pinned native migrations in
disposable PostgreSQL as a nonsuperuser owner, then tests concurrent atomic
import, collision rollback, private file-backed config and persistence of key
blocks/deletions across repeat startup. The attribution gate now invokes its
previously uncalled streaming fixture with native auth and isolated SDK caches.
`scripts/ci/langfuse-staging-check.py` preserves current runtime secret/provider
contracts and verifies that the incomplete activation hook/template is absent.
It must pass again after overlapping caller changes. The separate activation
PR must replace that invariant with production-matched SDK checks: native
startup, pre-auth admission, success/failure credential redaction, streaming
and exact usage. Include the real authentication-failure logging path; a
pre-call-hook-only fixture misses dynamic callback extraction. Confirm actual
Langfuse generations after rollout; a Ready Secret may still contain a provider
placeholder and direct Astra recovery is outside gateway-only accounting.

Use the renderer that matches the changed source:

```sh
kubectl kustomize clusters/homelab/apps/<app>
kubectl kustomize clusters/homelab/platform/<service>
helm template <release> <chart> -f clusters/homelab/apps/<app>/values.yaml
kubectl diff --server-side -k clusters/homelab/apps/<app>
```

For image automation changes, render the retirement source, validate Renovate,
and confirm no image bypasses digest policy:

```sh
npx --yes --package renovate renovate-config-validator renovate.json
nix develop --command bash scripts/ci/static-checks.sh
```

For `platform-dns` changes, render the overlay and compare upstream answers
before rollout. After Argo CD syncs, verify CoreDNS contains the intended
resolvers and a workload pod receives a public answer rather than a sinkhole:

```sh
kubectl kustomize clusters/homelab/platform/dns
dig +short A iptorrents.com @1.1.1.1
kubectl -n kube-system get configmap coredns -o yaml
kubectl -n media exec deployment/prowlarr -c app -- getent ahostsv4 iptorrents.com
```

## Octelium Cutover Checks

Before running `octops init`, validate the self-hosted Cluster prerequisites:

```sh
kubectl kustomize clusters/homelab/platform/multus
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-public
bash -n \
  scripts/octelium-gateway-dns.sh \
  scripts/tailscale-private-dns.sh \
  scripts/octelium-entra-oidc.sh
scripts/octelium-cluster-bootstrap.sh --help
```

After a Multus rollout or burst of Octelium service pod replacements, verify
all Multus pods remain ready and below their 512Mi memory limit. A daemon at its
limit plus `multus-shim` timeouts means the Octelium ingress can lose every
endpoint while Argo CD still reports `platform-multus` healthy.

```sh
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system top pod -l app=multus --containers
kubectl -n octelium get events --field-selector reason=FailedCreatePodSandBox
```

After the prerequisite apps are applied, `scripts/octelium-cluster-bootstrap.sh`
checks the Multus CRD, Multus DaemonSet rollout, Octelium node labels, and
PostgreSQL/Redis readiness before it calls `octops init` in front-proxy mode.
The `octelium-cluster` app renders the Istio front-door route, its HTTP/2
upstream `DestinationRule`, and the scoped console login-return `EnvoyFilter`
in `istio-system`; it must not create the
`octelium` namespace because Octelium genesis owns that namespace during
bootstrap. The bootstrap wrapper applies the required privileged Pod Security
labels to the namespace after `octops` creates it.

The filter rewrites only the exact unauthorized browser login redirect for
`console.stinkyboi.com`. Validate its rendered Lua with the static gate and
the public browser probe in `scripts/octelium-e2e-check.sh`, then verify
authenticated page rendering and audit queries. Revalidate Envoy compatibility
when upgrading Istio. Automated pruning is disabled for this app: rollback
must commit an empty `spec.configPatches` list and adjust the filter test gate,
as described in `clusters/homelab/apps/octelium-cluster/README.md`; deleting
the file alone leaves the live filter installed.

Before declaring Octelium-backed app UI access healthy, the replacement path
must pass:

```sh
nix develop --command python3 scripts/octelium-tunnel-check.py
scripts/octelium-e2e-check.sh
```

The transport probe resolves the browser API through `1.1.1.1` and validates
its gRPC-Web status-16 trailer. A trailers-only response may carry that status
in its headers with an empty body, as the
[gRPC-Web protocol](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md)
permits. The September 12 audit reproduced this response from the healthy
public endpoint; requiring a body trailer incorrectly failed the transport
gate. Nonempty responses still require their final trailer frame, and the
probe retains its HTTP/2, content-type, status and TLS checks.
The probe parses the final HTTP response in curl's header dump, excluding
informational and proxy CONNECT responses. It requires one actual content-type
field with the expected media type; optional parameters are permitted.
Duplicate status or content-type fields cannot satisfy the gate. Native gRPC
may return status in its actual HTTP trailers, while a nonempty gRPC-Web body
must carry its sole status in the final body trailer frame.
It separately starts a temporary TCP carrier
and requires verified origin TLS, HTTP/2, and native gRPC status 16. Generic
HTTP responses and local listener readiness do not pass. The catalog checks
still require authenticated `octeliumctl` with a configured native transport
or the existing private route. Also verify authenticated console rendering,
audit queries, and real Cordium execution/reconnects before declaring recovery.

For retained native Cordium access, validate the existing human and Workspace
paths from outside the homelab. On the operator workstation, run
`octelium connect -d`, generate the client kubeconfig with `octelium config
kubernetes-api.homelab`, run its printed export, set the file to mode `0600`,
and require `kubectl --request-timeout=15s get nodes` to succeed. Repeat the
config, mode, and `kubectl` check inside a Cordium Workspace, whose client
session is created automatically. Also require Secret reads and a server-side
dry-run create to be denied there; Cordium has restricted read-only access.
Keep Tailscale for private applications and remote Talos/LAN access. These legacy
checks do not replace the staged Traefik DNS and CI acceptance gates above.

Pass `--octelium-context` and `--homelab-context` when the Octelium control
plane and homelab connector live in different Kubernetes clusters.

CI/CD Octelium changes should also pass shell syntax checks for
`scripts/ci/install-kubeconfig.sh`, `scripts/octelium-ci-credential.sh`, and
`scripts/octelium-ci-kubeconfig-secret.sh`. Validate that
`docs/examples/octelium/homelab-services.yaml` parses and contains Service
`kubernetes-api-ci` plus core `ClusterConfig` `default` with human
`maxPerUser: 32`, and that User `homelab-ci` keeps matching 30-day clientless
Session and access-token lifetimes before applying it with `octeliumctl`.
Apply the `ClusterConfig` with `--include ClusterConfig` before the normal
catalog apply because the include flag replaces the default resource-kind list.
The static gate requires manual Homelab Diagnostics and Terragrunt Apply
dispatches to carry an exact expected `main` SHA and fail before work when the
resolved workflow commit differs. Every push to `main` runs only the cancellable
`Terragrunt Apply Request` check; it uses no protected environment, stored
secret, or OIDC permission and prints the exact dispatch command plus active
apply links. Production is restricted to `main`, without reviewer approval;
Same-repository PR plans also enter their environment automatically. The apply's first live-job step requires the expected, workflow, and current `main` SHAs to
match before credentials or live commands.
The live job retains only the newest pending run and never cancels an
in-progress apply. Main-only diagnostics use the same production environment.

The focused Octelium private Kubernetes workflow has the same exact-`main`,
current-head, production-branch, serialized-run, private-log, static, and
Conftest gates. Its fixed helper extracts exactly
`Policy/homelab-private-kubernetes-access` and
`Service/kubernetes-api.homelab`, never prunes, and requires a second apply to
report no changes. The lifecycle helper installs cleanup before creating its
30-minute, one-authentication Credential, binds its watch to the unique run it
dispatches, and verifies Credential, Session, and GitHub-secret revocation on
exit. See `docs/ci-cd.md`.

The gate checks the Octelium control plane, IdentityProvider `entra`, private
`kubernetes-api.homelab` Service, synced
workload credential, ready connector replica, and
`ambient.istio.io/redirection=enabled` on every active connector pod. It also
checks Cluster/API/portal TLS responses, the complete homelab WEB Service
catalog, public DNS for each existing
`*.stinkyboi.com` app hostname, and HTTPS access to each app hostname through
Octelium public WEB access. Langfuse is included as a non-anonymous public WEB
Service. It requires AFFiNE's anonymous Service mode, NOFX's
`homelab-human-web-access` policy, and unauthenticated NOFX `/` and `/api/health`
responses to carry Octelium's `401` denial header. It also validates AFFiNE's
native-client CORS preflight plus public `serverConfig` GraphQL query, confirms
AFFiNE rejects an unauthenticated workspace query, and ensures every other
public app Service remains non-anonymous. App hostnames
must not resolve to private
Octelium service IPs or the old Tailscale wildcard. The same script probes the
Cordium nested workspace wildcard for valid edge TLS and probes the reviewed
callback hostnames for public DNS and path-limited reachability; the
n8n expected-negative webhook probe must see an n8n webhook response body, not
only a generic HTTP 404 from Cloudflare or the Istio gateway, while the Policy
Bot webhook probe must use the POST shape GitHub sends and require the app-level
HTTP 400 webhook validation response, not just any non-404 response.

Rendered Kubernetes policy also enforces the access contract:
`policy/kubernetes.rego` rejects unreviewed Tailscale Funnel and classifies every
gateway-attached `VirtualService`, every `Gateway`, and every `Ingress` except
the explicit `compass-discovery` class as externally reachable by default.
Legacy resources must declare `homelab.rst.io/access-plane: octelium`; the two
reviewed Traefik-backed Tailscale callback Ingresses are explicitly allowed. Only
gatewayless or mesh-only `VirtualService` resources and Compass discovery
entries are exempt. The policy also requires reviewed
`homelab.rst.io/public-callback-*` annotations for unauthenticated callback
hosts such as `n8n-webhook.stinkyboi.com` and
`policy-bot-hook.stinkyboi.com`. Run `scripts/ci/conftest-policies.sh` after
changing route manifests or the Octelium public tunnel/DNS host list.

The script must report failed probes as `FAIL:` lines and finish with a nonzero
exit code when any check fails. Keep expected-negative probes inside guarded
conditionals and avoid empty-array expansion under `set -u`, so macOS Bash 3.2
does not exit before the failure summary.

## Istio Ambient Recovery

Use these read-only checks after node recovery or an ambient configuration
rollout. All must pass before closing the readiness finding; connector access
alone is insufficient. Keep raw logs outside git.

Require every node Ready and both DaemonSets fully updated, observed, and
available on every node, with no misscheduled instances:

```sh
(
set -euo pipefail
kubectl get nodes -o json | jq -e '
  (.items | length) > 0 and
  all(.items[]; any(.status.conditions[]; .type == "Ready" and .status == "True"))'
ambient_node_count="$(kubectl get nodes -o json | jq '.items | length')"
kubectl -n istio-system get ds istio-cni-node ztunnel -o json |
  jq -e --argjson n "$ambient_node_count" '
    (.items | length) == 2 and all(.items[];
      .status.observedGeneration == .metadata.generation and
      .status.desiredNumberScheduled == $n and
      .status.updatedNumberScheduled == $n and
      .status.numberReady == $n and .status.numberAvailable == $n and
      .status.numberMisscheduled == 0)'
)
```

Check the live CNI ConfigMap, the rolled CNI Pods' configuration references,
every ztunnel Pod's IPv6 setting, active connector enrollment, and Argo state:

```sh
(
set -euo pipefail
kubectl -n istio-system get cm istio-cni-config -o json |
  jq -e '.data.AMBIENT_IPV6 == "false"'
kubectl -n istio-system get pods -l k8s-app=istio-cni-node -o json |
  jq -e '(.items | length) > 0 and all(.items[];
    .metadata.annotations["homelab.rst.io/ambient-ip-family"] == "ipv4" and
    any(.spec.containers[] | select(.name == "install-cni") | .envFrom[]?;
      .configMapRef.name == "istio-cni-config"))'
kubectl -n istio-system get pods -l app=ztunnel -o json |
  jq -e '(.items | length) > 0 and all(.items[];
    any(.spec.containers[] | select(.name == "istio-proxy") | .env[]?;
      .name == "IPV6_ENABLED" and .value == "false"))'
kubectl -n octelium-client get pods -l app.kubernetes.io/instance=octelium-client -o json |
  jq -e '[.items[] | select(.status.phase != "Succeeded" and .status.phase != "Failed")] as $pods |
    ($pods | length) > 0 and all($pods[];
      .metadata.annotations["ambient.istio.io/redirection"] == "enabled" and
      any(.status.conditions[]; .type == "Ready" and .status == "True"))'
kubectl -n argocd get application istio -o json |
  jq -e '.status.sync.status == "Synced" and .status.health.status == "Healthy"'
)
```

Query the existing Prometheus service through the Kubernetes API. This helper
uses the operator's kubeconfig and does not expose Prometheus publicly. Capture
one UTC endpoint for every query and the later log check; keep
`ambient_window_end` available until all checks finish:

```sh
ambient_window_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
(
set -euo pipefail
test -n "$ambient_window_end"
ambient_promql() {
  kubectl get --raw "/api/v1/namespaces/monitoring/services/http:prometheus-kube-prometheus-prometheus:9090/proxy/api/v1/query?$(
    python3 -c 'import sys, urllib.parse; print(urllib.parse.urlencode({"query": sys.argv[1], "time": sys.argv[2]}))' \
      "$1" "$ambient_window_end"
  )" | jq -e 'if .status != "success" then error("Prometheus query failed") else .data.result end'
}
ambient_ds_uids="$(kubectl -n istio-system get ds istio-cni-node ztunnel -o json | jq -ce '
  def text: type == "string" and length > 0;
  if (.items | type) == "array" and (.items | length) == 2 and
     ([.items[].metadata.name] | sort) == ["istio-cni-node", "ztunnel"] and
     all(.items[]; .kind == "DaemonSet" and .metadata.namespace == "istio-system" and
       .metadata.deletionTimestamp == null and (.metadata.uid | text)) and
     ([.items[].metadata.uid] | unique | length) == 2
  then [.items[].metadata.uid] | sort else error("Invalid ambient DaemonSet inventory") end')"
ambient_pods="$(kubectl -n istio-system get pods -o json | jq -ce --argjson owners "$ambient_ds_uids" '
  def text: type == "string" and length > 0;
  if (.items | type) != "array" then error("Invalid Pod inventory") else .items end |
  [.[] | select(.metadata.deletionTimestamp == null and
      .status.phase != "Failed" and .status.phase != "Succeeded") |
    .status.phase as $phase | (.metadata.ownerReferences // []) as $refs |
    if .kind == "Pod" and .metadata.namespace == "istio-system" and
       (.metadata.name | text) and (.metadata.uid | text) and
       (["Pending", "Running", "Unknown"] | index($phase)) != null and
       ($refs | type) == "array" and all($refs[];
         (.kind | text) and (.name | text) and (.uid | text))
    then . else error("Malformed live Pod identity or owner") end |
    [$refs[] | select(.uid as $uid | $owners | index($uid))] as $matching |
    select(($matching | length) > 0) |
    [$refs[] | select(.controller == true)] as $controllers |
    if ($matching | length) == 1 and $controllers == $matching and
       $matching[0].kind == "DaemonSet"
    then [.metadata.namespace, .metadata.name, .metadata.uid, $matching[0].uid]
    else error("Ambiguous ambient Pod controller") end] as $pods |
  if ($pods | length) > 0 and ([$pods[][3]] | sort | unique) == $owners and
     ([$pods[] | .[0:2]] | unique | length) == ($pods | length) and
     ([$pods[][2]] | unique | length) == ($pods | length)
  then [$pods[] | .[0:3]] | sort else error("Missing or duplicate ambient Pods") end')"
ambient_promql 'min_over_time(kube_pod_status_ready{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",condition="true"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy readiness series") end'
ambient_promql 'count_over_time(kube_pod_status_ready{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",condition="true"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete readiness history") end'
ambient_promql 'sum by (namespace, pod, pod_uid) (increase(prober_probe_total{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",probe_type="Readiness",result="failed"}[24h1m]))' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.pod_uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 0)
    then . else error("Missing probe history or observed probe failures") end'
ambient_promql 'count_over_time(prober_probe_total{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",probe_type="Readiness",result="failed"}[1m] offset 24h)' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.pod_uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 1)
    then . else error("Missing pre-window probe counter baseline") end'
ambient_promql 'count_over_time(prober_probe_total{namespace="istio-system",pod=~"(ztunnel|istio-cni-node)-.*",probe_type="Readiness",result="failed"}[24h])' |
  jq -e --argjson expected "$ambient_pods" '
    if ([.[] | [.metric.namespace, .metric.pod, .metric.pod_uid]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete probe history") end'
ambient_nodes="$(kubectl get nodes -o json | jq -ce '
  [.items[] | [.metadata.name,
    (([.status.addresses[] | select(.type == "InternalIP" and (.address | contains(":") | not)) | .address][0]) + ":10250")]] |
  sort | unique | if length > 0 then . else error("No expected kubelet targets") end')"
ambient_ksm_selector="$(kubectl -n monitoring get service prometheus-kube-state-metrics -o json |
  jq -er '.spec.selector | to_entries | map("\(.key)=\(.value)") | join(",") | select(length > 0)')"
ambient_ksm="$(kubectl -n monitoring get pods -l "$ambient_ksm_selector" -o json | jq -ce '
  [.items[] | select(.metadata.deletionTimestamp == null and
    .status.phase != "Failed" and .status.phase != "Succeeded") |
    [.metadata.name, (.status.podIP + ":8080")]] |
  sort | unique | if length > 0 then . else error("No expected kube-state-metrics targets") end')"
ambient_promql 'min_over_time(up{job="kube-state-metrics"}[24h])' |
  jq -e --argjson expected "$ambient_ksm" '
    if ([.[] | [.metric.pod, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy kube-state-metrics targets") end'
ambient_promql 'count_over_time(up{job="kube-state-metrics"}[24h])' |
  jq -e --argjson expected "$ambient_ksm" '
    if ([.[] | [.metric.pod, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete kube-state-metrics history") end'
ambient_promql 'min_over_time(up{job="kubelet",metrics_path="/metrics/probes"}[24h])' |
  jq -e --argjson expected "$ambient_nodes" '
    if ([.[] | [.metric.node, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) == 1)
    then . else error("Missing, replaced or unhealthy kubelet probe targets") end'
ambient_promql 'count_over_time(up{job="kubelet",metrics_path="/metrics/probes"}[24h])' |
  jq -e --argjson expected "$ambient_nodes" '
    if ([.[] | [.metric.node, .metric.instance]] | sort | unique) == $expected and
       all(.[]; (.value[1] | tonumber) >= 2880)
    then . else error("Missing or incomplete kubelet probe scrape history") end'
)
```

The subshell stops at the first failed command without changing the caller's
shell options. Each assertion must exit zero; empty results, bad values, and
short observation windows fail. Require readiness minimum `1` and failed-probe
increase `0` for every current CNI and ztunnel Pod. At the declared 30-second
scrape cadence, each readiness and failed-probe counter series needs at least
2,880 samples over 24 hours. Exporter `up` checks require the same coverage and
match each live Pod/node and scrape address; the current IPv4 endpoints use
ports 8080 and 10250. Every expected target must remain `up == 1`.
All readiness/probe assertions match namespace, Pod name and UID against
current nonterminal, nondeleting Pods controlled by the live DaemonSet UIDs.
Read-only inspection confirmed the readiness `uid` and prober `pod_uid` labels;
the probe aggregation retains that identity. Invalid/empty inventory, missing
series, gaps, counter absence, or a replacement with less than 24 hours
of observation do not prove recovery. If scrape cadence or target identity
changed, establish equivalent complete coverage before closing the finding;
do not replace missing data with zero. The failed-probe increase spans 24 hours
plus one minute and requires a sample at or before the 24-hour boundary from
that preceding minute. This catches a failure before the first in-window scrape.
It conservatively rejects failures in the extra minute too; wait for a clean
window instead of dropping the baseline. The executable Promtool fixture in
`scripts/ci/istio-ambient-probe-check.py` covers that boundary and missing data.

Inspect all CNI and ztunnel logs for the same 24-hour window. Save current logs
privately and print only their first/last timestamps when assessing retention:

```sh
ambient_logs="$(umask 077; mktemp -d)"
(
set -euo pipefail
umask 077
test -n "$ambient_logs"
test -d "$ambient_logs"
kubectl -n istio-system get pods -o json | jq -er '
  [.items[] | select(any(.metadata.ownerReferences[]?;
    .kind == "DaemonSet" and (.name == "istio-cni-node" or .name == "ztunnel"))) |
    [.metadata.name, .spec.containers[0].name]] |
  if length > 0 then .[] | @tsv else error("No ambient Pods to collect") end' |
  while IFS="$(printf '\t')" read -r ambient_pod ambient_container; do
    kubectl -n istio-system logs "$ambient_pod" -c "$ambient_container" --timestamps \
      > "$ambient_logs/$ambient_pod.current.log"
    test -s "$ambient_logs/$ambient_pod.current.log"
  done
for ambient_file in "$ambient_logs"/*.log; do
  test -s "$ambient_file"
  awk 'NR == 1 {print FILENAME, "first", $1} END {print FILENAME, "last", $1}' "$ambient_file"
done
)
```

The directory variable remains available to later commands. Any failed fetch,
empty log or empty Pod inventory exits nonzero; discard that incomplete capture
and rerun the block before assessing retention.

`kubectl logs --since=24h` alone cannot establish that rotated records still
cover the window. If any current log starts too recently, identify its Pod UID,
node InternalIP, and container name with
`kubectl -n istio-system get pod POD -o json` and
`kubectl get node NODE -o json`. Use authenticated Talos access to list
`/var/log/pods/istio-system_<pod>_<uid>/<container>/` on that node:

```sh
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP ls POD_LOG_DIRECTORY
talosctl --endpoints 10.1.0.199 --nodes NODE_INTERNAL_IP read ROTATED_LOG_PATH > "$ambient_logs/rotated.log"
```

Replace the uppercase placeholders with the observed values. Preserve distinct
local filenames for each Pod/rotation; decompress `.gz` files before inspection.
If a container restarted, include its previous logs. Require a complete retained
file chain covering the observation window on every node. Missing older files
leave the log gate unverified even if current readiness is healthy.

Search the collected, uncompressed logs for readiness failures and the observed
IPv6 bind/route signatures using the same captured endpoint:

```sh
python3 scripts/istio-ambient-log-check.py \
  --window-end "$ambient_window_end" "$ambient_logs"
```

Exit `0` means no in-window signatures; `1` means a matching failure; `2` means
invalid or incomplete input. The helper checks `(end - 24h, end]`, matching
Prometheus range boundaries, with nanosecond precision. It accepts UTC `Z`
timestamps from `kubectl logs --timestamps` and complete CRI `F` records from
Talos. Malformed timestamps, partial CRI `P` records, unreadable/empty files,
compressed files, symlinks, nested directories, and an empty inventory fail
closed. Keep only the uncompressed log files in this private directory.

Older and future signatures are excluded; every input record must still parse.
Output contains only the window and aggregate counts, never raw log messages.
This signature check does not establish Pod identity or retained rotation
coverage: the preceding gates remain required. Record the observation window
and aggregate verdicts; never commit raw logs or substitute a shorter window
for this recovery gate.

## Policy Bot Checks

Repository-local `.policy.yml` changes need Policy Bot validation, not just YAML
parsing:

```sh
policy-bot validate -p .policy.yml
curl -sS --fail-with-body https://policy-bot.stinkyboi.com/api/validate -T .policy.yml
```

Use the live endpoint when the local binary and Docker validator are
unavailable.

## Terragrunt Checks

OpenTofu generates `.terraform.lock.hcl` during initialization. These provider
lockfiles are ignored at every directory level; do not commit them or copy a
peer unit's lock. Exact provider versions live in module/template HCL; CI
regenerates locks and checksums during init. This policy supersedes the
provider-lock requirement recorded in [Homelab Audit — 2026-09-02](audit-2026-09-02.md).
Fresh runners trust the registry checksum set because prior provider checksums
are not committed. Exact versions constrain selection, but do not independently
prove identical provider bytes across clean runs.

Generate explicit stack units before focused validation:

```sh
cd IaC
terragrunt stack generate
```

Focused unit validation:

```sh
cd IaC/live/<stack>/<unit>
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable run --no-auto-init -- validate -no-color
# Only before an authenticated live plan, reconnect to the intended backend:
terragrunt --log-disable init -reconfigure -no-color
terragrunt --log-disable plan -no-color
```

Backend-free OpenTofu validation does not guarantee credential-free Terragrunt
initialization: existing backend metadata or Terragrunt's S3 checks can still
require AWS access. Use an isolated module copy for offline validation when
that access is unavailable; do not silently switch a later plan to local state.

Explicit stack validation:

```sh
cd IaC
terragrunt stack run plan
```

The pull request workflow renders temporary Terragrunt plans to policy JSON and
runs Terraform-plan Conftest policy during `scripts/ci/terragrunt-plan.sh`. It
then runs `scripts/ci/conftest-policies.sh` for static YAML policy checks. Plan
details and live command output are withheld from the public PR and Actions
logs. Run the same order locally when reproducing a failure.

CI plan and apply scripts call `terragrunt stack generate` before filtering
units. When `IaC/terragrunt.stack.hcl`, `IaC/stacks`, `IaC/stack-defaults.hcl`,
`IaC/.catalog`, or `IaC/modules` changes, the scripts plan or apply the matching
generated unit groups instead
of relying on `--filter-affected` against ignored generated `terragrunt.hcl`
files. Stack index/inputs/defaults, catalog, module, shared root/provider, and tracked generated-group
changes use the local `*` because each command runs from
its generated-unit root. Plan-only toolchain, Terraform-policy, and execution-
script changes also refresh every plan without widening production apply scope.
Affected-only runs combine the repository-relative group with the Git selector
so Terragrunt cannot queue another unit group. Intentional operator plans use
mode `0700` temporary directories. CI may save plans in generated unit caches
for exact apply and policy checks; its scripts use `umask 077` and delete those
files on exit. Normal local `terragrunt plan` commands do not write plan
artifacts into generated caches.
Production Argo CD Application registration saves each affected plan, evaluates
the Terraform policy JSON, rejects manifest replacement/deletion, then applies
that exact plan. A protected manual dispatch may set one exact `argocd_app` unit
name to reconcile committed desired state without widening the run to its group
or running any unrelated production apply phase. Langfuse also reconciles its
shared SSM and S3 producers first, with pre-write platform readiness checks;
see [GitOps Flow](../architecture/gitops-flow.md). The offline
`scripts/ci/terragrunt-apply-test.py` regression checks prerequisite ordering,
saved-plan policy gates and failure-before-downstream-write behavior without
cloud or cluster access. Manual production and
diagnostic dispatches reject every ref except `refs/heads/main`; the production
environment independently limits deployments to the `main` branch.
Deleted-unit handling compares tracked units and explicit-stack paths at
the base and head revisions, so a catalog migration at the same path is not a
destroy while removing a stack block still retires its state. The production
Azure credential gate compares AzureAD unit sources, their repository-owned
module sources, stack blocks, and the shared root source they consume. Every
root source change fails closed. Unrelated stack changes do not require Azure
credentials.

Production applies resolve their affected-unit base from the newest successful
historical push apply or full dispatch. Full runs are named `Full @ <sha>`;
targeted runs are named `Targeted <app> @ <sha>` and never advance that
checkpoint. A missing, unreachable, or non-ancestor result fails closed so an
apply cannot become the new successful checkpoint while skipping an unknown
deleted-unit range. Manual-dispatch secret scans cover `HEAD^..HEAD`; the
working-tree Gitleaks scan still covers the complete checkout.

On October 7, [full apply run 37586972225](https://github.com/Stuhlmuller/homelab/actions/runs/37586972225)
succeeded at signed `main` commit `f47cf006e1108f2c1d13f7d002b0611fcdfc22df`.
That revision is now the checkpoint. The focused Fleet identity operator path
and Entra OIDC verification do not advance this checkpoint. Later recovery
still requires a reviewed successful full apply across its outstanding range;
never relabel a targeted run or manually skip an unapplied range. See the
[Fleet Free identity runbook](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#repository-operator-workflow).

GitHub-hosted live jobs depend on the Octelium clientless Kubernetes route. If
that route is the failed dependency, restore reviewed
`IaC/live/kubernetes-node-labels` state from a trusted LAN machine with a direct
`https://10.1.0.199:6443` kubeconfig, shared-backend AWS credentials, a saved
Terragrunt plan, and the Terraform-plan Conftest gate documented in
`docs/ci-cd.md`. No repository kubeconfig secret is part of that recovery path.

The trusted GitHub Actions PR plan job is serialized with a shared concurrency
group because it reads the same OpenTofu S3 backend state across pull requests.
Do not treat a queued PR plan as unhealthy; it is waiting for the live-state
lock lane. Same-PR replacement runs also queue instead of canceling in-progress
plans, because interrupting OpenTofu while it holds an S3 backend lock can leave
a stale lock that blocks later plans.

## Live Rollout Rule

Do not mutate live cluster, Talos, cloud, Argo CD, or secret-manager state until
the relevant validation has passed or the unavailable validation is recorded
with the risk. Desired state must be represented in the repo before applying it.

## Source Files

- `docs/validation-runbook.md`
- `.agents/skills/terragrunt-workflows/SKILL.md`

## Deluge daemon health

Run `nix develop --command python3 -I scripts/ci/deluge-daemon-status-test.py`
for aggregate counts, missing/malformed credentials, RPC failure and timeout,
malformed replies, and disconnect failures. These offline coroutine tests mock
Deluge/Twisted; they do not prove reactor behavior in the deployed image.
Render app-template 4.4.0 and the Deluge Kustomization, verifying that app and
daemon-metrics both mount `/scripts/daemon-status.py` and retain their existing
timeouts and VPN gating.

After reviewed Argo reconciliation, run
`kubectl -n media exec deploy/deluge -c app -- timeout 25s python3 -B /scripts/daemon-status.py`.
Require zero exit status, expected torrent count, healthy cached RPC/VPN
metrics, a serving Service endpoint and successful access through the original
route. A direct loopback check alone does not prove browser access. See the
[Deluge runbook](../../clusters/homelab/apps/deluge/README.md#troubleshooting)
and [October incident](deluge-cpu-audit-2026-09-05.md#october-8-daemon-health-failure).

## Gluetun CPU capture

The static gate exercises the bounded profiling helper with synthetic Pod,
process, and HTTP responses. Wrong or insecure API endpoints, identity,
readiness, image, listener, deadline, response-size, and cleanup failures must
stop capture. Endpoint flags remain pinned if the ambient context changes;
an already-absent capture directory counts as cleaned. Chart rendering must
retain the existing Deluge networking, CPU limits, capabilities, and storage;
only Gluetun mounts the two private-listener configuration files. Rendering
the committed disabled configuration with `pprof_enabled: "on"` must change
the Pod's ConfigMap checksum; the default remains `"off"`.

Synthetic checks do not prove a runtime bind address, safe profiling overhead,
or the cause of saturation. After reviewed activation, the helper verifies the
actual listener before collecting a private profile. After a reviewed disable
rollout, `check-disabled` verifies its absence. See
[Deluge CPU Audit — 2026-09-05](deluge-cpu-audit-2026-09-05.md) for measurement and rollback requirements.

## Cordium remote repository gate

The optional manual `cordium-check.yml` workflow executes the exact reviewed
main commit inside a disposable Cordium workspace using dedicated GitHub OIDC.
Its workflow is included in the credentialed-job inventory, normalized hash,
and exact-dispatch guard. Local lifecycle tests are part of the static gate;
live execution, cleanup, denied identity/method cases, and audit correlation
remain acceptance requirements. See [Cordium CI](../../docs/cordium-ci.md).

Fixed acceptance modes add exact-SHA exit-42 cleanup, read-only ListSpace
denial, and genuine wrong-ref/workflow assertion cases. Workspace execution
stays main-only; the two login cases cannot invoke Cordium. A matching server
error must occupy all stdout, with its matching raw Cobra error and known
usage on stderr. Transport failures and mixed output do not count as denial.
The intentional failure stays failed in CI and emits a notice only after
exit 42 and verified workspace deletion. Local regressions cover these bounds.
See the [fixed case matrix](../../docs/cordium-ci.md#fixed-acceptance-cases).

Wrong-ref Unauthenticated also covers provider/key errors. A fresh successful
allowed-main control and correlated private audit records remain required;
there is no workflow audit-record assertion or export helper. The pinned
logout attempts remote revocation but hides RPC failures, so unexpected login
success always fails acceptance and requires private session inspection.

Cordium work shares a deadline captured before Nix setup and reserves three
minutes for verified deletion and wrapper cleanup. Startup/check limits are
five/20 minutes; API calls cannot consume the cleanup reserve. Lifecycle tests
exercise timeout cleanup and exhausted setup without creating a workspace.
Cordium cleanup polls bounded inventory until asynchronous deletion completes.
Its fixed retirement helper requires the workflow and CI catalog definitions
to be removed on clean, exact reviewed local/remote main first, deletes only
the three dedicated CI identity resources,
and verifies absence. Tests reject remaining declarations, network errors,
and incomplete deletion. Ordinary catalog apply does not prune these objects.
Retirement verifies the pinned native client and reuses the private TLS carrier
for every inspection and deletion. Transport/pin failures prevent native calls;
the read-only target preview opens no carrier. Tests require carrier-scoped
environment on every request and cleanup after failed inspection.

The Tunnel probe accepts the protocol-defined empty-body gRPC-Web response
with status trailers in headers. Live browser and native TCP-carrier probes
passed after PR 957; malformed bodies and spoofed status headers still fail.
[Protocol reference](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md).

Cordium native CI installation tests verify read-only previews, fixed
three-resource selection, policy-first ordering, exact-main guards, and
repeated-apply convergence. Missing resources are distinguished from failed
native reads; wrong identities, duplicate definitions, reported apply errors,
and post-apply specification drift fail closed. Use the bounded
[CI catalog command](../../docs/cordium-ci.md#fixed-native-catalog-reconciliation)
for rollout; broad catalog application is not required.
Operator commands use `python3 -I`; the documented caller checks clean reviewed
main before evaluating Nix or repository Python. A copied-checkout regression
proves an untracked `scripts/json.py` cannot run before these helper guards.

Cordium retirement checks cover the pinned CLI's stdout `gRPC error NotFound:`
format as well as raw gRPC stderr errors. Already-absent resources are skipped;
other native failures remain errors.

## OpenClaw bootstrap gates

Bootstrap verifies its current offline archive, existing local database
integrity and direct-mount identity. It refuses missing databases and requires
a reviewed restore. Configuration and assistant checks preserve unrelated
state and remain idempotent.

Configuration batches have two complementary gates. The static shell fixtures
check bootstrap ordering, independent optional credentials, preservation, repeat
runs, failure stops, and private temporary-file cleanup. `OpenClaw native config`
runs `scripts/ci/openclaw-batch-native-check.py` on Linux amd64 using the exact
committed image digest. Synthetic config cases verify typed assignments,
SecretRefs, duplicate-path ordering, one write per batch, dry-run behavior,
failure atomicity, and the legacy hook-token unset sequence. The container has
no network or credentials and starts no gateway. This proves vendor semantics,
not production startup speed; see [OpenClaw bootstrap batching](openclaw-bootstrap-batching.md).

## Octelium PostgreSQL Restore Drill

`scripts/ci/octelium-restore-drill-test.py` exercises the candidate shell entry
point against disposable PostgreSQL 14 fixtures using the pinned Nix toolchain.
It requires actual globals/database restore, preserved backup source, private
output, and actual globals-triggered shell and PostgreSQL `COPY TO PROGRAM`
regressions that cannot write synthetic private markers through inherited log
descriptors. Both programs must execute, and all normal output must stay in
scratch. Success and failure both require empty public streams; Job exit status
is the completion signal. The render guard rejects a console-bearing entry-point
wrapper or a shared/host PID namespace. It also requires failure on corrupt or
stale newest archives, invalid checksum paths,
empty required tables, missing encrypted-resource keys, and previous-day-only
backups. A current invalid set fails even when a valid previous-day set exists.
Rendered timing guards include the backup's late-start and execution deadlines
plus a 15-minute margin. Rendered guards
require only the read-only backup PVC plus bounded scratch, no credentials, and
no additive NetworkPolicy allow selecting the drill. The full static gate runs
this check; `postgresql_14` is a validation dependency in `flake.nix`.

The live application excludes the resources in
`clusters/homelab/apps/octelium-storage/restore-drill-candidate/`. The render
fixture asserts that exclusion and the candidate CronJob's secondary suspension.
Only a separate reviewed activation after image/launcher and Talos runtime proof
may add it to GitOps and lift suspension. Post-activation acceptance
requires its scheduled Job success and `lastSuccessfulTime`, plus the shared
30-hour staleness alert. Static fixtures alone do not prove live restoration.
See `clusters/homelab/apps/octelium-storage/README.md` for private diagnostics,
rollback, and the limits of this PostgreSQL-only drill.

## OpenClaw container privilege gate

The app, bootstrap, and proxy declare UID/GID 1000, non-root execution, no
privilege escalation, and an empty capability set. Pod seccomp is explicitly
`RuntimeDefault`. The root Nix toolbox init remains a documented exception;
server-side Restricted warnings for that init are expected and must not be
misreported as full Pod compliance. See the OpenClaw README's container
privilege boundary for post-rollout process and functionality checks.

## NOFX runtime, image, and catalog gates

The static gate also renders the NOFX workload and runs
`scripts/ci/nofx-runtime-check.py`. It resolves relative backtest/log writes
against the effective working directory and most-specific mount, preserving
the existing SQLite path and claim while requiring an absolute executable and
read-only image root. A running health endpoint does not test these writes;
live acceptance additionally requires a short simulated Backtest Lab run.

Changes under `builds/nofx` also require `bash builds/nofx/test.sh` and
`bash builds/nofx/build.sh` on a Linux Docker host. The tests exercise the actual
patched backend and frontend build targets. The NOFX Images workflow runs these
without publishing credentials on PRs. Its main-only publishing job rebuilds
before registry login, rejects stale or mismatched main SHAs, and records fixed
GHCR image digest references. Both jobs are included in the closed credentialed
workflow inventory and the exact normalized workflow hash; actionlint,
Conftest, and Checkov cover workflow edits.

Image publication and deployment are separate changes. First-time packages
default to private, so public visibility and anonymous image access must be
verified before a reviewed PR changes runtime digests. Post-rollout acceptance
requires a blank-key model edit without trader initialization, a working AGPL
source download, rejected invalid backtest run IDs, and a completed short
simulation using the default OKX US public feed. Legacy saved runs retain
Binance. The September 14 storage rollout was `Synced`/`Healthy` but hit Binance
HTTP 451 on a new backtest; it did not satisfy this functional gate.

The fixed NOFX reconciliation command defaults to read-only inspection.
The documented caller verifies exact local/remote reviewed main and a clean
checkout before Nix evaluates `flake.nix` or `flake.lock`. The helper repeats
that guard before parsing the catalog or opening transport; it cannot protect
Nix code that a caller already evaluated. Staged and untracked files also fail
execution.
Tests reject wrong resource identities, missing or mismatched pinned CLI builds,
reported native apply errors, missing convergence, and remaining anonymous
access. Live acceptance requires an unauthenticated denial,
authorized human access, and audit correlation after the reviewed apply.
The operator entrypoint requires `python3 -I` before non-built-in imports.
A copied-script fixture proves untracked `scripts/json.py` never executes.
Tests also cover Linux `sha256sum`, Darwin `shasum`, failed-checksum rejection,
missing-Service recreation without treating auth failures as absence, and
live `authorizationMode: PASS` verification.
See [the operator path](../../docs/octelium-nofx-reconciliation.md).

## Fleet device management rollout

Fleet-only Company Portal and Platform SSO acceptance is retired. The dated
pilot records below do not authorize repeating that unsupported enrollment.
Use the current [Fleet boundary](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#retired-platform-sso-pilot).

The [WireGuard/AirVPN workflow](../../clusters/homelab/apps/fleet/WIREGUARD-AIRVPN.md)
adds `python3 -I scripts/ci/fleet-airvpn-setup-test.py` to static checks. Its
synthetic tests cover private-file handling, current-password file validation,
dry runs without credential reads, authentication without fallback or retries,
supported Apple VPN payloads,
explicit device targeting, enrollment checks, policy reconciliation and secret
redaction. Both Apple platforms require a freshly queried matching device UDID;
tests reject missing identifiers, including responses containing only an
enrollment/command-envelope identifier. App installation, MDM profile receipt
and a real AirVPN connection remain separate acceptance gates. Owner-supplied
configurations are required for live VPN provisioning; the installation policy
only checks the Mac app.

Use optional `--password-file` for the existing administrator's current
password on policy or device execution, including removal, after the bootstrap
password has rotated. Local validation must reject an unsafe credential file
before authentication. This path changes no password and preserves session
revocation; see the runbook for its owner-only file contract.

On 2026-10-05 UTC, read-only `DeviceInformation` queries returned matching device
UDIDs for the enrolled local Mac and iPhone. No VPN profiles were installed;
the inspection session was revoked. This validates the enrollment guard only.

Entra provider authentication has its own
[operator bootstrap and CI acceptance gates](../../docs/entra-terraform-provider.md).
Check the encrypted operator plan against exact application names, federation
subjects, read/owned-app permissions and retained human ownership. Reject
credentials, directory roles, licenses and unreviewed tenant-wide write grants.
Validate both GitHub environment protections before publishing identity
selectors. A human-operator plan does not prove GitHub OIDC or claims-assignment
refresh works; require actual CI runs for both identities and fresh no-change
plans. Keep private identity and authentication evidence out of public logs.

The [Free Entra acceptance checklist](../../clusters/homelab/apps/fleet/FREE-ENTRA.md)
adds separate gates for Microsoft Password Platform SSO and console SAML. The
profile operator is dry-run by default; its Fleet API validation uses
`configuration_profiles/batch?dry_run=true`, without replacing global profiles.
Require exact local Mac identity, correct platform-specific profile UUIDs,
acknowledged installation, retained pre-existing profiles, and session revocation.
The Entra app/user units require focused encrypted plans before protected apply.
Browser SAML identity, device/user registration, actual Mac password sync,
offline login, and FileVault unlock must each be verified independently. Record
failed versus untested checks explicitly; Argo health is not their acceptance.
Keep identity-specific acceptance evidence in a private operator report. Public
documentation should describe the verification method without publishing account
identifiers, credentials or detailed tenant security state from the test.

Fleet adds bootstrap API regression tests for closed first-admin setup,
administrator identity validation, token revocation and credential redaction.
Backup tests cover dump and checksum failures, atomic publication, collision
handling, retention and matching scheduled/PostSync Pod contracts. The MySQL
server and dump client both permit 512 MiB packets for stored MDM packages.

The targeted protected apply validates existing platform readiness before shared
SSM/IAM reconciliation and Fleet registration. The fixed Fleet mirror inventory
must match the application's rendered images exactly and remain a subset of the
full reviewed inventory; scoped publication retains digest and complete authenticated
Harbor-pull verification. Require published Harbor digests,
ready workloads and secrets, Bound claims, the pinned public version, blocked
setup aliases, authenticated administrator access and the PostSync backup's
verified-publication log. Nightly recurrence, offsite recovery, actual device
enrollment and reversible profile delivery are separate gates. See the
[Fleet runbook](../../clusters/homelab/apps/fleet/README.md#rollout-and-validation).

On October 3, the reviewed scoped mirror, targeted apply, DNS reconciliation,
public administrator/API checks and initial backup passed; the Fleet runbook
records their workflow IDs. Omitted ExternalSecret server defaults caused
repeated Argo self-healing, so Fleet now declares refresh interval, remote-ref
strategies and template merge policy explicitly, matching the live API defaults.

The [Apple acceptance record](../../clusters/homelab/apps/fleet/README.md#apple-activation-and-device-acceptance-2026-10-03)
confirms active APNs, a user-approved Mac, a freshly acknowledged MDM query and
verified temporary profile installation/removal with baseline profiles retained.
Free enrollment uses **Personal (BYOD)** through `/enroll`; the administrator
manual-profile endpoint requires Premium and returns HTTP 402. iOS inventory
and command acceptance remain pending; the runbook owns detailed evidence,
the observed unexplained push delay and certificate renewal metadata. The
[profile verifier](../../clusters/homelab/apps/fleet/README.md#verify-reversible-profile-delivery-on-this-mac)
defaults to a preview; `--execute` targets only the exact local Mac and requires
verified removal of its temporary profile while retaining the baseline.

Sandboxed `profiles status -type enrollment` can falsely report **No**. Verify
through an approved local read outside the sandbox before diagnosing
unenrollment, and privately match serial/hardware UUID to the exact Fleet host.
Keep device identifiers, certificates and secrets out of git.
Compare agent heartbeat with MDM check-in/acknowledgement when diagnosing
delivery delays; do not duplicate writes while a command remains pending.

The October 3 Free/Entra pilot merged in [PR #1152](https://github.com/Stuhlmuller/homelab/pull/1152)
and applied the two focused Entra units without modifying existing identities
or adding licenses. Mac baseline and native PSSO profile installation passed
MDM acknowledgement, exact identifier/UUID readback and unrelated-profile
retention. Local inspection retained user-approved Fleet MDM, FileVault and the
existing secure token; screen-lock delay became immediate. Managed screensaver
preferences read back `idleTime=300`, `askForPassword=1`, and
`askForPasswordDelay=0` (display-sleep timers are separate). A supported host
refetch produced fresh inventory and a passing FileVault SQL policy result.
Company Portal, PSSO registration and password/login acceptance were still pending.

The first real console SAML callback returned `account_disabled`: Fleet matched
the signed NameID to the existing password-login account, whose SSO flag is
deliberately false. Settings readback alone had not detected this external-MSA
identity mapping difference. Preserve recovery access and correct the dedicated
Entra application's claim mapping through the SAML module; retest the browser
callback after apply.

Read-only Fleet inspection on 2026-10-06 UTC confirmed the managed **Family Mac
security baseline** appeared on the iPhone with installation status `failed`:
`MCInstallationErrorDomain (4035): Invalid profile target` and
`MCProfileErrorDomain (1015): The target device does not match this platform`.
This confirms Apple rejected that installation; Fleet's global assignment is
still visible. The same catalog profile was `verified` on one Mac and `pending`
on another. No profile settings were changed, and the operator session was
revoked. A fresh device `ProfileList` was not requested during this inspection.
See the [Mac-only migration](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#mac-only-baseline-through-individual-installs)
before treating a visible Fleet assignment as installed configuration or
removing the catalog entry, which also removes Mac assignment.

The owner then selected individual Mac installs with no global baseline
assignment. The operator now rejects global upload before credential access;
`mac-baseline --host-id <MAC_FLEET_ID>` requires an enrolled `darwin` host.
The replacement preserves every security setting but uses distinct profile and
payload identities so delayed global removals cannot erase it. The 51-test
setup suite checks phone exclusion, host identity/enrollment, unchanged settings,
unrelated-profile retention and guarded catalog removal. The Apple API/MDM
suite (17 tests), dependent AirVPN suite (24 tests), both operator dry runs and
`git diff --check` passed. Live migration requires acknowledged replacement
installation before removing existing Mac protection; these tests alone do not
establish device delivery or removal of the iPhone assignment.

An external Python `urllib` probe with its default user agent received HTTP 403
with a Cloudflare response header. The same endpoint returned 200 for curl, the
browser and an identified `Fleet-verification/1.0` client; authenticated API
checks passed with that client. The exact edge rule was not identified or
changed. If a device client receives 403, inspect edge events and capture any
needed exception in desired state; this probe does not establish device
enrollment compatibility.

## Harbor OCI rollout

The core compatibility candidate adds `scripts/ci/harbor-core-source-test.py`
to offline fixtures. It checks verified source preparation, patch validation,
retained original-manager baseline, hash mismatch refusal, unexpected archive
roots, escaping symlinks and nonempty-context refusal without network access.
The Linux `harbor-core-compatibility` job declares read-only contents and uses a
checkout without persisted credentials. It builds the pinned candidate: original
repeated-child failure must precede repaired manager tests, upstream API generation,
and complete core compilation. Networking is disabled for tests/build after
dependency download. No production inputs are mounted.
The candidate also runs the complete CSRF middleware suite and ten browser/session
compatibility cases against the replacement library. They require valid same-origin
requests and legacy response headers, reject cross-site/same-site browser requests,
and retain the non-session API exemption. The middleware unit tests use in-memory
configuration; their unused PostgreSQL bootstrap is removed.
The native suite also accepts a trusted JWK and rejects attacker key material
using its key ID. A compiled-package graph guard fails if core introduces
OpenPGP or Distribution proxy/storage/handler server packages. These are
specific prerequisite checks; unfiltered module-level findings remain in the
audit receipts and final-container/component scans are still required.
The Linux job runs the checker and private runtime-audit command for the exact
Docker-saved candidate. Offline regressions refuse wrong image/config identity,
platform/distro, stale or invalid databases, filters/exclusions, and available
fixes, while retaining unresolved findings unchanged. A privacy case requires
sanitized receipts to omit raw image metadata and explicitly deny CVE clearance.
Full registry and runtime acceptance still needs fresh Linux CI evidence.
Core publication regression cases additionally require one fixed subject,
dedicated workflow/current-main binding, complete private pulls before signing,
the enrolled signer, Harbor-only signing Pod images, and withheld outputs on
pull/digest/signature failures. The credentialed job inventory and canonical
workflow hash enroll both the publisher and pinned-reference reporting job;
dispatch verification precedes checkout and repeats before credentials.
The protected publisher also requires zero matches in the exact full-container
Grype report before registry credentials; ordinary audit fixtures continue to
retain unresolved findings for review.
No publication workflow has been dispatched as part of these source tests.
The Harbor Core publication workflow runs the pinned public Chainguard signer
fixture before AWS credential configuration, and `validate` runs the same fixture.
It imports a disposable P-256 key, requires the emitted public key to equal
OpenSSL's output, and checks the signing API flags used by the producer. A
dated 2026-10-11 read-only check found a production reviewer, but the current
source contract now declares automatic plan/production environments, with
production restricted to the exact `main` branch. Recheck live settings before
dispatch; source configuration alone is not live acceptance.
The merged publisher suite retains current-main anonymous source staging and
reader-authenticated destination-pull checks alongside the fixed-core cases. Its native
offline OCI fixture still verifies multi-platform and repeated-descriptor
byte preservation with network transports rejected.
The build then runs an isolated pinned Harbor/PostgreSQL stack. It requires
unchanged registry push/pull of eight repeated child descriptors and all blobs,
with exactly one database relation. Offline fixtures also validate the OCI
payload hashes, reject upload locations outside the disposable endpoint, and
require no published host ports, internal networking and core health ordering.
The registry client shares the proxy's network namespace and uses its loopback
listener; this avoids publishing a port from an internal-only Docker bridge.
Passing this fixture does not prove full-catalog or CVE-free publication;
see the [candidate gates](../../builds/harbor-core/README.md).

Harbor requires chart/Kustomize rendering, bootstrap and transport regression
tests, policy checks, and a state-backed Terragrunt plan. Live acceptance adds
verified TLS, API health, denied anonymous artifact pulls, successful robot
push/pull at the declared image digests, ready consumer Pods and a verified
logical database backup. See [Harbor Private OCI Registry](harbor-oci.md); a Healthy Application alone does
not establish successful private image publication.

Run `nix develop --command python3 -I scripts/ci/harbor-publish-test.py` for
publication gates. Its native staging test uses generated local OCI fixtures
and actual Skopeo, rejecting network transports and requiring exact root and
both architecture-child manifest digests through `dir:` staging and a second
copy. The fixture retains repeated child descriptors; omitting all-platform
copying fails the original-index digest assertion. This gate requires Skopeo,
not Docker or production credentials. It proves local staging behavior;
complete Harbor pulls, destination signatures, scans and live consumers still
require separate acceptance.

`talos-harbor-mirror-credential-test.py` rejects unsafe directories, files,
profile names, inherited AWS credentials and proxies, stale main, and leaked
values while exercising the owner-only credential materializer. The Talos
regression then limits the auth patch to `robot$mirror+pull`, rejects unrelated
Harbor auth, and verifies rollback removes only that owned entry. An executable
ordinary mirror rollout requires supplied reader auth unless its captured config already has the
owned reader auth. The missing-reader fixture reaches neither Harbor receipt
checks nor candidate machine-config rendering or `apply-config`. These fixtures
do not read SSM or change a node.

The fixed Traefik publication scope retains all-platform digest, tag alias and
fresh complete authenticated Harbor-pull checks. The Talos regression rejects scoped,
untitled and mismatched-revision run receipts as full-catalog evidence before
provenance or registry access; cluster-wide mirror verification requires
`Mirror all @ <run head SHA>` and the unchanged publication bundle.

The full Harbor chart is rendered twice to reject randomly generated state,
then combined with the owned manifests to validate prerequisite references and
sync ordering. A narrow policy exception accepts only the six exact empty or
public-configuration Secret payloads emitted by chart 1.19.2; actual credential
data or an added field still fails the raw-Secret gate.

## Mastodon activation gates

The [offline checks](../../scripts/ci/offline-checks.sh) exercise the Ruby launcher,
idempotent owner bootstrap, routes, fixed SMTP injection and conflict-safe public
DNS helpers. Canonical workflow security hashes include the SMTP and DNS lanes;
the DNS job installs Nix and runs both kubeconfig setup and publication inside
the pinned shell. These fixtures do not contact SMTP or publish DNS.

Before activation, require current-head protected checks and live Terragrunt
plan, complete fixed-image publication, worker capacity, ready upstream
Applications and declared SSM credentials. Register only the Mastodon target
through the saved-plan apply path. Then verify actual Argo revision/health,
migrations, owner login, loaded JSON gem, SMTP delivery and public HTTP,
WebFinger, media and streaming. The DNS workflow requires Mastodon and the
shared connector Synced/Healthy at its reviewed revision. Preserve data and
stable keys through recovery; prove backups and isolated restore separately.
See the [Mastodon runbook](../../clusters/homelab/apps/mastodon/README.md).
