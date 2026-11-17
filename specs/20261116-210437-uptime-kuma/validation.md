# Implementation validation

## US1 checkpoint (2026-11-17)

- Catalog validator61 classified apps/54 monitors;22 negative tests pass.
- Read-only live Prometheus POST evaluation45/45 parsed:43 healthy,2 down
  (undeployed Kuma and existing Octelium Enterprise rscstore readiness).
- Native adapter11 tests pass; pinned-image integration exit0, details in
  [native evidence](validation-adapter.md). Per-cycle lock regression includes real once CLI while watch remains live
  plus socket contention/release verification; complete rerun exit0.
- Rendered pinned app-template4.4.0; ownership init precedes bootstrap.
  Main mounts only data, credential only bootstrap/reconciler, no API token.
- Rendered chart244 policy assertions and overlay488 assertions pass;147
  policy unit tests pass including exact monitoring-only owner secret key.
- ConfigMap encoded object650293 bytes; data623630 bytes, below1MiB limit.
- Targeted apply suite34/34 after declared local stack generation; SSM-before-
  registration and failed prerequisites/permissions stop before writes.
- Traefik route11/11 and private DNS10/10 tests plus declaration checks pass.
- Network peer3/3 tests pass. Harbor inventory140 references and chart sources
  match after adding the rendered app-template registration.
- Full offline-static-checks.sh exit0 with current app source and updated
  credential-workflow hash. Terragrunt formatting, syntax and diff checks pass.
- acer Ready,7.95CPU/~14.9GiB allocatable; observed CPU10%,memory68%.

No protected app delivery, live Kuma availability, failure/recovery transitions
or backup/restore acceptance is claimed. T005 image publication remains pending.

## US3 backup implementation

12 backup tests pass. Actual pinned-image integration exits0 with live native
WAL writing, a distinct read-only source mount rejecting write attempts,
atomic snapshot publication and isolated same-image native login with original
monitor IDs and retained history. See validation-backup.md.

Initial backup wave1, nightly04:20 America/Los_Angeles with14 retained archives,
and isolated restore wave2 are declared. Restore has no production data mount.
Backup/restore pods deny all network ingress/egress; Kubernetes storage mounts
remain node-managed. Combined overlay854policy assertions pass. Actual
production backups/replacement/recovery acceptance remains T027 after delivery.

US3 review overrides completion: declared NetworkPolicy denial is not presently
enforced in this cluster. Copied active monitors can start during restore.
Pinned Docker network-none integration does not prove production isolation.
US3 tasks pending design repair and stronger clone execution suppression.

## US2 freshness evidence

Catalog test suite27/27 passed in repository Nix environment, including actual
promtool3.11.3 execution of17 scenarios:15-second scrape age30eligible/31down,
stale single inputs, missing/duplicate metrics, zero desired, partial readiness,
and stale rollout generation/revision. Cadence claims must match committed
ServiceMonitor interval. Repository devShell includes prometheus.cli and Nix
checks reuse its tool set; base shell explicitly skips evaluator if absent.
Native JSONata/JSON-query negative scenarios pass; timed full acceptance result
remains pending and is not inferred from unit tests.

US2 final evidence:16adapter unit tests pass; frozen actual timed acceptance
observed3healthy samples, down120026ms,recovery59958ms, paused only its test
monitor and preserved all other definitions. Focused final pinned verifyCLI
run exits0 with3healthy observations and repeats native negative/admin denial/
once-watch checks. Adapter source is unchanged between timed and focused
runs; only disposable harness redirect/watermark errors were corrected. Exact
hashes and split evidence in validation-adapter.md. T016–T017 complete locally;
production acceptance remains T026 after deployment.

US3 P1 resolution: clone-only fencing and dedicated identity now pass actual
network-enabled positive/negative integration. Positive native transition
produced>=2probes and>=1webhook; fenced42second window produced0/0 with native
auth/IDs/history and unchanged archive preserved. Actual pinned updater/tunnel
guards and poisoned inherited environment cases pass.20backup tests including
50k-row bounded-memory regression; combined overlay915policy assertions pass.
Source review found no remaining P1. See validation-backup.md; production
restoration/replacement acceptance is still T027 and has not occurred.

