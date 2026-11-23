# Workflow checkpoint

## Specify — 2026-11-16

Owner: Codex `uptime_kuma` worker, coordinated by the requesting chat.
Issue: <https://github.com/Stuhlmuller/homelab/issues/1847>.
Notion: <https://app.notion.com/p/41be535fc6288136935bf601083debf5?pvs=204>.
Branch: `codex/uptime-kuma`.
Base: `48e8b9e4627f4a37f30d00f2d28b96d64133996e`.
Feature: `specs/20261116-210437-uptime-kuma`.

Invoked the local `speckit-specify` skill against the verbatim request recorded
in spec.md. Used the installed `create_new_feature.py --json --timestamp
--short-name uptime-kuma` helper to resolve the template, create exactly one
feature and persist `.specify/feature.json`. Replaced its template placeholders
with the behavior specification and evaluated the requirements checklist.
No implementation, deployment or constitution amendment performed.

### Workflow provenance

Installed `.specify/init-options.json` identifies Spec Kit 0.15.1, Codex skills,
Python scripts and timestamp feature numbering. The local skill and
`common.py` use file-backed feature selection and a first-match template stack.
The active template is `.specify/templates/spec-template.md`: no override,
preset or extension template exists. `extensions.yml` installs assess but has
`hooks: {}`, so no pre/post hooks apply. The newer upstream standalone
`resolve_template.py` is absent; the inspected installed `common.resolve_template`
used by `create_new_feature.py` is the applicable equivalent for this checkout.
No tooling upgrade or fabricated command was used.

Read official upstream methodology `spec-driven.md`, `docs/quickstart.md`,
`docs/reference/agentic-sdd.md`, and `templates/commands/specify.md` at revision
`a227e38315cd38172b04f2fb8f06ce8b69b38331`:
<https://github.com/github/spec-kit/tree/a227e38315cd38172b04f2fb8f06ce8b69b38331>.
The newer upstream command composes templates and allows an environment feature
override; this repository deliberately uses its installed resolver and
file-backed feature state instead. Historical methodology examples of branch
creation and sample constitution articles do not override installed behavior.
Remaining command definitions will be consulted for their own stages, not
claimed as already read.

### Constitution and repository context

Reused constitution 1.0.0: repository-owned desired state, public secret safety,
validation before live change, reviewable documented changes, repeatable
bootstrap and ownership. Read AGENTS, task lifecycle/runbook, app onboarding,
homelab context, OpenWiki quickstart, application pattern, app onboarding
runbook and relevant inventory. AGENTS says executable CI/protections govern
readiness; documentation adds no routine approval round.

### Evidence and decisions

- GitHub issue/PR searches for uptime kuma returned no existing work item.
- GitHub fetch and read-only Kubernetes inventory succeeded.
- Live Application status includes staged Missing resources and intentionally
  zero-replica apps. `Synced/Healthy` is not proof of a working app endpoint.
- Live workloads include stopped AFFiNE, legacy OpenClaw, Mastodon web/worker,
  Bulldozer, Crossplane and nix-builder. Clarification/planning must reconcile
  their current desired state and retain explicit dispositions, not activate
  them or silently claim coverage.
- Scope includes active user apps and supporting services, with shared coverage
  only when justified by the actual check. Existing target failures remain
  visible; unrelated repairs are excluded.
- Agent-selected defaults: minute checks for continuous apps, schedule-derived
  freshness for scheduled jobs, 30-day history, private authenticated UI,
  repeatable stable monitor configuration and isolated recovery proof.
- Requirements quality checklist: 16/16 passed; no unresolved markers.

### Next stage

Dispatch `speckit-clarify` in a separate turn for this same feature/worktree.
Resolve decisions from current source/live evidence; ask the user only for
irrecoverable material input. Then stop at the clarification checkpoint before
planning. No current blocker; no live writes or deployment retries.

## Clarify — 2026-11-16

Invoked local `speckit-clarify`; prerequisite resolver confirmed the same feature.
Read upstream `templates/commands/clarify.md` at the pinned revision above.
No pre/post hooks apply. Reused constitution context. No user questions asked;
five agent decisions were integrated into spec.md with evidence, not fabricated
user answers. No implementation or production mutation.

