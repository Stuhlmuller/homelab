# Restore Decryption RBAC Enforcement Evidence (2026-04-05)

## Scope
Implements policy-as-code guardrails for [HOM-107](/HOM/issues/HOM-107):

- least-privilege functional roles (`key_admin`, `backup_operator`, `restore_approver`, `restore_executor`)
- tier-based restore approval requirements
- mutual exclusion between restore approver and restore executor roles
- requester/approver/executor identity separation
- time-bound grant TTL limits by tier

## Artifacts
- `policies/restore_decryption_policy.json`
- `scripts/preflight_policy_guardrails.py`
- `scripts/run_policy_fixtures.py`
- `fixtures/policy/pass/restore-tier0-dual-control-valid.json`
- `fixtures/policy/pass/restore-tier1-valid.json`
- `fixtures/policy/fail/restore-tier0-approver-executor-overlap.json`
- `fixtures/policy/fail/restore-tier0-approver-self-declared-role-escalation.json`
- `fixtures/policy/fail/restore-tier0-grant-ttl-boolean.json`
- `fixtures/policy/fail/restore-tier0-grant-ttl-zero.json`
- `fixtures/policy/fail/restore-tier0-missing-security-approval.json`
- `fixtures/policy/fail/restore-tier1-grant-ttl-exceeds-limit.json`

## Validation
- `python3 scripts/run_policy_fixtures.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`

Both commands pass in the implementation workspace.
