# Image Automation And Image Updater

## Current contract

The controller source is staged with zero replicas; its stack is not registered
in `IaC/terragrunt.stack.hcl`. Read-only checks on 2026-10-10 confirmed that its
Argo CD Application and Deployment are absent. Register the stack through the
normal Terragrunt workflow before treating the controller as deployed.
Enrollment is generated from
`clusters/homelab/apps/harbor/image-automation.json` and must match
`python3 -I scripts/ci/image-automation.py render-check`. The intended
write-back branch is `main:codex/image-updater-proposals`; a separate main-owned
workflow validates signed single-parent candidates before any non-force update.
Routine updates require verified Harbor receipts, complete platform pulls and
workload compatibility. Recovery binds the originating failure and retained
known-good digest; unsafe or unknown current data pauses and alerts without data
restore. Enable replicas only through a reviewed change after recovery readiness.

Renovate continues to own unrelated image and chart updates. Enrolled Harbor
targets transfer ownership only after their `automation_status` becomes
`enrolled`; the checked-in pilot is still `not-enrolled` while publication and
compatibility evidence are pending.

The staged Terragrunt Application defines three sources: the pinned Image
Updater Helm chart, a repository values ref, and the Kustomize source containing
the paused configuration. The configured replica count stays at zero until recovery
readiness is accepted.

## Verification

```sh
python3 -I scripts/ci/image-automation.py check
python3 -I scripts/ci/image-automation.py render-check
nix develop --command bash scripts/ci/static-checks.sh
```

For a reviewed direct promotion, first enable the repository variable
`IMAGE_AUTOMATION_PROMOTION_ENABLED=true`, then dispatch `image-automation.yml`
with `operation=promote` from `main`. The job fetches only the proposal branch,
validates the exact single-parent candidate with trusted `main` code, compares
the live ref again, and requests a non-force update. It requires the reviewed
`homelab-production` environment. No controller or workflow may force-push,
cherry-pick, or execute proposal-branch code.
The independent Image Update Gate runs before that write job and checks the
candidate tree's semantic scope with read-only permissions.
The scheduled `observe` job reads the durable journal and sends bounded Discord
alerts for expired failed or paused observations; missing notification
credentials fail visibly without printing the webhook.
If the protected direct write fails after the same candidate validation, the
workflow revalidates the proposal and queues its branch for normal protected
auto-merge.
Promotion also rejects proposal branches containing files outside the candidate
metadata, state journal, and enrolled consumer targets, including symlinks.

Recovery uses the same candidate contract. A failed deployment blocks routine
updates; a bound rollback requires a fresh safe current-data result. Unsafe or
unknown data records a pause and failed-digest rejection without restoring
data. State is journaled before ref movement so interruption cannot create a
second recovery attempt.

## Rollback

Keep the previous known-good Harbor digest and deployment record. If promotion
or rollout fails, use the repository-owned `recover` and `pause-reject`
operations; do not patch Argo CD or Kubernetes resources manually. A reviewed
resolution and newly verified healthy baseline are required before resuming
routine updates.