Resolved scope granularity (app/owned service, not every transient resource),
freshness and target-specific semantics for existing support telemetry, current
private mesh access rather than stale Octelium-default prose, safe generated
owner bootstrap without account resets, and pause-with-history retirement for
owned monitors. Concrete endpoints, software versions, storage, recovery and
reconciliation mechanisms remain planning work.

Coverage scan:

| Category | Status |
| --- | --- |
| Functional scope and behavior | Resolved |
| Domain and data model | Resolved |
| Interaction and UX | Clear |
| Nonfunctional quality | Resolved |
| Integrations and dependencies | Resolved; implementation selection deferred to plan |
| Edge cases and failure handling | Resolved |
| Constraints and tradeoffs | Clear |
| Terminology and consistency | Clear |
| Completion signals | Clear |
| Placeholders | Clear |

Sections changed: Status, Clarifications, Functional Requirements, Assumptions.
Requirements checklist re-evaluated: 16/16 → 16/16; no newly passing items,
regressions or unchecked items. Checklist bytes unchanged as required by clarify.
`git diff --check` passed. No essential unresolved ambiguity or tool blocker.
Next: separate `speckit-plan` turn in the same worktree and feature.

## Plan — 2026-11-16

Invoked local speckit-plan and setup_plan.py; read its pinned upstream command.
No extension hooks. Created plan.md, research.md, data-model.md,
contracts/native-api.md and quickstart.md. No tasks or implementation created.
One read-only research subagent inspected the pinned native Kuma API; planning
owner verified source/config/registry details and repository delivery owners.

Design selects Kuma 2.5.11 with resolved digest, same-image native adapter,
loopback-only owner initialization, private Traefik route, app-template,
retained Acer-local SQLite and checked NFS archives. Existing Prometheus signals
cover supporting workloads with explicit target health and freshness. Image-only
prerequisite and targeted SSM/app registration lanes precede deployment.
Inventory baseline is the source/live union of 60 entries; the new app adds one.

Constitution gates pass before and after design. XERJ tools/CLI unavailable;
pinned peer tree/source and official upstream inspected instead, as explicitly
recorded in research. Pinned-image runtime tests, exact per-app endpoint checks,
image publication, saved plans and live acceptance remain implementation/delivery
obligations, not claimed results. No unresolved design question needs user input.

Validation: artifact presence, no template placeholders, feature identity,
relative links and git diff --check. Next: separate requirements checklist
creation followed by explicit review, then tasks and read-only analysis.

## Checklist generation — 2026-11-16

Invoked local speckit-checklist with the coordinator's explicit scope. Prerequisite
resolver found plan/research/model/contracts/quickstart. No hooks apply; existing
constitution and feature artifacts retained. Created checklists/deployment.md
with 24 requirements-quality questions, all unchecked, all traceable to feature
artifacts. Scope: bootstrap/deployment safety, complete meaningful coverage,
state/reconciliation/recovery and measurable executable acceptance. Audience:
coordinator/reviewer; standard depth; before tasks. No user questions necessary.

Validation: 24 unique sequential IDs, 24 unchecked and zero checked custom items,
git diff --check. Built-in requirements checklist unchanged. Next: separate
explicit coordinator review; do not generate tasks or implement before review.

## Plan repair R1 — 2026-11-16

Read the separate requirements review (23 pass / CHK009 open). Corrected the
plan's fixed 120-second allowance to exactly two actual configured source
observation/scrape periods, matching spec FR-004. Catalog records each source's
period and configuration evidence; Kuma check cadence is explicitly unrelated.
Research and data model align; quickstart requires the negative 15-second-source
fixture (31-second age fails, 30-second age is eligible). Only the existing
explicit scheduled-work exception remains.

No spec, reviewer checklist or review record changed. No implementation.
Validation: obsolete threshold removed, aligned artifact references inspected,
git diff --check passed. Next: separate coordinator re-review of CHK009.

## Tasks — 2026-11-16

Invoked local speckit-tasks and setup_tasks.py using the completed artifacts and
24/24 separate requirements review. No hooks apply. Created tasks.md with 28
unchecked dependency-ordered tasks: setup 2, foundational image publication 3,
US1 9, US2 3, US3 4, cross-cutting/delivery/acceptance 7. FR-001–012 and
SC-001–007 are mapped. Freshness includes the R1 sub-60-second negative case.
Pinned-image, backup, unauthorized-access and failure/recovery validation are
explicit; image prerequisite precedes consuming merge and runtime acceptance
precedes completion. Separate source and final convergence turns remain required.

