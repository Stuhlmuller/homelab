# Validation guide: Chainguard image automation

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

This guide covers staged repository implementation. Contract/render commands
exist now; Harbor publication, workload migration, promotion and live recovery
remain gated. Do not deploy from this guide until their reviewed code,
credentials and companion governance changes exist.

## Baseline and local checks

From the repository root:

```bash
python3 -I scripts/ci/speckit-check.py
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command python3 scripts/harbor-image-inventory.py
```

Expected: Spec Kit and repository checks pass. The repaired inventory helper
currently reports 85 named references and seven unresolved digest-only chart
pins; missing renders still prevent complete consumer acceptance. See
[inventory](migration-inventory.md).

The implementation is on branch `codex/chainguard-image-automation` at the
recorded baseline. No live infrastructure or remote Git state was changed.

After implementing the planned helper and tests:

```bash
nix develop --command python3 -I scripts/ci/image-automation.py check
nix develop --command python3 -I scripts/ci/image-automation.py render --check
nix develop --command python3 -I scripts/ci/image-automation-test.py
nix develop --command bash scripts/ci/static-checks.sh
```

Expected: strict enrollment/state validation, deterministic updater targets,
full rendered Harbor-reference coverage and focused negative tests pass.
The helper uses committed paths and fixed recipe IDs. `check` and
`render --check` are local, read-only operations with no credentials.

The anonymous Chainguard registry currently exposes the pilot latest index as
`sha256:3de78d5699d76c56f74a4a47abcd81f22f5a16757eee9fac45837fb2ae3f0e06`
with `linux/amd64` child `sha256:e85f358d0552f65088c7c25f2182a842d673ea22a6cdc4a878f7fec2be3cc57a`
and `linux/arm64` child `sha256:edc6e7d57c2e292c4df2e4bc22fe331efb4ab5ae0b14a6adf41cce866e087200`.
This is access/platform evidence only; it is not a Harbor publication receipt or
workload rollout proof.
The paused Kiali curl candidate currently resolves to
`sha256:d262b3773a248e4cdb66de162c3fc882672756d38b6206f20071049e95a98ba1`
with `linux/amd64` child `sha256:31ded4cdc3eb7bd2f3f67ea3020573b5bcd345c65e28a4dbff06c390b94eb633`
and `linux/arm64` child `sha256:bc02b15e092f9b2d5ee2fd54a89e69b882882c5679e1b833b860fc0a8576f0f2`;
this is likewise source evidence only until Harbor publication and consumer pulls
are verified.

For live inventory, use an approved Kubernetes context and keep the raw Pod
JSON outside the public repository:

```bash
kubectl get pods -A -o json > /tmp/chainguard-inventory-pods.json
nix develop --command python3 scripts/harbor-image-inventory.py \
  --pods /tmp/chainguard-inventory-pods.json
```

Supply every pinned chart's `helm template` output with repeated `--render FILE`
arguments, including hooks. Resolve operators' image defaults even when their
Pods do not currently exist. Publish only sanitized image identities, not raw
Pod objects, environment values or credentials. The denominator is active
consumers, not historical catalog rows.

## Activation prerequisites

- Companion github-iac plan reviewed and applied: ruleset separation, real
  candidate checks, verified App identities/installations and main-only
  unattended environments. Existing protected environments retain reviewers.
- Fresh proposer ESO Secret Ready; promoter key restricted to dedicated CI;
  source/Harbor and notification grants verified without printing values.
- Harbor healthy with storage headroom, native import rules reconciled, pilot
  image and updater controller digest completely verified and retained.
- Exact pinned Helm/Kustomize renders pass; shared Terragrunt/OpenTofu format,
  plan and policy gates pass for affected stacks. Generated `IaC/live` remains
  generated. Apply through the existing reviewed delivery workflow.
- Every pilot target is explicit, baseline function/known-good digest recorded,
  Renovate ownership excluded only for that target, and recovery recipe tested.
- Schedules, functional checks, observation deadlines and notification route are
  committed. No live mutation is needed to pause, repair or enroll resources.

## Acceptance order and release samples

Complete recovery readiness T049, then activate the stateless pilot in T041.
T042 release acceptance and T050 recovery drills are independent successors:
no major-version pair or fresh upstream rebuild is needed to start safety drills.
Both acceptance results remain required before completing the feature.

T042 must select and verify real sample pairs before running its release drill.
Use T005's accessible candidate inventory; do not assume Python has a suitable
major pair or that historical tags are accessible. Choose a separate isolated
canary when needed, with no production data or credentials. Record:

- Exact immutable Chainguard source refs/digests and actual release versions;
  one pair crosses a stable major and one is a same-version rebuild.
- Required platform/child digests, current access checks, full Harbor download
  receipts and retained baseline for every sample.
- The declared canary application/target, compatible startup/functional recipe,
  isolated storage boundaries and bounded replay sequence in enrollment/workflow.

The canary lane starts at the verified baseline and advertises only the recorded
verified successor; use the normal updater, checks, signed promotion and Argo
path. Exact replay samples are reviewed test configuration and cannot loosen
production latest/stability rules. Missing accessible pairs leave T042/SC-004
open with concrete evidence; proceed with T050, without fabricating releases or
marking the whole feature complete.

## End-to-end scenarios

Use the main-owned workflow's declared operations (`verify`, `promote`,
`observe`, `recover`) and repository-owned canary/failure configuration.
Capture safe run URLs, commit SHAs, image identities and elapsed times.
Do not print raw registry/GitHub responses that might contain credentials.

