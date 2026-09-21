# CodeQL Legacy Analysis Retirement

Tags: #operations #validation #security

The CodeQL aggregate on recent PRs reports a missing `/language:actions`
configuration even though the current Actions job completes. The old
`.github/workflows/codeql.yml:analyze` configuration stopped running after
[PR #552](https://github.com/Stuhlmuller/homelab/pull/552). Current scans use
`.github/workflows/codeql.yml:analyze-actions`. A successful current upload
does not by itself establish complete introduced-alert comparison.

The [committed retirement scope](../../../scripts/config/codeql-legacy-actions-retirement.json)
names exactly 97 old analyses on `refs/heads/main`, including each analysis ID,
commit, timestamp, configuration and tool identity. The September 6 inventory
also found 277 old analyses across 107 PR refs; those remain outside the scope.
All current configurations remain outside the scope. Main retirement is the
smallest proposed repair for the comparison warning; success must be verified
with fresh main and PR analyses after the change.

## Preview

The [helper](../../../scripts/ci/codeql-retire-legacy-actions.py) uses the
existing authenticated GitHub CLI for read-only local inspection:

```sh
retirement_receipts="$(mktemp -d)"
nix develop --command python3 scripts/ci/codeql-retire-legacy-actions.py \
  preview --output "$retirement_receipts/preview.json"
```

Preview paginates the analysis inventory, checks exact legacy identities and
the successful current-main scan, and reports the scope digest, current main
commit, remaining IDs and retained inventory. It never reads SARIF or writes
GitHub state. New, missing or changed legacy records fail closed; a shorter
inventory is not automatically a successful retirement.

The [maintenance workflow](../../../.github/workflows/codeql-retire-legacy-actions.yml)
is manual and main-only. Once merged, its default dispatch runs validation and
the read-only preview:

```sh
gh workflow run codeql-retire-legacy-actions.yml \
  --repo Stuhlmuller/homelab --ref main \
  -f expected_sha='<reviewed-current-main-sha>'
```

Review the exact committed scope and `codeql-retirement-preview-<attempt>` artifact.
The scope digest identifies the approved deletion set; it is not a substitute
for approval. Retained scan IDs may grow as normal analyses finish.

## Approved execution

GitHub deletes analyses one at a time, newest first within a set. Deleting a
set's last analysis can lose historical alert data and change alert status.
The API requires explicit final-deletion confirmation. See the
[REST contract](https://docs.github.com/en/rest/code-scanning/code-scanning#delete-a-code-scanning-analysis-from-a-repository)
and [branch-scoped configuration removal](https://github.blog/changelog/2023-03-09-delete-stale-code-scanning-configurations-to-close-outdated-alerts/).
Re-running scans does not recreate the exact deleted history.

Only after explicit approval of this history loss, exact scope digest and
reviewed main commit, request the protected execution job:

```sh
gh workflow run codeql-retire-legacy-actions.yml \
  --repo Stuhlmuller/homelab --ref main \
  -f expected_sha='<reviewed-current-main-sha>' \
  -f approved_scope_sha256='<reviewed-scope-sha256>' \
  -f confirm_history_loss=true
```

The read-only job must pass repository static and policy gates before the
execution job reaches `homelab-production`. On September 6 that existing
environment required reviewer `rstuhlmuller` and permitted only `main`;
self-review and administrator bypass were enabled. This workflow changes none
of those controls. Do not automatically approve or bypass the retirement job.
Refresh the environment controls before approving an execution.

Only the protected job receives `security-events: write`. The helper checks a
clean checkout at exact current main, the unchanged active scanning workflow,
the approved scope digest, explicit history-loss consent, and fresh analysis
identities before deleting. It reconstructs API endpoints from approved IDs;
returned URLs cannot expand the scope. Every attempted deletion is recorded
durably before the request so an uncertain response can be reconciled.

Before the first DELETE, the protected job creates and successfully uploads an
immutable `codeql-retirement-authorized-<run-id>` artifact. It binds the exact
run, main commit and scope digest to the full identities of retained analyses.
Creation requires all 97 approved IDs still present. A failed or cancelled
upload prevents execution. The artifact contains public analysis metadata,
never raw SARIF or credentials, and is retained for 30 days.

To resume an interrupted execution, rerun the failed job or all jobs **within
the same workflow run** while the reviewed commit remains current main. Both
preview and execution download this run's authorization artifact, validate its
repository/run/commit provenance and content binding, and recheck retained
identities. Approved IDs already absent are recorded separately as recovered;
the helper does not claim that their DELETE responses were observed. Remaining
IDs must still match the reviewed scope before deletion. The artifact authorizes
only the original 97 IDs and never permits loss of retained history.

Preview and incremental execution receipts use attempt-specific artifact names,
so retries do not collide with prior uploads. Incremental receipt upload remains
best-effort after runner loss; recovery relies on the inventory already stored
before execution. A new workflow run cannot import the prior authorization.
Missing/expired artifacts, changed main, retained-identity drift, or missing IDs
without this run's authorization stop recovery. Review a new declared recovery
change in those cases; do not forge attempts or shrink the scope. The execution
step is bounded to 25 minutes inside a 40-minute job.

## Acceptance and rollback limits

Completion requires all approved main legacy IDs absent, no remaining legacy
main configuration, and retained analyses still present. Then inspect fresh
main and PR Actions results and verify the obsolete-category warning no longer
prevents introduced-alert comparison. Successful deletion alone does not prove
that final comparison works. Keep the audit finding open if it does not.

Historical deletion has no exact rollback. The active CodeQL workflow stays
enabled throughout; rerunning the old configuration can reinstate a stale
configuration and does not restore its original history. Do not delete other
refs, dismiss alerts, rename the active category or disable scanning to obtain
a green aggregate.

Local validation:

```sh
nix develop --command python3 scripts/ci/codeql-retire-legacy-actions-test.py
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
```

Related: [[validation-gates]], [[continuous-improvement]].

Current-main integration refreshes only the active workflow fingerprint; the 97
legacy analysis identities remain fixed. Run a fresh read-only preview before
requesting historical deletion. Earlier preview receipts do not authorize this
updated scope digest.