No parallel-write markers: same-file and shared-delivery dependencies dominate;
optional disjoint review opportunities are documented. Validation: sequential
unique task IDs, unchecked state, story labels/paths, complete FR/SC mapping,
git diff --check. Next: separate read-only speckit-analyze. No implementation.

## Analyze and implementation start — 2026-11-16

Coordinator reports separate read-only speckit-analyze passed: 19/19 FR/SC
covered, 28 mapped tasks, no findings. Implement invoked for T001–T005 only.
Prerequisites resolve; requirements 16/16 and deployment 24/24, zero unchecked.
No hook applies. Existing ignore rules cover local state/cache; no new build
context/package publication is introduced in this prerequisite.

## Image prerequisite implementation checkpoint

Read-only analyze passed: all 19 FR/SC covered by 28 mapped tasks; no findings.
T001–T004 complete. PR #1848 contains only nine image-publication source files,
with signed head b02ca03aa9937481a0eb7515a62b28085093ce58. Independent coordinator
review found no actionable issues in exact scope, precredential validation,
exact-main guards or policy hashes. Focused tests pass; workflow policy 61/61,
policy unit tests 146/146, inventory/OpenWiki/actionlint/shell/diff checks pass.
Base publisher suite passed 104 tests; two need cosign/skopeo supplied by Nix.
Full Nix gate remains running; T005 stays unchecked pending protected merge
and successful exact-main publication/full-pull receipt. No consumer source exists.

### Continuation handoff at 05:45 UTC

Required Terragrunt/static gate completed successfully; `repo` remains running,
no failed checks. Local full Nix gate session 8197 is actively executing offline
tests (started 05:34); retain it, do not launch a duplicate. The optional app
attach_artifact call hung for approximately ten minutes and was terminated to
prevent its queued old-head checkout reset racing later work. Ordinary PR URL
is durable; UI attachment is not confirmed. Sole CI query owner remains this
worker. Continue independent app source/local tests while observing T005, but
no consumer merge until exact-main publication receipt. Temporary Python helper
image also verified 3.13.16/SQLite3.40.1, but is unnecessary and not selected.

## US1 implementation checkpoint (06:01 UTC)

T006–T014 complete in source with evidence in validation.md,
validation-adapter.md and catalog-evidence.md.61 apps/54 monitors,22 catalog
tests,11 adapter tests, actual pinned integration exit0 including real once
CLI while watch remains running. Review found two issues (NOFX service name,
lifetime writer lease); both fixed and executable regressions pass.

Generated-stack apply suite34/34; route/DNS/policy/render checks pass. Full
offline-static-checks.sh exit0 on current source. No production writes occurred.
Secrets are exact generated SSM key, scoped projection and policy; workload
uses Harbor pinned digest but no consuming PR has been created or merged.

Image prerequisite PR1848 current signed head
c99d073207ee138d50bd8e7845ef13a85299764b; local branch reset to that ancestor
while preserving all US1 edits. Exact admission catalog and second credential
workflow hash repairs delivered to that PR. Current CI running; network-policy
job133852756165/run44027956057 failed (log pending run completion). Existing
Harbor remediation investigation belongs coordinator; worker owns PR polling.
T005 remains unchecked, no publication. No local test process remains running.
Next separate implementation turn US2/US3; continue protected image delivery
when actual required gates permit. Never merge consumer before publication.

## US3 review blocker — restore isolation

Independent review found P1: cluster NetworkPolicy enforcement remains staged,
so a deny-all declaration does not enforce restore egress isolation. Starting
the copied Kuma DB starts active monitors; reuse of the main ServiceAccount
permits backend traffic. Docker --network none proves local restore mechanics
but not deployed isolation. T018–T021 remain unchecked pending narrow owning-
stage design repair, re-analysis and separate implementation. No CNI expansion
or ad hoc production writes. Parent coordinates plan repair after US2 checkpoint.
Existing snapshot/restore local successes remain factual but do not satisfy
the deployment isolation requirement.