| Scenario | Action through declared path | Expected evidence |
| --- | --- | --- |
| Import only | Enable pilot's hourly native pull and verification; leave updates paused. | Same source/destination digest, required child platforms, complete intended-access pulls, retained tag and verified alias within 6 hours; no workload commit. |
| Initial migration | Review enrollment and exporter image origin change after publication. | Rendered/running Harbor digest, UID/filesystem/CA behavior, `/livez`, `/metrics` and original Prometheus scrape pass. |
| Stable major | Use the actual major-version pair and isolated canary selected and verified in T042. | Signed conventional C is checked then promoted without PR/human action within 1 hour; functional rollout within 30 minutes. Missing sample access leaves SC-004 open and does not delay T050 recovery drills. |
| Same-tag rebuild | Replay T042's verified same-version digest pair through the declared canary track. | New verified receipt and digest update; two later unchanged cycles create zero duplicate commits or workload changes. |
| Incomplete/wrong artifact | Exercise declared fixture/test lane with missing blobs, platform or digest mismatch. | Candidate never advertised/consumed; failed stage visible within one scheduled check; retained working release unchanged. |
| Ineligible version/access | Exercise prerelease, dev, downgrade, missing source permission or restricted-to-public mapping. | No main or workload change; exact access/track failure identified; no restricted copy made public. |
| Semantic scope | Propose an unenrolled image, unrelated key, workflow change, symlink or policy edit. | Image Update Gate fails before main; no privileged candidate code runs. |
| Real-check enforcement | Fail a required genuine check or supply a same-name check from another producer. | Main remains B; missing/skipped/spoofed contexts cannot promote C. |
| Main race | Advance main through normal reviewed work while C validates. | No force push or stale promotion; candidate reconstructed and checks repeated on the new base. |
| Stateless rollback | After T041, deliver the declared unhealthy exporter canary with previous digest retained; do not wait for T042. | Current-data recipe says safe; the failed journal blocks routine updates while its bound signed revert succeeds within 30 minutes; rejection persists for two cycles. |
| Stateful unsafe/unknown | Exercise the declared recovery lane with changed/inconclusive data evidence. | Routine updates and rollback are denied; a control-only pause/rejection is permitted despite failed/paused state, with an alert within 5 minutes and no image or data restore. |
| Failed recovery/denied Git | Deny recovery validation/write or fail the recovery health fixture. | One recovery attempt maximum; journal prevents re-promotion even if pause commit fails; alert within 5 minutes, unaffected apps continue. |
| Restart/idempotency | Restart updater or interrupt/resume workflow through declared test controls. | Deployment journal and Git controls survive; no repeated failed digest, lost pending rollout or duplicate commit. |
| Registry/bootstrap recovery | Follow reviewed cold-bootstrap/mirror recovery procedure in its declared rehearsal lane. | Current and previous known-good copies pullable; source provenance available; updater activates only after dependencies; no manual live patches. |

The canary and failure lane are implementation work, not permission to mutate
production by hand. Stateful rehearsals require isolated disposable data and
declared storage boundaries. No automated restore touches production data.

## Read-only rollout evidence

After implementation, these existing commands inspect declared state:

```bash
kubectl -n argocd get applications
kubectl -n argocd get imageupdaters
gh run list --repo Stuhlmuller/homelab --workflow image-automation.yml
gh api repos/Stuhlmuller/homelab/commits/main --jq '.sha'
```

For each migrated consumer, correlate the exact main commit with its successful
checks, publication receipt, Argo revision, actual runtime child digest and
functional result. Observe source discovery/import/verification, validation,
commit, deployment, recovery/pause and last success distinctly. An Argo Healthy
badge or a successful replication task alone is insufficient.

## Completion

## Current implementation evidence

On 2026-10-06 UTC, the repository static gate passed after the updater source
restoration and ran the image automation and promotion checks. A later isolated
cache run reached the existing Octelium restore drill, which stopped because
the sandbox PostgreSQL process cannot allocate shared memory; this is an
environment limitation, not an image automation failure. No live Harbor,
Kubernetes, GitHub App, or companion-repository mutation was performed. The
direct promotion job remains gated by the reviewed production environment and
`IMAGE_AUTOMATION_PROMOTION_ENABLED`, which is not enabled in this branch;
Harbor public import is enabled in desired state but is not live in the audited
cluster; Image Updater workload enrollment remains paused.
The isolated-cache catalog check also passed with 85 declared references and
confirmed enrolled Harbor targets have exclusive Renovate ownership rules.
The Harbor render checker now rejects an enrolled destination without a
verified publication receipt; its focused regression suite passes.
The Harbor replication declaration now covers both enrolled repositories,
`chainguard/python` and `chainguard/curl`, with exact stable-tag rules.
The live read-only check returned `401` for the private Harbor destination and
found no `harbor-bootstrap` Job or `harbor-chainguard-replication` ConfigMap;
the repository desired state therefore remains unapplied live.

Finish only when every active consumer is migrated or has a specific exception,
all spec success criteria have evidence, secret/publication/ownership checks
pass, and retirement/bootstrap/recovery/knowledge-base docs match behavior.
If direct promotion fails after candidate validation, the workflow revalidates
the same candidate and creates or reuses its proposal PR, then requests normal
protected auto-merge. Document the exact direct-write blocker, measure time to
PR creation, and expose pending approvals; do not claim direct promotion
acceptance passed.
