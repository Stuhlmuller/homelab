# Image prerequisite delivery — T003 in progress

Owner: adguard-tailnet-dns; same issue #1842 and feature worktree.
User repeated deployment instruction; no further Notion updates are authorized.
The previous scoped convergence turn found no correction needed for T001–T002;
38 remaining tasks stay open. No feature-wide convergence claim.

Prerequisite PR: <https://github.com/Stuhlmuller/homelab/pull/1843>
Remote branch: feat/adguard-image-prerequisite
Head: 07de14cfdaffdf315ba21ba66d59013225d02e79
Base: 6a7a2b8d48be8c0e27cfa17f9fc24748dcca9e24
GitHub createCommitOnBranch produced a VALID verified signature. Source changes
are only the image catalog entry and its publication runbook paragraph.
Canonical feature selection/spec artifacts remain local in the feature worktree.

Focused image checks passed in the preceding increment. Full local static gate
is running; required PR CI is pending. Ownership recorded with pr-delivery.py.
System gh 2.46 lacks --slurp; use the pinned Nix devShell CLI for that helper.
No protected merge, Harbor publication, app deployment or DNS change yet.

Next: inspect exact-head CI after its normal cadence, repair relevant failures,
verify all current rules/signatures/required checks, merge without bypass,
then dispatch harbor-mirror.yml image_scope=all at exact new main. Verify run
success and complete authenticated AdGuard pull before consuming source merges.

## Read-only rollout investigation while CI runs

Traefik deployment is 1/1 available and certificate Ready. The private Service
has its expected assigned endpoint. The existing codex-signer Ingress alone
among the four callback Ingresses has no loadBalancer status; this is a candidate
cause of aggregate Progressing, not a proven root cause. No events were present.
Resource health is stored in appTree, not individual Application resource rows.
Revisit at T033 through the owning source; no live repair was attempted.

## Corrected catalog synchronization

The full local static gate failed image-rewrite-check.py because the admission
catalog copy must equal the full Harbor catalog. Synchronized the copy without
changing admission policy, then restarted the full static gate. Added the
publication boundary to the authored Harbor wiki page. Current signed head:
24b09c17d2acca36f7fc0cbc2f64ecab54bf2455. All three prerequisite commits have
VALID GitHub signatures. Required CI must pass on this new head.

The separate Harbor-core audit failed validation:remediation on the first head
(run 43775557415/job 133000928925) and unchanged base main (run
43687411060/job 132730663831). The existing open finding in
openwiki/operations/harbor-oci.md records the same failure and owning next step:
inspect the protected report, repair the runtime dependency, rerun its audit.
No audit suppression or protection change was made.

Focused repair verification passed: image-rewrite-check.py reports 225 reviewed
sources; openwiki-check.py passes; git diff --check passes. Full local static
validation remains running in exec session 40782, log
/workspace/adguard-progress/image-static-repaired.log. It began before the wiki
addition; the separate wiki check covers that later documentation change.

Current exact-head repo job 133003668312 is in Verify Offline Nix Checks;
Terragrunt static job 133003732669 is in Run Static Checks. All introduced
commit signatures verified VALID, no review threads, base unchanged. Latest
release-dry-run 133003781194 passed; older same-head run was cancelled when
the PR body changed. Do not mistake the superseded cancellation for latest
required status. GraphQL isRequired identifies successful policy-bot: main;
required Actions check App ID 15368 verified. Fresh merge readiness is still
required after all pending checks finish. No merge or publication attempted.

Resume: inspect cached evidence and local session, refresh exact-head required
checks with backoff, repair failures, protected squash merge with expected head,
verify signed sole-parent main commit, dispatch harbor-mirror.yml all with
exact current main, retain successful complete-pull receipt. T003 stays open.

Publication preflight history: no active mirror run among latest three. Most
recent completed run 41598610421 was cancelled. Prior 41490485349 passed
static validation but failed Copy And Verify Fixed Public Digests with the
sanitized category phase=setup, category=command-failed on 2026-11-02.
The exact underlying cause is not public; this is not evidence of missing
AdGuard content or a successful full-catalog receipt. Inspect fresh dispatch
result rather than assuming historical publication succeeds.

Final-tree validation continuation: local session40782 completed its offline
checks, then the Nix signature test found the newly evaluated manifest-policy
output unbuilt. The wiki file changed during the preceding Nix build, so the
evaluation and built output refer to different trees. Started full static checks
on the now-stable final tracked tree: session38574, log
/workspace/adguard-progress/image-static-final.log. Do not modify tracked
files while this validation runs. GitHub checks already use the final commit.
The exact-head repo job advanced past offline checks to final checks; Terragrunt
static remains running. Latest Harbor-core audit job133003668279 reproduced
validation:remediation, same as the documented baseline failure.

## Protected merge and publication dispatch

All current required checks passed on signed head
24b09c17d2acca36f7fc0cbc2f64ecab54bf2455. GitHub accepted the ordinary protected
squash merge for PR1843 (no admin bypass). Merge commit
48e8b9e4627f4a37f30d00f2d28b96d64133996e has a valid verified signature, sole
parent6a7a2b8d48be8c0e27cfa17f9fc24748dcca9e24, and was exact current main.
All four merged files match the reviewed local files byte-for-byte.