## US2/US3 bounded implementation checkpoint (06:16 UTC)

T015 complete:27catalog tests including17actual PromQL scenarios;16adapter
unit tests. Actual pinned JSON-query tests pass healthy, missing/multiple/false,
HTTP401/302 and unauthorized administrative reads. Native live heartbeat
collector fixed to monitorID/timestamp (history rows use monitor_id/id).
T016–T017 implemented but unchecked while final timed native acceptance/verify
integration continues in child adapter, exec session56517. Do not cancel or
duplicate it. Executed adapter/integration files frozen for this run.

US3 local mechanics:12tests and pinned WAL/read-only-source/native restore
integration pass,854rendered overlay policy assertions pass. However P1 restore
isolation gap leaves T018–T021 unchecked. Separate reviewer repaired plan,
research,data-model,native contract,quickstart only; parent will reconcile tasks
and re-analyze before clone-fence implementation. No runtime repair performed.

Image PR1848 c99d073: repo and transient network-policy rerun now pass.
Static Policy remains running; existing Harbor compatibility audit fails
validation:remediation (coordinator owns diagnosis). No merge/publication.
No production changes. Parent requested checkpoint while real acceptance
continues so separate artifact stages can proceed.

## Separate tasks reconciliation — P1 restore repair

Read all five repaired design artifacts; invoked installed speckit-tasks setup
helper (existing feature/tasks preserved, no hooks). Updated reopened T018–T021
and deployed acceptance T027; appended T029 clone fence, T030 network-enabled
positive/negative startup suppression proof, T031 dedicated restore identity.
Dependencies and FR/SC coverage explicitly include the repair.31 unique task
IDs verified; prior IDs/completion preserved; new/reopened tasks unchecked.
No runtime/source edits in this stage. Stop before read-only analysis.

Independent US2 timed run returned real3healthy observations, failure120026ms,
recovery59958ms, testpaused and unchanged other monitor definitions. Later
verify harness assertion failed because '/' correctly302redirects; adapter
truthfully reported unhealthy. Child corrected disposable fixture to /dashboard
and is running a focused3-observation verifyCLI proof. This is not a full
integration exit0 claim; T016–T017 remain pending until evidence checkpoint.

## Repair analysis and implementation handoff

Separate read-only analysis passed repaired31tasks with no gaps. US3
implementation authorized only against repaired clone-execution-fence design;
reviewer checklist unchanged. Backup worker owns backup/runtime/test/jobs/README;
primary worker owns Kustomization/network wiring and delivery.

## Repaired US3 implementation checkpoint

T018–T021 and T029–T031 complete locally after separate plan/tasks/analysis.
Exact-schema clone transaction/reopened and pre-spawn checks, fixed minimal
child environment, dedicated restore identity and explicit network enforcement
limits implemented. Streaming deterministic history hashing avoids retention-
scale materialization;50k512byte rows stayed below2MiB Python allocation.

20backup tests pass. Final pinned network-enabled integration exits0: positive
control native healthy→down emitted at least2probes/1webhook; fenced clone
observed42seconds (>=2x20-second configured fixture intervals) emitted exactly
0probes/0notifications. Native needSetup=false/login/details/paused IDs/history
and unchanged archive pass; inherited Node/proxy/Kuma/tunnel poison excluded.
Actual pinned updater/tunnel guard positive/negative counters passed without
public calls. Combined rendered overlay915policy assertions and diff checks pass.
See validation-backup.md for exact hashes/commands. No production writes.

US2 T016–T017 also completed from split truthful native evidence (timed
failure120026ms/recovery59958ms plus focused verifyCLI exit0); no redundant
timed replay. Source reviewer found no remaining P1 fence defect.

Image prerequisite PR1848 merged at verified mainb6063d41; local branch
codex/uptime-kuma rebased with autostash preserving consumer edits. Publication
run44030881358 remains ValidateHarborMirror/RunStaticChecks; T005 unchecked
until successful fixed-scope full authenticated pull receipt. Optional Harbor
remediation finding recorded separately; it was not a required merge gate.
Next: T022/T023 full checks/docs, separate source convergence, protected consumer
delivery only after publication, then actual live acceptance.

