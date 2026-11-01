---
type: audit
title: "Issue burndown — November 1, 2026"
description: "Complete 98-issue inventory, verified closures, bounded source repairs and outstanding acceptance gates."
tags: [operations, issues, security, validation]
---

# Issue burndown — November 1, 2026

Baseline `d1408e1a09e86d35d215d1460807a98d1b5b3a53`; 98 open issues,
excluding pull requests. Discovery was split across CI, runtime and operations;
a different agent verified every closure and implemented patch before delivery.
This dated inventory records source progress separately from runtime acceptance.
Six issues were closed: two completed defects, one retired workload request,
and three duplicate incident reports. The recurring dashboard remains open.

## Delivery and validation

The source batch repairs workflow-event validation, release supply-chain and
serialization, Renovate discovery, validation-cache isolation and credential
staging. It corrects the Prometheus runbook. No credential rotation, storage
migration, dormant workload activation or manual infrastructure repair occurs.

Focused release publication, policy, parsing, cache and discovery fixtures pass;
independent review checks the same source. The full `nix run .#validate` gate
cannot complete on this Mac: the existing Mastodon PostgreSQL fixture exhausts
host shared-memory allocation during `initdb`. This is an unavailable full gate,
not a passing test. The offline static/security gate passes separately.
Protected GitHub checks and normal merge remain required before source delivery
is complete; hosted release/discovery acceptance remains separate.

## Outstanding gates and source ownership

- Image issues require fresh scans of exact immutable artifacts, supported
  replacements, declared publication and service-specific rollout evidence.
  Historical failed scans are not current vulnerability counts. Follow
  [Harbor](harbor-oci.md), [inventory](../workloads/inventory.md) and each workload
  README; do not activate a retired app to satisfy an obsolete upgrade request.
- SQLite/Prometheus/PostgreSQL moves require fenced backup, independent restore,
  capacity and retained rollback. Follow [storage](../architecture/storage-and-state.md).