Dispatched harbor-mirror.yml at main with expected_sha
48e8b9e4627f4a37f30d00f2d28b96d64133996e and image_scope=all. Confirmed run:
<https://github.com/Stuhlmuller/homelab/actions/runs/43777917412>
Publication remains pending; T003 stays open until successful authenticated
complete pulls. No AdGuard workload or tailnet DNS change has been deployed.

Local full static validation remains in session38574. Preserve the tracked
working tree while it runs; afterward reconcile the four merged local files
with origin/main without losing .specify/feature.json or the feature artifacts.
Next: inspect run43777917412 result; diagnose sanitized failures rather than
blind retries. Complete T003 only with the full publication receipt.

Scoped source convergence found no new corrective work for the merged image
prerequisite: both catalogs equal, exactly one immutable AdGuard entry, original
manifest hash matches, amd64/arm64 present, documentation states the publication
boundary. All five constitution principles checked for this source increment.
No artifacts changed during convergence; spec/plan/tasks hashes remain the prior
recorded values. This is not feature convergence: T003 publication and T004–040
remain open.

Read-only runtime follow-up: Harbor and platform-image-policy report
Synced/Healthy/Succeeded with repository revision
48e8b9e4627f4a37f30d00f2d28b96d64133996e. The catalog-only reconciliation
is healthy; no AdGuard Application exists yet. Publisher run43777917412 remains
in Validate Harbor Mirror / Run Static Checks.

Full local static gate completed exit0 (session38574; image-static-final.log),
including final-tree offline checks, signed-cache acceptance/unknown-key and
unsigned rejection, module/fixture checks, gitleaks and Checkov (0 unreviewed
findings). Reconciled canonical feature branch by verifying all four local files
against merged commit, preserving their patch receipt, then fast-forwarding
to48e8b9e4627f4a37f30d00f2d28b96d64133996e. Only feature selection and untracked
spec artifacts remain local; no user changes lost. Publication still pending.

Publisher advancement: Validate Harbor Mirror succeeded. Copy Reviewed Public
Images job133014963656 passed exact-current-main validation, verified client
installation, tailnet join and AWS credential configuration; Copy And Verify
Fixed Public Digests is running. This is not yet a complete pull receipt.
Watcher session80837 continues at120-second intervals.

## Publication outcome checked after environment restart

Run43777917412 completed: Validate Harbor Mirror passed, Copy Reviewed Public
Images failed. The public job log reports phase=authenticated-pull and
category=command-failed at2026-11-16T05:20:27Z; it does not identify root cause.
No blind retry dispatched. T003 remains open; authenticated publication is not
proven. Preserved encrypted diagnostic artifact14199244243 before its expiry,
SHA256c7721abe73f39f46f763ff86f1d0764c4942ac29c80ce295aa3cf0789cce3142,
849bytes, in the private workspace progress directory outside the repository.
No plaintext diagnostic was decrypted or published. Old watcher80837 is no
longer active after environment restart. Next inspect the protected failure
through the declared diagnostic custody path, fix the owning cause, then retry
publication with fresh current-main checks. Application consumption remains gated.


## OIDC restored; authenticated read diagnostics

On 2026-11-17 UTC, the user confirmed the homelab AWS OIDC connection was
resolved. Managed manifest-backed AWS profile/config selectors with inherited
cloud proxy/CA bindings successfully authenticated STS as the codex-cloud-agents
role in account 716182248480. SSM reads succeeded; no AWS writes occurred.
No static AWS credentials were requested or used.

The fixed public publication failure source is
`docker.io/library/python@sha256:227b6570d6ee07061ae6ca2eb04dedfb6d2b34045835f343065b9869e4d427ea`,
phase `authenticated-pull`, category `command-failed`. This differs from both
AdGuard and the feature's Python init digest. The protected encrypted diagnostic
remains preserved; its plaintext has not been accessed. No publication retry.

Using the SSM-backed mirror pull robot in temporary private client configuration,
`regctl image copy --force-recursive` successfully pulled the complete mirrored
AdGuard OCI index into a fresh local OCI directory. Subsequent local digest
inspection matched
`sha256:e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c`.
The same read-only Python-index probe reached its local 180-second timeout.
That timeout does not diagnose the original CI failure. Earlier skopeo copy
probes were inconclusive because local signature policy files were absent;
no signature policy was weakened. Temporary auth and image directories were
removed when the diagnostic finished. No diagnostic process remains active.
T003 stays open: the successful AdGuard read is not a full publisher success.

The two stored Tailscale operator OAuth parameters were readable (Version 2).
The repository helper's direct transport failed in this cloud environment;
a separate token request through the managed proxy, refusing redirects, returned
HTTP 401 for the stored pair. Values stayed private in memory. AWS OIDC repair
therefore does not resolve the independent Tailscale enrollment credential issue.
The user was asked for an existing Tailscale administrator environment or private
API-key file path, explicitly not pasted credentials. That answer is pending.
The existing rotation helper strips AWS selectors and disables proxies; if repair
must run here, implement and validate a narrow managed-cloud compatibility path
through normal source delivery before live writes. Do not bypass its guards.

Next: obtain existing administrator/diagnostic custody access, diagnose the
publisher failure and repair through its declared pipeline, then resume T031.
No AdGuard deployment, signing, DNS cutover, credential mutation or Notion write
occurred. All earlier implementation validation remains applicable.