Final independent repair re-review PASS: P1 resolved; updated evidence22/22
backup tests includes safe verifier-owned clone discard and preservation of
preexisting destinations. Cleanup-only post-integration change has focused
regressions; native fence/network execution proof remains unchanged. Reviewer
confirmed evidence/source/streaming/identity contract. Deployed restore remains
T027. Stop this implementation turn for cross-cutting checks/docs stage; do not
wait on unrelated mirror static validation to transition source work.

## T022–T023 checkpoint before separate source convergence

T023 complete: six required docs and current-routing correction, desired-state
wording without deployment claims. T022 CI wiring complete; focused/render/
lint/secret checks pass; full corrected Nix/static gate40914 still running, so
T022 unchecked. First full attempt caught Traefik canary-copy drift, repaired.
Python source formatted to repository rules, task Markdown wrapped, test SQLite
connections explicitly closed. Catalog493611bytes passes added-file size limit
without changing decoded PromQL; live largest-query form parse verified.

Source staged71files, about800KB; no consumer PR or merge yet. Source is frozen
for independent convergence while the full gate runs. Publication44030881358
passed validation and is copying/verifying exactmainb6063d41; T005 pending.
Worker retains sole publication/check query ownership. Stop before convergence.

## Concurrent read-only gate monitoring result

FullNix40914 failed the DNS inventory suffix guard in
scripts/tailscale-private-dns-check.py:55. Original27migration+2OCE fixedset
rejects new private-only Kuma suffix. Reported to coordinator/convergence
reviewer for append-only remediation task; no source/tasks mutated. Preserve
original27hash/order and26retirement names in fix. Sourceconvergence owns tasks.
Publication44030881358 remains copy/verify; no receipt claimed.

ConsumingPR preparation: branchcodex/uptime-kuma based on signed merged
mainb6063d41,71stagedfiles (~800KB), no sourcepush before convergence findings
resolved. Next PR must describe private61-app/54-monitor coverage, native
reconciliation and verified clone-fenced backups plus applicable test evidence;
normal protected checks/merge, publication receipt prerequisite unchanged.

## T032–T033 implementation checkpoint

Both convergence findings repaired with passing focused regressions, no design
change. T03236catalog+17adapter tests, explicit durable retired-source marker,
retained disabled ownership and active/shared-owner coverage; current catalog
unchanged. T03327DNS tests preserve27migrationhash/order and26retirement names,
reviewed Kuma private-only suffix accepted, unknown suffixes rejected.

Full static session64879 running /tmp/kuma-convergence-static.log. T022 remains
pending; T024 not marked until separate source re-convergence. Publication
44030881358 still copy/verify; transfer output intentionally private and active
job log unavailable (404), so no byte-progress claim or duplicate dispatch.
Source frozen for repeated convergence; consumer push remains pending that
review. No production application changes.

Repeated independent source convergence PASS: no new gaps; T032/T033 proven.
T024 marks source review only, T028 live convergence remains pending.
Consuming PR body prepared locally; creation waits full local static result,
merge additionally waits exact-scope publication receipt. No source push yet.


## T034 precise routing prerequisite

Kuma alone retains Traefik Application Synced and verifies the named routing
Deployment current generation, positive desired replicas and matching
updated/ready/available counts. The named Certificate must be Ready at its
current generation, with the declared traefik-tls secret and wildcard DNS name.
All other targets and prerequisites retain their previous checks. No live
mutation or unrelated ingress repair occurred.

Actual apply-script regression suite passed 38 tests in 90 seconds, including
unrelated aggregate Progressing success, unsynced and missing dependencies,
stale generation, zero/partial replicas, wrong certificate identity, false or
stale certificate readiness and preserved other-target aggregate health.
ShellCheck, changed Markdown lint and diff whitespace checks passed. Broad
static retry94546 predates this behavior fix and remains pending; it is not
claimed as final-source evidence. Separate targeted re-convergence is next;
this behavior change has not been pushed.

## Delivery continuation access checkpoint

Separate T034 source convergence passed with no gaps. Reviewed preflight fix
and receipts remain local, ready for signed publication to PR1850. The next
GitHub GraphQL request returned HTTP401 Bad credentials; no push, merge or
apply was attempted after that failure. Resume after supported environment
credential refresh, preserving expected remote head
9cb322dfb872dd8b1ee751ccef211b9133c7a9ca. Image publication proof is complete;
current-head required CI and protected merge still precede targeted apply.