Final cleanup correction:22/22backup tests pass, including verifier-owned
clone discard and preexisting-destination preservation. Independent final
review passes source and updated network-enabled proof. Cleanup-only delta
was unit-tested without duplicating timed fence proof; exact evidence and
hashes retained in validation-backup.md.

## Cross-cutting gate checkpoint

Kuma catalog,27freshness/coverage tests,16adapter tests and22backup tests are
wired into offline-checks.sh; promtool is required and supplied by the pinned
Nix tool set. Runtime Docker proofs remain explicit delivery gates, already
recorded, not silently substituted by offline tests.

Final chart/overlay1159policy assertions and HCL formatting pass. Ruff and
Markdown pass; staged gitleaks scanned800KB with no leaks, artifact scan passes.
Canary route copy synchronized after full Nix check caught byte-equality drift.
Catalog is493611bytes below500KiB added-file limit, preserving decoded queries;
largest compact form query accepted by live Prometheus through temporary
read-only port-forward (stopped). Catalog27tests and backup22tests pass after
formatting; canary regression passes. Six required docs updated and wiki checker
passes. Final shell/YAML/wiki hygiene uses repository-standard helper inputs.

Full Nix/static rerun still executing in session40914, private log
/tmp/kuma-final-static2.log. T022 remains unchecked until its final result.
No full timed test replay for formatting-only deltas. Source frozen for separate
convergence; image publication44030881358 still CopyAndVerifyFixedPublicDigests.

FullNix40914 completed FAIL: tailscale-private-dns-test.py inventory guard
permits exactly original27migration names plus2OCE suffix names. Appending
Kuma private hostname fails that oldsuffix contract. Required repair must
explicitly allow the new private-only suffix without changing migrationhash/
order or26public-retirement names; add regression proving Kuma is not retired.
No source edits made during concurrent convergence. T022 remains incomplete.

## Convergence repairs T032–T033

Lifecycle validator accepts retained disabled owned records and evidence-backed
historical retirement; active apps require enabled coverage and shared active-
owner monitors cannot be paused. Current61apps/54monitors unchanged.36catalog/
PromQL tests and17adapter tests pass including pause preserving IDs/history.

Private DNS guard explicitly allows Kuma only after unchanged27migration
names/2OCE names;27DNS tests pass, unknown suffixes rejected and Kuma excluded
from26public-retirement names. Original migration order/hash unchanged;
private DNS resolver/declaration checks pass. Full static gate restarted once
both owning failures fixed: session64879, /tmp/kuma-convergence-static.log.
Ruff/Markdown/diff pass; T022 remains pending full result, T024 pending separate
repeat convergence.


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

## Completed static remainder: policy finding

Broad offline, manifest-policy and OpenWiki derivations completed before T034.
The explicit built-snapshot signature proof passed (signed accepted, unknown
key and unsigned rejected). Current manifest policy and the supported static
remainder completed through OpenTofu validation/boundary tests, Octelium native
policy checks, n8n recovery and Gitleaks without findings. Final session40003
exited 1 at Kubernetes Checkov: 12,154 passed, 3 failed, 346 skipped, zero parse
errors. All three failures are CKV_K8S_40 (high UID): Kuma first-backup Job,
backup CronJob and restore-verification Job use UID1000. No suppression added.
The owning plan/runtime identity requires a scoped correction and native image
permission proof before final validation can be complete.


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


## T037 native ping validation

Catalog/freshness suite37tests and adapter18tests passed. The exact pinned Kuma
image at UID/GID10001 ran the bounded probe-only integration mode successfully:
bootstrap/login/reconcile and once/watch remained valid; native JSON-query
accepted200/statusOK and rejected500/Error, malformedJSON, missing status,
wrong status and302redirect. Prior timed failure/recovery evidence is retained;
no redundant full timed replay was needed for this target predicate change.
Harness SHA256: `6f895f634d84125dabf1f1c1952da9c6e4900004d44d78e72677666b72158ced`. Adapter implementation unchanged.

Pinned chart plus overlay rendered1216policy assertions with zero failures;
rollout annotation is declarative only. Checker remains strict for Prometheus
freshness and limits the native status exception to prowlarr-http and its exact
owner/URL/expectation. Before replacement, all546historical row identities,
monitor IDs, timestamps and statuses were read back at original captured cutoffs
and saved in acceptance-before-replacement.json, spanning55monitor IDs.
No source push or live mutation occurred. Final targeted convergence is next.