- Application health propagation still depends on single ownership of Argo
  parameters and bounded Cordium hooks (#891, #908, #890, #889). Preserve this
  order rather than changing parent health before child sync is bounded.
- Credential, organization/App privilege, human-access and recovery issues need
  their specific reviewed management paths and authorization. Source fixes do
  not prove credential revocation or live authorization. Existing service
  reconciliation helpers and [secret boundaries](../architecture/secrets-and-identity.md)
  remain authoritative; do not bypass them with manual mutations.
- The initial read-only operations probes did not establish protected remote
  access or intended unauthenticated denial for NOFX/Dispatcharr. Keep #776,
  #777 and #866 open; repeat their exact transport, catalog and authenticated
  acceptance checks through the declared paths before closure.
- Many August implementation PRs were closed unmerged. A draft's old test
  comment does not establish current implementation. Reuse compatible source
  only after checking current callers and acceptance requirements.
- #920 still applies to current coverage verification: an offline reproduction
  using the existing [Grype fixture](../../scripts/ci/harbor-core-scan-check-test.py)
  passes zero-match publication validation without package inventory. The
  [native receipt verifier](../../scripts/ci/harbor-native-chainguard-receipt.py)
  also accepts successful scans with an empty severity summary. Independent
  execution confirmed this validator behavior; it does not prove any real
  scan omitted packages. Add positive, artifact-bound SBOM/package coverage
  evidence before calling zero findings clearance. Do not require nonempty
  vulnerability matches: clean, covered images legitimately have none.

The remaining rows are triage dispositions, not independently certified runtime
findings. Every open issue retains its own acceptance requirements. The
[Istio acceptance record](audit-2026-09-04.md#istio-and-dispatcharr-revalidation-september-5)
and [cleanup fixture](../../scripts/ci/terragrunt-stack-test.py) support completed
closures; OctoBot retirement is in PRs #1305–#1307. No new 24-hour observation or
fresh full image scan is claimed.

## Complete starting inventory

<!-- markdownlint-disable MD013 -->

| Issue | Request | Disposition at this checkpoint |
| --- | --- | --- |
| [#1799](https://github.com/Stuhlmuller/homelab/issues/1799) | Complete task lifecycle with revision-bound GitOps verification | Active implementation owned by the lifecycle task; preserve its branch and pilot. |
| [#1061](https://github.com/Stuhlmuller/homelab/issues/1061) | Emergency Bypass - 9/20/2026 | Duplicate of #1058; canonical incident remains open. |
| [#1060](https://github.com/Stuhlmuller/homelab/issues/1060) | Emergency Bypass - 9/20/2026 | Duplicate of #1058; canonical incident remains open. |
| [#1059](https://github.com/Stuhlmuller/homelab/issues/1059) | Emergency Bypass - 9/20/2026 | Duplicate of #1058; canonical incident remains open. |
| [#1058](https://github.com/Stuhlmuller/homelab/issues/1058) | Emergency Bypass - 9/20/2026 | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#933](https://github.com/Stuhlmuller/homelab/issues/933) | [P1] Remediate Metrics Server runtime image vulnerabilities | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#932](https://github.com/Stuhlmuller/homelab/issues/932) | [P1] Remediate NFS provisioner image vulnerabilities and obsolete toolchain | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#931](https://github.com/Stuhlmuller/homelab/issues/931) | [P2] Align GitHub-verified signatures with the configured no-reply identity | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#929](https://github.com/Stuhlmuller/homelab/issues/929) | [P1] Remediate Kiali operator and server image vulnerabilities | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#928](https://github.com/Stuhlmuller/homelab/issues/928) | [P2] Remediate Grafana and dashboard-download image vulnerabilities | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#926](https://github.com/Stuhlmuller/homelab/issues/926) | [P1] Upgrade vulnerable Prometheus monitoring images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#923](https://github.com/Stuhlmuller/homelab/issues/923) | [P3] Correct stale Prometheus alerting validation docs | Prometheus validation and notification docs match current Discord contract. |
| [#920](https://github.com/Stuhlmuller/homelab/issues/920) | [P2] Reject vulnerability scans with no package coverage | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#919](https://github.com/Stuhlmuller/homelab/issues/919) | [P2] Upgrade vulnerable cert-manager runtime images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#918](https://github.com/Stuhlmuller/homelab/issues/918) | [P2] Upgrade vulnerable local-path storage provisioner runtime | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#917](https://github.com/Stuhlmuller/homelab/issues/917) | [P2] Remove or bound the scanner unsafe OpenPGP dependency | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#916](https://github.com/Stuhlmuller/homelab/issues/916) | [P2] Rebuild the vulnerability scanner with patched Go libraries | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#915](https://github.com/Stuhlmuller/homelab/issues/915) | [P2] Harden scanner arguments and fail closed on extraction errors | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#909](https://github.com/Stuhlmuller/homelab/issues/909) | [P1] Add host filesystem and disk-health monitoring for node-local state | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#908](https://github.com/Stuhlmuller/homelab/issues/908) | [P1] Bound Cordium nested Argo sync before enabling parent health propagation | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#900](https://github.com/Stuhlmuller/homelab/issues/900) | [P1] Upgrade vulnerable Multica web and PostgreSQL images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#903](https://github.com/Stuhlmuller/homelab/issues/903) | [P1] Upgrade vulnerable policy-bot runtime | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#902](https://github.com/Stuhlmuller/homelab/issues/902) | [P1] Upgrade vulnerable AFFiNE and pgvector images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#904](https://github.com/Stuhlmuller/homelab/issues/904) | [P2] Upgrade vulnerable media application runtimes | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#901](https://github.com/Stuhlmuller/homelab/issues/901) | [P1] Upgrade vulnerable NOFX frontend and backend images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#899](https://github.com/Stuhlmuller/homelab/issues/899) | [P1] Upgrade vulnerable Multus CNI image | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#896](https://github.com/Stuhlmuller/homelab/issues/896) | [P1] Upgrade vulnerable OpenClaw and Nix helper images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#897](https://github.com/Stuhlmuller/homelab/issues/897) | [P1] Upgrade OctoBot runtime with fixable critical vulnerabilities | Superseded by completed retirement; no active OctoBot runtime or route remains. |
| [#895](https://github.com/Stuhlmuller/homelab/issues/895) | [P2] Rebuild Compass without fixable HIGH vulnerabilities | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#898](https://github.com/Stuhlmuller/homelab/issues/898) | [P2] Upgrade vulnerable Dispatcharr and Redis images | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#893](https://github.com/Stuhlmuller/homelab/issues/893) | [P2] Make Descheduler honor its declared 30-minute cadence | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#889](https://github.com/Stuhlmuller/homelab/issues/889) | [P1] Gate Argo CD dependency rollout on runtime health | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#892](https://github.com/Stuhlmuller/homelab/issues/892) | [P1] Move NOFX SQLite off NFS | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#894](https://github.com/Stuhlmuller/homelab/issues/894) | [P1] Move Grafana SQLite off NFS | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#891](https://github.com/Stuhlmuller/homelab/issues/891) | [P2] Eliminate dual ownership of argocd-cmd-params-cm | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#890](https://github.com/Stuhlmuller/homelab/issues/890) | [P1] Propagate child Application health to Argo CD parents | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#888](https://github.com/Stuhlmuller/homelab/issues/888) | [P2] Enable Renovate coverage for the pinned Nix toolchain | Nix discovery enabled with reviewed grouped toolchain updates; lock refresh/hosted proof outstanding. |
| [#887](https://github.com/Stuhlmuller/homelab/issues/887) | [P2] Track Helm chart pins embedded in Terragrunt | HCL and NFS Helm discovery implemented; hosted update evidence outstanding. |
| [#886](https://github.com/Stuhlmuller/homelab/issues/886) | [P2] Remove direct operator identity from Argo CD admin RBAC | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#879](https://github.com/Stuhlmuller/homelab/issues/879) | [P1] Attest Cordium boundary from server-side AccessLogs | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#877](https://github.com/Stuhlmuller/homelab/issues/877) | [P2] Serialize semantic releases | Serialized publisher/current-main checkout and isolated repeat-publication test; hosted acceptance pending. |
| [#874](https://github.com/Stuhlmuller/homelab/issues/874) | [P2] Make workflow-event policy reject null-valued pull_request_target | Policy rejects null-valued unsafe workflow events; regression and independent review passed. |
| [#876](https://github.com/Stuhlmuller/homelab/issues/876) | [P1] Pin the semantic-release toolchain, not only its wrapper action | Release toolchain integrity-locked; live publisher acceptance pending merge. |
| [#875](https://github.com/Stuhlmuller/homelab/issues/875) | [P2] Restore Renovate coverage for SHA-pinned GitHub Actions | Action version metadata restored; hosted discovery acceptance outstanding. |
| [#873](https://github.com/Stuhlmuller/homelab/issues/873) | [P1] Keep AWS credentials valid for the full production apply | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#872](https://github.com/Stuhlmuller/homelab/issues/872) | [P1] Make pull-request plan identities technically read-only | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#868](https://github.com/Stuhlmuller/homelab/issues/868) | [P2] Disable legacy QNAP NFSv2 through a declared management path | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#867](https://github.com/Stuhlmuller/homelab/issues/867) | [P1] Move Prometheus and Alertmanager off unsupported NFS | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#866](https://github.com/Stuhlmuller/homelab/issues/866) | [P2] Restore the Octelium-protected Dispatcharr route | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#864](https://github.com/Stuhlmuller/homelab/issues/864) | [P1] Keep static validation caches outside the repository | Private external validation cache and failure cleanup; full static gate limited by host fixture failure. |
| [#860](https://github.com/Stuhlmuller/homelab/issues/860) | [P1] Enforce organization 2FA and secure repository defaults | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#859](https://github.com/Stuhlmuller/homelab/issues/859) | [P0] Reduce organization-wide GitHub App privileges | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#857](https://github.com/Stuhlmuller/homelab/issues/857) | [P1] Reconcile the Octelium service catalog from reviewed main | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#848](https://github.com/Stuhlmuller/homelab/issues/848) | [P2] Prove the Octelium Kubernetes authorization boundary end to end | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#847](https://github.com/Stuhlmuller/homelab/issues/847) | [P1] Validate and safely rotate the shared Octelium kubeconfig | Validated create-only credential staging; live rotation/cutover explicitly outstanding. |
| [#846](https://github.com/Stuhlmuller/homelab/issues/846) | [P1] Make Cordium Kubernetes access fail closed | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#844](https://github.com/Stuhlmuller/homelab/issues/844) | [P2] Harden LiteLLM runtime and remove its Kubernetes API token | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#842](https://github.com/Stuhlmuller/homelab/issues/842) | [P2] Remove unused Crossplane core and recover cluster capacity | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#841](https://github.com/Stuhlmuller/homelab/issues/841) | [P2] Retire obsolete Octelium demo and TUN paths without weakening the primary access plane | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#840](https://github.com/Stuhlmuller/homelab/issues/840) | [P3] Remove verified dead repository and duplicate validation plumbing | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#838](https://github.com/Stuhlmuller/homelab/issues/838) | [P1] Require reviewed plans for production changes | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#836](https://github.com/Stuhlmuller/homelab/issues/836) | [P1] Keep deleted-unit state cleanup encrypted | Completed: inherited enforced state/plan encryption; real-render regression independently passed. |
| [#833](https://github.com/Stuhlmuller/homelab/issues/833) | [P1] Keep operational diagnostics private | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#830](https://github.com/Stuhlmuller/homelab/issues/830) | [P1] Remove bootstrap escalation identity | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#815](https://github.com/Stuhlmuller/homelab/issues/815) | [P0] Bind infrastructure applies to reviewed plans | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#813](https://github.com/Stuhlmuller/homelab/issues/813) | [P0] Restore protected repository rules | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#805](https://github.com/Stuhlmuller/homelab/issues/805) | [P3] Triage conflicting PRs and remove retired Argo marker applications | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#804](https://github.com/Stuhlmuller/homelab/issues/804) | [P1] Upgrade access-platform components compatibly | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#803](https://github.com/Stuhlmuller/homelab/issues/803) | [P1] Complete credential remediation | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#802](https://github.com/Stuhlmuller/homelab/issues/802) | [P1] Complete integrity diagnosis and recovery readiness | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#801](https://github.com/Stuhlmuller/homelab/issues/801) | [P2] Diagnose and remove LAN-to-wired and NAS latency/packet loss | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#800](https://github.com/Stuhlmuller/homelab/issues/800) | [P2] Fix Cordium workspace nested-wildcard TLS | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#799](https://github.com/Stuhlmuller/homelab/issues/799) | [P2] Isolate Deluge privilege from the rest of the media namespace | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#797](https://github.com/Stuhlmuller/homelab/issues/797) | [P2] Complete least-privilege Argo AppProject migration | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#796](https://github.com/Stuhlmuller/homelab/issues/796) | [P2] Reduce Kubernetes LIST latency and stale object/alert noise | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#795](https://github.com/Stuhlmuller/homelab/issues/795) | [P2] Make Argo CD and alerts reflect generated Octelium runtime health | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#794](https://github.com/Stuhlmuller/homelab/issues/794) | [P2] Stabilize OpenClaw probes and eliminate NFS read storms | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#793](https://github.com/Stuhlmuller/homelab/issues/793) | [P1] Restore resilient resource headroom | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#792](https://github.com/Stuhlmuller/homelab/issues/792) | [P1] Verify backup and restore coverage | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#791](https://github.com/Stuhlmuller/homelab/issues/791) | [P1] Pin deployable artifacts and enable vulnerability scanning | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#790](https://github.com/Stuhlmuller/homelab/issues/790) | [P1] Move Octelium PostgreSQL off NFS and prove restore | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#789](https://github.com/Stuhlmuller/homelab/issues/789) | [P1] Patch affected application dependencies | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#788](https://github.com/Stuhlmuller/homelab/issues/788) | [P1] Upgrade unsupported platform dependencies | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#787](https://github.com/Stuhlmuller/homelab/issues/787) | [P1] Enable repository vulnerability alerts | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#786](https://github.com/Stuhlmuller/homelab/issues/786) | [P1] Restrict CI cloud trust | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#785](https://github.com/Stuhlmuller/homelab/issues/785) | [P1] Restore resilient capacity and remove emergency access | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#784](https://github.com/Stuhlmuller/homelab/issues/784) | [P1] Enforce workload network isolation | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#783](https://github.com/Stuhlmuller/homelab/issues/783) | [P1] Retire bootstrap privilege after use | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#782](https://github.com/Stuhlmuller/homelab/issues/782) | [P0] Restore application sandbox and contain high-authority credentials | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#781](https://github.com/Stuhlmuller/homelab/issues/781) | [P1] Prevent stale infrastructure runs from blocking delivery | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#779](https://github.com/Stuhlmuller/homelab/issues/779) | [P1] Make infrastructure validation merge-blocking | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#778](https://github.com/Stuhlmuller/homelab/issues/778) | [P1] Restore service-mesh node readiness | Completed: merged IPv6 readiness repair, historical 24-hour acceptance and fresh read-only health verification. |
| [#777](https://github.com/Stuhlmuller/homelab/issues/777) | [P0] Enforce intended human-access policy | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#776](https://github.com/Stuhlmuller/homelab/issues/776) | [P0] Restore protected remote access | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#775](https://github.com/Stuhlmuller/homelab/issues/775) | [P0] Restore cluster capacity and clear stale state | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#774](https://github.com/Stuhlmuller/homelab/issues/774) | [P0] Complete security remediation program | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#679](https://github.com/Stuhlmuller/homelab/issues/679) | Emergency Bypass - 8/18/2026 | Open; implementation and/or acceptance evidence outstanding. Follow the issue-specific prerequisites. |
| [#159](https://github.com/Stuhlmuller/homelab/issues/159) | Dependency Dashboard | Recurring Renovate dashboard; retain open. |