GitHub connector contents write produced unsigned d785b02237b70deccade703d8c81d9e58491964e.
It was retained at codex/uptime-kuma-unsigned-backup and removed from the PR
using an exact expected-head lease. Connector verified the restored signed
head 9cb322dfb872dd8b1ee751ccef211b9133c7a9ca. No local edits were lost.
The connector cannot replace the signed GraphQL commit and workflow-dispatch
path; supported managed GitHub credential renewal remains necessary.

Static remainder40003 finished with the three UID policy findings documented
in validation.md. Final source remains undeployed; no check was waived.

## Narrow task reconciliation: runtime UID

Read all five repaired design artifacts and appended T035 only. Existing task
IDs/completion history remain intact. The task requires complete identity
consistency, actual high-UID pinned-image native/backup/fenced-restore proof,
negative permission/identity coverage and clearance of all three Checkov
findings without suppression. No runtime source changed in this turn. Next:
separate read-only analysis, then bounded implementation and convergence.


## Final local gate repairs: T035 and T036

All non-root processes now use UID/GID/fsGroup10001 consistently. Initial root
ownership remains mount-root-only chown10001:10001/chmod0700. Actual pinned
adapter integration exited0 with projected root:10001 mode0440 credentials and
config, persistent data ownership, bootstrap/login/reconciliation, once/watch,
JSON negatives, denied authentication and three-observation verification.
Actual pinned backup integration exited0 with owned data/scratch, projected
reads and write denial, separate read-only live-WAL EROFS proof, positive
probes/webhook, and42seconds fenced zero-probe/zero-notification native restore
with unchanged archive, IDs/history/authentication and environment guards.
Exact harness hashes and complete evidence are in the adapter/backup reports.

Kubernetes Checkov now passes12,157 checks, zero failures,346 unchanged skips,
zero parse errors. Policy unit tests150/150 and rendered assertions1216/1216
pass. The three public/test secret literals use independently reviewed exact
path/check/fingerprint records with maximum occurrence1. Boundary suite14tests
passes (3 optional native-mode tests skipped); the actual full scanner covers
1679tracked files,28reviewed findings and zero unreviewed findings. Changed
values, paths, checks, extra findings and repeated occurrences remain denied.
No UID policy suppression or scanner bypass was added. Ruff, ShellCheck,
Markdown and YAML lint pass (existing YAML style warnings only).

T022 local evidence is composed explicitly: pre-T034 broad offline/manifest/
OpenWiki derivations, final38apply regressions, current manifest and full static
remainder through final scans, followed by the exact UID/literal repairs and
affected native/render/policy/scanner checks above. No claim of one uninterrupted
final-tree full replay is made. Final-head remote CI remains required after
signed publication. No GitHub CLI auth retry, merge or deployment occurred;
credential renewal and separate final source convergence remain next steps.

## Final source convergence and credential-blocked handoff

Separate final source convergence passed T035/T036 with no gaps or new tasks;
review verified the current fixture hashes. All local validation is complete
within the compositional scope recorded above. No test runners remain active.

PR1850 remains draft at verified signed head
9cb322dfb872dd8b1ee751ccef211b9133c7a9ca. The reviewed final corrections and
evidence remain in24modified tracked files in this worktree. The unsigned
connector experiment is isolated on codex/uptime-kuma-unsigned-backup and is
not an ancestor of the PR head. No additional authentication retries occurred.

T025–T028 remain pending. Resume after supported managed GitHub CLI credential
renewal: publish the exact reviewed changes as verified signed commits, obtain
complete required checks/reviews on the final head, compare the image receipt
bundle, use normal protected expected-head merge, verify signed reachable main,
then dispatch the declared targeted Terragrunt Apply at exact current main.
Verify GitOps revision/readiness before separate functional, persistence,
backup/restore and runtime-convergence acceptance. No deployment is claimed.


## Protected delivery and deployment readiness

PR1850 merged normally on 2026-11-17 at 08:32:47 UTC, signed merge
1dfeb92a3654bae7a927c8adf4ed454347820dd7, sole parent b6063d41, reachable main.
All four introduced commits were verified signed; all seven required contexts
passed, with no reviews/threads required or unresolved. Optional Harbor audit
still reports its existing remediation finding and was not treated as a gate.
Kuma image publication matched the consuming merge bundle exactly.

