# Plan amendment: R1 and R2

Stage: narrow speckit-plan correction, 2026-11-15. This edits the established
plan in place rather than rerunning setup_plan.py and overwriting it with a
blank template. The installed skill and template were read in the initial plan
stage; its design/research/constitution/post-hook contract is reused. Hooks are
still empty. No feature, branch, task list or worker was recreated.

R1 resolution: Cutover execution reruns every required direct acceptance check
in the same invocation; a saved receipt alone is never authorization. Full-set
maximum 300 monotonic seconds; success-to-apply maximum 60 seconds. Reject
future/negative times and clock regression. Bind source/deployed/config revisions,
Service UID/IP, peer key/name/tag/signature, plan digest and full before/after DNS
policy. Re-read main/config/endpoint/live policy/plan bytes immediately before
apply. Preserve native state locking/stale-plan rejection. Negative cases include
expired checks/delay, future timestamps, changed bindings and plan bytes.

R2 resolution: Explicit --mode rollback has its own checks. Validate administrator
access, current-main restoration source, captured prior policy against reviewed
pre-cutover source, fresh live policy against activated/already-restored policy,
and the exact DNS-only plan. Preserve timing/drift/unknown-value guards. Never
invoke AdGuard DNS/UI/filter/peer availability gates in rollback; private resolver
availability is diagnostic. Already-restored is a no-op; inspect policy/state
after uncertain results. Require an eligibility regression with AdGuard offline
and an unrelated-drift negative case.

Affected artifacts: plan.md, contracts/dns-and-admin.md, data-model.md,
quickstart.md. This makes existing FR-008/013/015/019 and US4 concrete; no new
user-facing scope or authority. Specification and both checklist states remain
unchanged. Constitution check remains satisfied: repository-owned changes,
protected credentials, validated exact mutation, documented recovery and existing
ownership. No new research uncertainty; these are local guard/contract decisions.

Validation: matching timing/mode clauses, local links, whitespace and unchanged
spec/built-in/custom checklist markers verified. Next separate stage: re-review
CHK015 and CHK017 plus related consistency items. Do not mark them complete in
this amendment. No implementation, runtime test, merge or deployment performed.
