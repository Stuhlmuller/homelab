# Unlocked-tailnet specification amendment

- Stage: specify complete; next: clarify the mode/identity and evidence contract.
- Base: 0f4f806262d9d2cf0ab1296334e4d907a2ce5f3f.
- Branch: fix/adguard-unlocked-tailnet.
- Existing feature and issue1842 retained; no Notion writes.
- Source evidence: local_signer requires Enabled=true, NodeKeySigned=true and
  trusted local signing key; validate_target requires enabled Lock and lock-peer
  matching; adguard-check snapshot uses both and requires signed=true.
- Owner confirms Lock disabled. This explains the reported preflight failure;
  no new live state or signature claim is made.
- Requirements added: FR-020/021 and SC-007; four acceptance scenarios.
- Constitution unchanged. Existing spec template and feature selector reused.
  Local extensions declare hooks: {}; no hooks executed.
- Requirement quality review: 16/16 pass, no essential user question.
- Code, live Lock and DNS unchanged. No implementation tests applicable yet.
- Subsequent stages must reconcile the existing plan, tasks, contracts and
  runbooks before implementation and keep unknown mode fail-closed.