First targeted apply44047731567 passed static checks but stopped at the
precredential current-main guard after unrelated AdGuard PR1851 advanced main.
No checkout, credentials or live apply occurred in that failed job. Inspected
new signed main ec53ed3d3b9b2397bf41abfd8935561e8e5d5b67: Kuma manifests,
IaC, apply workflow/script and scoped image inventory were byte unchanged.
The normal exact-main retry44050500579 completed successfully, both static and
Terragrunt Apply. No guard was bypassed and no ad hoc cluster mutation occurred.

At 09:12 UTC, Argo uptime-kuma was Synced/Healthy with successful operation,
chart4.4.0 and both Git source revisions ec53ed3d. Deployment had one ready Pod;
app and reconciler were Ready, both init containers exited0, and both runtime
containers reported the pinned Harbor digest7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9.
Both5Gi PVCs were Bound, owner ExternalSecret Ready, reconciler health command
exited0. First-backup and restore-verification Jobs each completed successfully;
their native evidence is still to be inspected in the separate acceptance stage.

T025 is complete. T026–T028 remain pending: private UI authentication, exhaustive
coverage/observations and failure/recovery, retained IDs/history across the
code-owned replacement, backup/restore evidence, and runtime convergence.
Nightly scheduled execution has not yet been observed. Working branch for
acceptance evidence/follow-up changes is codex/uptime-kuma-acceptance based on
current main; original implementation PR remains merged.


## Live acceptance checkpoint before Prowlarr correction

At deployed ec53ed3d, source/live union validates61classified apps and54monitors.
Native verify reports all54definitions correct and three recent observations
for every monitor;52healthy. Octelium Enterprise workload signal remains an
existing target health failure. Prowlarr HTTP is a confirmed probe mismatch:
initialize.json redirects302to login, while deployed2.5.2.5491-ls160 exposes
anonymous /ping returning200with statusOK. Pinned upstream PingController
checks configuration repository data (cache5seconds), returning500on failure.
Do not accept the redirect; correct to an exact JSON status predicate through
source review. No runtime catalog change was made in this acceptance turn.

Controlled acceptance passed3healthy samples, failure120023ms, recovery59922ms.
Disposable monitor55is paused; other definitions unchanged. Two declared once
runs each reported managed54and zero creates/changes/pauses/resumes/settings;
health command exited0. Before-replacement IDs/counts/first/last heartbeat
references are preserved in acceptance-before-replacement.json; original full
read-only SQLite snapshot is /tmp/kuma-history-before.json.

Real private browser URL <https://uptime-kuma.stinkyboi.com/dashboard> showed the
native login, rejected invalid credentials and opened the authenticated
Dashboard with the actual owner credential. Final check used TLS verification
with the existing provider CA imported into Chromium trust, not disabled TLS.
Curl independently reported certificate verification success. Credentials were
read in memory from their authorized mount and never printed or captured.

First backup and isolated restore both logged ok,54monitors/54heartbeats and
identical archive SHA256179f82012d7c2c92ba7bed68e9aed74c09925c3664846de87690166f1dfd9f13.
Both Jobs completed successfully. Nightly CronJob remains unsuspended with
`20 4 * * *`, America/Los_Angeles, Forbid; no nightly execution yet observed.
T026/T027 remain open for the corrected probe and declared replacement/history
proof. Separate targeted convergence and implementation are next; no source
annotation or live restart has been performed.

## T037 implementation checkpoint

Prepared the Prowlarr JSON `/ping` correction with stable ownership key, exact
HTTP200/statusOK and pinned five-second configuration-cache limitation. Added
source-controlled acceptance rollout annotation; no live mutation or push.
The baseline file preserves all55IDs and concrete first/last heartbeat times
from546historical observations for post-replacement row-presence checks.
Current deployed acceptance remains52healthy of54, with Prowlarr's known probe
mismatch and the existing Octelium Enterprise target-health failure. Private
TLS-verified UI login/denial and controlled120023ms down/59922ms recovery passed.
The correction and replacement must complete through protected PR/GitOps before
T026/T027 can close. Separate targeted source convergence follows local tests.
